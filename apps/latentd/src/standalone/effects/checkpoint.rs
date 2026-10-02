//! Bootstrap checkpoint files retire on the original recovery workers before
//! the trusted composition receives a dispatcher or command admission port.
use std::sync::Arc;
use std::time::Instant;

use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeReservation,
        NativeReservationRequest,
    },
    ActivationClock,
};
use latent_effects::{
    authority::EffectAuthorityOwner,
    dispatch_store::DispatchCatalog,
    runtime::{DeferredEffectAdapter, DispatcherConfig},
};
use latent_policy::supply_chain::SupplyChainAuthority;
use latent_state::{
    embedded::{EmbeddedStore, StoreError},
    protected_store::{ProtectedCheckpointConfig, ProtectedStoreOwner},
    store_identity::StoreIdentity,
    store_io::StoreIoKind,
};

use super::{error, EffectRuntime, PlatformError, PlatformErrorCode, ProtectedEffectClock};

const CHECKPOINT_WORK_BYTES: u64 = 64 * 1024;
const MAXIMUM_PREPARATION_BYTES: u64 = 1024 * 1024;

type PreparationAction =
    Box<dyn FnOnce(&EmbeddedStore, &NativeReservation) -> Result<(), StoreError> + Send>;

/// Trusted finite tenant/bootstrap preparation. It runs on the SAME recovery
/// writer after Fresh checkpoint creation, never on the async runtime. The
/// original reservation is descriptive capacity/deadline evidence; actual
/// namespace, tenant and policy publication still use their original owners.
pub struct ProtectedStatePreparation {
    retained_bytes: u64,
    action: PreparationAction,
}

impl ProtectedStatePreparation {
    pub fn new(
        retained_bytes: u64,
        action: impl FnOnce(&EmbeddedStore, &NativeReservation) -> Result<(), StoreError>
            + Send
            + 'static,
    ) -> Result<Self, PlatformError> {
        if retained_bytes == 0 || retained_bytes > MAXIMUM_PREPARATION_BYTES {
            return Err(unavailable());
        }
        Ok(Self {
            retained_bytes,
            action: Box::new(action),
        })
    }
}

struct PreparationKeeper {
    _buffer: NativeBufferPermit,
    _original: Arc<NativeReservation>,
}

/// Inputs supplied by the trusted standalone composition. Limits and paths
/// grant no namespace or dispatch authority; the admitted store and its SAME
/// global recovery owner must already exist. The deadline is never refreshed.
pub struct ProtectedEffectStartup {
    pub dispatcher: DispatcherConfig,
    pub store: Arc<ProtectedStoreOwner>,
    pub authority: EffectAuthorityOwner,
    pub adapters: Vec<Arc<dyn DeferredEffectAdapter>>,
    pub supply_chain: Arc<SupplyChainAuthority>,
    pub clock: Arc<dyn ActivationClock>,
    pub checkpoint: ProtectedCheckpointConfig,
    pub identity: StoreIdentity,
    pub preparation: Option<super::ProtectedStatePreparation>,
    pub original_deadline: Instant,
    pub control_runtime: tokio::runtime::Handle,
}

struct StartupGuard {
    store: Arc<ProtectedStoreOwner>,
    complete: bool,
}

impl Drop for StartupGuard {
    fn drop(&mut self) {
        if !self.complete {
            // Dropping an observation cannot cancel a native checkpoint job,
            // release its keeper or permit another owner to reuse this store.
            self.store.quarantine();
        }
    }
}

impl EffectRuntime {
    /// Inspect durable continuity, start this one role paused, persist its new
    /// epoch/floor and positively retire the external file before returning.
    /// Dispatch remains paused for the caller's normal readiness sequence;
    /// restore review still requires its independent authenticated operation.
    pub async fn start_protected(
        mut startup: super::ProtectedEffectStartup,
    ) -> Result<(Self, Arc<ProtectedEffectClock>), PlatformError> {
        let mut guard = StartupGuard {
            store: Arc::clone(&startup.store),
            complete: false,
        };
        startup.dispatcher.start_paused = true;
        let deadline = startup.original_deadline;
        let result = tokio::time::timeout_at(deadline.into(), admitted(startup))
            .await
            .map_err(|_| unavailable())??;
        guard.complete = true;
        Ok(result)
    }
}

async fn admitted(
    startup: ProtectedEffectStartup,
) -> Result<(EffectRuntime, Arc<ProtectedEffectClock>), PlatformError> {
    let store = &startup.store;
    let native = store.native_capacity().map_err(|_| unavailable())?;
    let preparation_bytes = startup
        .preparation
        .as_ref()
        .map_or(0, |preparation| preparation.retained_bytes);
    let keeper = Arc::new(
        native
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    work_bytes: CHECKPOINT_WORK_BYTES
                        .checked_add(preparation_bytes)
                        .ok_or_else(unavailable)?,
                    ..NativeReservationRequest::default()
                },
                startup.original_deadline,
            )
            .map_err(|_| unavailable())?,
    );
    let fresh = store
        .take_initialization_witness()
        .map_err(|_| unavailable())?
        .await
        .map_err(|_| unavailable())?
        .map_err(|_| unavailable())?;
    let (mut checkpoint, opened) = store
        .open_checkpoint(
            startup.checkpoint,
            startup.identity,
            fresh,
            Arc::clone(&keeper),
            DispatchCatalog::checkpoint,
        )
        .map_err(|_| unavailable())?
        .await
        .map_err(|_| unavailable())?;
    opened.map_err(|_| unavailable())?;
    let retired = checkpoint.retirement_witness().ok_or_else(unavailable)?;
    let (checkpoint, inspected) = store
        .inspect_checkpoint(checkpoint, DispatchCatalog::checkpoint)
        .map_err(|_| unavailable())?
        .await
        .map_err(|_| unavailable())?;
    let inspected = inspected.map_err(|_| unavailable())?;
    let time = ProtectedEffectClock::admit(
        startup.clock,
        startup.supply_chain,
        inspected.checkpoint.as_ref(),
    )?;
    if let Some(preparation) = startup.preparation {
        prepare(store, &keeper, preparation).await?;
        time.sample()?;
    }
    let minimum = inspected
        .checkpoint
        .as_ref()
        .map(|old| (old.dispatch_owner_epoch(), old.clock_floor_millis()));
    let effects = EffectRuntime::start(
        startup.dispatcher,
        Arc::clone(store),
        startup.authority,
        startup.adapters,
        time.clone(),
        minimum,
        startup.control_runtime,
    )
    .await?;
    effects.bind_native_capacity(&native)?;
    let (checkpoint, advanced) = store
        .advance_checkpoint(
            checkpoint,
            inspected.checkpoint,
            time.covered_epoch()?,
            DispatchCatalog::checkpoint,
        )
        .map_err(|_| unavailable())?
        .await
        .map_err(|_| unavailable())?;
    advanced.map_err(|_| unavailable())?;
    checkpoint.retire().await;
    if !retired.has_retired() {
        return Err(unavailable());
    }
    time.sample()?;
    Ok((effects, time))
}

async fn prepare(
    store: &ProtectedStoreOwner,
    original: &Arc<NativeReservation>,
    preparation: ProtectedStatePreparation,
) -> Result<(), PlatformError> {
    let buffer = original
        .reserve_buffer(NativeBufferClass::Work, preparation.retained_bytes)
        .map_err(|_| unavailable())?;
    let retained = Arc::new(PreparationKeeper {
        _buffer: buffer,
        _original: Arc::clone(original),
    });
    let original = Arc::clone(original);
    store
        .with_store_retaining(
            StoreIoKind::RecoveryWrite,
            preparation.retained_bytes,
            retained,
            move |engine| {
                // No native-capacity mutex spans filesystem I/O. The trusted
                // preparation also retains this exact deadline in each actual
                // publication fence, without manufacturing another keeper.
                original
                    .with_live(|| ())
                    .map_err(|_| StoreError::Unavailable)?;
                (preparation.action)(engine, &original)?;
                original
                    .with_live(|| ())
                    .map_err(|_| StoreError::Unavailable)
            },
        )
        .map_err(|_| unavailable())?
        .await
        .map_err(|_| unavailable())?
        .map_err(|_| unavailable())
}

fn unavailable() -> PlatformError {
    error(
        PlatformErrorCode::Unavailable,
        "protected transaction startup is unavailable",
    )
}
