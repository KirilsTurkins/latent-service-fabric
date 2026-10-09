use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, OnceLock};
use std::task::{Context, Poll};
use std::time::Instant;

use latent_core::native_capacity::NativeReservation;
use latent_core::{ActivationClock, SystemActivationClock};

use super::native_capacity::NativeBinding;
use super::physical::{validate_records, FailureLatch, PhysicalStore};
use super::startup_memory::{memory_error, startup_memory_size, InitializationMemory};
use super::{
    ProtectedStoreConfig, ProtectedStoreError, ProtectedStoreOwner, ProtectedStoreStartupMemory,
};
use crate::embedded::{ReadView, RowKey, StoreError, StoreLimits};
use crate::store_io::{
    StoreIoDrain, StoreIoError, StoreIoOwner, StoreIoReady, StoreIoShutdown, StoreIoSnapshot,
    StoreIoStartup,
};

enum Starting {
    Running(StoreIoStartup<PhysicalStore>),
    Failed(StoreIoOwner<OnceLock<PhysicalStore>>, StoreIoError),
    RejectedReady(StoreIoReady<PhysicalStore>, ProtectedStoreError),
}

/// Owned startup; existing protected data is never reset on an error.
#[must_use = "readiness requires observing initialization; dropping detaches accepted work"]
pub struct ProtectedStoreStartup {
    state: Starting,
    failure: Arc<FailureLatch>,
    limits: StoreLimits,
    native_capacity: Arc<NativeBinding>,
    original: Option<Arc<NativeReservation>>,
}

impl ProtectedStoreOwner {
    pub fn start(
        config: ProtectedStoreConfig,
    ) -> Result<ProtectedStoreStartup, ProtectedStoreError> {
        Self::start_with_clock(config, Arc::new(SystemActivationClock))
    }

    pub fn start_with_clock(
        config: ProtectedStoreConfig,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<ProtectedStoreStartup, ProtectedStoreError> {
        Self::start_validated_with_clock(
            config,
            0,
            |_, _| Err(StoreError::UnsupportedFormat),
            clock,
        )
    }

    /// Current family codecs validate every persisted row before readiness.
    /// A codec must bound decode before allocation and explicitly reject any
    /// unsupported nonempty family. The default `start` accepts empty rows only.
    pub fn start_validated(
        config: ProtectedStoreConfig,
        validator_retained_bytes: u64,
        validator: impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError> + Send + 'static,
    ) -> Result<ProtectedStoreStartup, ProtectedStoreError> {
        Self::start_validated_with_clock(
            config,
            validator_retained_bytes,
            validator,
            Arc::new(SystemActivationClock),
        )
    }

    pub fn start_validated_with_clock(
        config: ProtectedStoreConfig,
        validator_retained_bytes: u64,
        mut validator: impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError> + Send + 'static,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<ProtectedStoreStartup, ProtectedStoreError> {
        Self::start_validated_view_with_clock(
            config,
            validator_retained_bytes,
            move |view| validate_records(view, &mut validator),
            clock,
        )
    }

    /// Validate the complete logical registry against one coherent native view
    /// on the accepted initialization worker before publishing readiness.
    /// The trusted validator must bound its pages, point reads and retained
    /// buffers and reject unsupported formats and inconsistent cross-row links.
    /// It cannot transfer the borrowed native view to another owner.
    pub fn start_validated_view(
        config: ProtectedStoreConfig,
        validator_retained_bytes: u64,
        validator: impl FnOnce(&ReadView) -> Result<(), StoreError> + Send + 'static,
    ) -> Result<ProtectedStoreStartup, ProtectedStoreError> {
        Self::start_validated_view_with_clock(
            config,
            validator_retained_bytes,
            validator,
            Arc::new(SystemActivationClock),
        )
    }

    pub fn start_validated_view_with_clock(
        config: ProtectedStoreConfig,
        validator_retained_bytes: u64,
        validator: impl FnOnce(&ReadView) -> Result<(), StoreError> + Send + 'static,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<ProtectedStoreStartup, ProtectedStoreError> {
        Self::start_validated_view_inner(
            config,
            None,
            None,
            validator_retained_bytes,
            validator,
            clock,
        )
    }

    /// Bind a store identity within the actual exclusive initializer, after
    /// validating existing logical rows and before publishing this owner.
    /// Only an actually committed empty-store identity batch can later produce
    /// a once-only initialization witness; matching existing identity cannot.
    pub fn start_bound_validated_view_with_clock(
        config: ProtectedStoreConfig,
        identity: crate::store_identity::StoreIdentity,
        validator_retained_bytes: u64,
        validator: impl FnOnce(&ReadView) -> Result<(), StoreError> + Send + 'static,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<ProtectedStoreStartup, ProtectedStoreError> {
        Self::start_validated_view_inner(
            config,
            Some(identity),
            None,
            validator_retained_bytes,
            validator,
            clock,
        )
    }

    /// Prepay initialization and resident engine memory on the node's original
    /// Recovery admission before creating workers or opening native files. The
    /// same owner is already bound when readiness is delivered; original memory
    /// survives detached startup waiters and actual engine/root destruction.
    pub fn start_bound_retained_validated_view_with_clock(
        config: ProtectedStoreConfig,
        identity: crate::store_identity::StoreIdentity,
        memory: ProtectedStoreStartupMemory,
        validator_retained_bytes: u64,
        validator: impl FnOnce(&ReadView) -> Result<(), StoreError> + Send + 'static,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<ProtectedStoreStartup, ProtectedStoreError> {
        Self::start_validated_view_inner(
            config,
            Some(identity),
            Some(memory),
            validator_retained_bytes,
            validator,
            clock,
        )
    }

    fn start_validated_view_inner(
        config: ProtectedStoreConfig,
        identity: Option<crate::store_identity::StoreIdentity>,
        memory: Option<ProtectedStoreStartupMemory>,
        validator_retained_bytes: u64,
        validator: impl FnOnce(&ReadView) -> Result<(), StoreError> + Send + 'static,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<ProtectedStoreStartup, ProtectedStoreError> {
        let size = startup_memory_size(&config, validator_retained_bytes)?;
        if !cfg!(all(target_os = "linux", target_arch = "x86_64")) {
            return Err(ProtectedStoreError::UnsupportedPlatform);
        }
        let (native_capacity, original, initialization_memory, resident_memory) = match memory {
            Some(memory) => {
                let prepared = memory.prepare(&size)?;
                (
                    prepared.binding,
                    Some(prepared.original),
                    Some(prepared.initialization),
                    Some(prepared.resident),
                )
            }
            None => (Arc::new(NativeBinding::default()), None, None, None),
        };
        let failure = Arc::new(FailureLatch::default());
        let initializer_failure = Arc::clone(&failure);
        let limits = config.engine;
        let io = config.io.clone();
        let started = StoreIoOwner::initialize_with_clock(
            move || {
                let result = initialization_memory
                    .as_ref()
                    .map_or(Ok(()), InitializationMemory::check)
                    .and_then(|()| {
                        PhysicalStore::initialize(
                            &config,
                            Arc::clone(&initializer_failure),
                            validator,
                            identity,
                            resident_memory,
                            initialization_memory.as_ref(),
                        )
                    });
                // Owned configuration/validator buffers and failed native
                // locals retire on this same worker before the init permit.
                drop(config);
                let result = result.map_err(|error| {
                    initializer_failure.record(error);
                    StoreIoError::InitializationFailed
                });
                drop(initialization_memory);
                result
            },
            size.initialization - 4096,
            io,
            PhysicalStore::finalize,
            clock,
        );
        let state = match started {
            Ok(startup) => {
                if let Some(gate) = startup.failure_gate() {
                    failure.install(gate);
                }
                Starting::Running(startup)
            }
            Err(error) => {
                let Some(owner) = error.owner else {
                    return Err(ProtectedStoreError::Io(error.reason));
                };
                Starting::Failed(owner, error.reason)
            }
        };
        Ok(ProtectedStoreStartup {
            state,
            failure,
            limits,
            native_capacity,
            original,
        })
    }
}

impl ProtectedStoreStartup {
    pub fn snapshot(&self) -> Result<StoreIoSnapshot, ProtectedStoreError> {
        match &self.state {
            Starting::Running(startup) => startup.snapshot(),
            Starting::Failed(owner, _) => owner.snapshot(),
            Starting::RejectedReady(ready, _) => ready.snapshot(),
        }
        .map_err(ProtectedStoreError::Io)
    }

    pub fn close(&self) {
        match &self.state {
            Starting::Running(startup) => startup.close(),
            Starting::Failed(owner, _) => owner.close(),
            Starting::RejectedReady(ready, _) => ready.close(),
        }
    }

    pub fn quarantine(&self) {
        match &self.state {
            Starting::Running(startup) => startup.quarantine(),
            Starting::Failed(owner, _) => owner.quarantine(),
            Starting::RejectedReady(ready, _) => ready.quarantine(),
        }
    }

    pub fn drain_async<F: Future<Output = ()>>(
        &self,
        deadline: Instant,
        wait: F,
    ) -> Result<ProtectedStoreDrain<F>, ProtectedStoreError> {
        match &self.state {
            Starting::Running(startup) => startup.drain_async(deadline, wait),
            Starting::Failed(owner, _) => owner.drain_async(deadline, wait),
            Starting::RejectedReady(ready, _) => ready.drain_async(deadline, wait),
        }
        .map(ProtectedStoreDrain::new)
        .map_err(ProtectedStoreError::Io)
    }
}

impl Future for ProtectedStoreStartup {
    type Output = Result<ProtectedStoreOwner, ProtectedStoreError>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        let result = match &mut this.state {
            Starting::Running(startup) => Pin::new(startup).poll(cx),
            Starting::Failed(_, error) => Poll::Ready(Err(*error)),
            Starting::RejectedReady(_, error) => return Poll::Ready(Err(*error)),
        };
        match result {
            Poll::Ready(Ok(ready)) => {
                this.failure.install(ready.failure_gate());
                let original = this.original.take();
                let mut ready = Some(ready);
                let mut publish = || ProtectedStoreOwner {
                    ready: ready.take().expect("single readiness publication"),
                    failure: Arc::clone(&this.failure),
                    limits: this.limits,
                    native_capacity: Arc::clone(&this.native_capacity),
                };
                let published = if let Some(original) = &original {
                    original.with_live(publish).map_err(memory_error)
                } else {
                    Ok(publish())
                };
                match published {
                    Ok(owner) => Poll::Ready(Ok(owner)),
                    Err(error) => {
                        // The original short gate has been released. Keep the
                        // private ready owner available for positive drain;
                        // neither a witness nor a business job can escape.
                        let ready = ready.expect("rejected gate did not publish readiness");
                        ready.quarantine();
                        this.failure.record(error);
                        this.state = Starting::RejectedReady(ready, error);
                        Poll::Ready(Err(error))
                    }
                }
            }
            Poll::Ready(Err(error)) => {
                drop(this.original.take());
                Poll::Ready(Err(this
                    .failure
                    .get()
                    .unwrap_or(ProtectedStoreError::Io(error))))
            }
            Poll::Pending => Poll::Pending,
        }
    }
}

/// One async node drain waiter; deadline expiry retains live view/engine owners.
pub struct ProtectedStoreDrain<F> {
    inner: StoreIoDrain<OnceLock<PhysicalStore>, F>,
}

impl<F> ProtectedStoreDrain<F> {
    pub(super) fn new(inner: StoreIoDrain<OnceLock<PhysicalStore>, F>) -> Self {
        Self { inner }
    }
}

impl<F: Future<Output = ()>> Future for ProtectedStoreDrain<F> {
    type Output = StoreIoShutdown;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        Pin::new(&mut self.get_mut().inner).poll(cx)
    }
}
