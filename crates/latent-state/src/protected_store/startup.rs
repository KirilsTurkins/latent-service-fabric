use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, OnceLock};
use std::task::{Context, Poll};
use std::time::Instant;

use latent_core::{ActivationClock, SystemActivationClock};

use super::physical::{validate_records, FailureLatch, PhysicalStore};
use super::{ProtectedStoreConfig, ProtectedStoreError, ProtectedStoreOwner};
use crate::embedded::{ReadView, RowKey, StoreError, StoreLimits};
use crate::store_io::{
    StoreIoDrain, StoreIoError, StoreIoOwner, StoreIoShutdown, StoreIoSnapshot, StoreIoStartup,
};

enum Starting {
    Running(StoreIoStartup<PhysicalStore>),
    Failed(StoreIoOwner<OnceLock<PhysicalStore>>, StoreIoError),
}

/// Owned startup; existing protected data is never reset on an error.
#[must_use = "readiness requires observing initialization; dropping detaches accepted work"]
pub struct ProtectedStoreStartup {
    state: Starting,
    failure: Arc<FailureLatch>,
    limits: StoreLimits,
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
        let initialization_bytes = config
            .validate()?
            .checked_add(8 * 1024 * 1024)
            .and_then(|bytes| bytes.checked_add(validator_retained_bytes))
            .ok_or(ProtectedStoreError::InvalidConfiguration)?;
        if initialization_bytes
            .checked_add(4096)
            .is_none_or(|bytes| bytes > config.io.job_bytes)
            || initialization_bytes
                .checked_add(config.io.resident_bytes)
                .and_then(|bytes| bytes.checked_add(4096))
                .is_none_or(|bytes| bytes > config.io.retained_bytes)
        {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        if !cfg!(all(target_os = "linux", target_arch = "x86_64")) {
            return Err(ProtectedStoreError::UnsupportedPlatform);
        }
        let failure = Arc::new(FailureLatch::default());
        let initializer_failure = Arc::clone(&failure);
        let limits = config.engine;
        let io = config.io.clone();
        let started = StoreIoOwner::initialize_with_clock(
            move || {
                PhysicalStore::initialize(&config, Arc::clone(&initializer_failure), validator)
                    .map_err(|error| {
                        initializer_failure.record(error);
                        StoreIoError::InitializationFailed
                    })
            },
            initialization_bytes,
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
        })
    }
}

impl ProtectedStoreStartup {
    pub fn snapshot(&self) -> Result<StoreIoSnapshot, ProtectedStoreError> {
        match &self.state {
            Starting::Running(startup) => startup.snapshot(),
            Starting::Failed(owner, _) => owner.snapshot(),
        }
        .map_err(ProtectedStoreError::Io)
    }

    pub fn close(&self) {
        match &self.state {
            Starting::Running(startup) => startup.close(),
            Starting::Failed(owner, _) => owner.close(),
        }
    }

    pub fn quarantine(&self) {
        match &self.state {
            Starting::Running(startup) => startup.quarantine(),
            Starting::Failed(owner, _) => owner.quarantine(),
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
        };
        match result {
            Poll::Ready(Ok(ready)) => {
                this.failure.install(ready.failure_gate());
                Poll::Ready(Ok(ProtectedStoreOwner {
                    ready,
                    failure: Arc::clone(&this.failure),
                    limits: this.limits,
                }))
            }
            Poll::Ready(Err(error)) => Poll::Ready(Err(this
                .failure
                .get()
                .unwrap_or(ProtectedStoreError::Io(error)))),
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
