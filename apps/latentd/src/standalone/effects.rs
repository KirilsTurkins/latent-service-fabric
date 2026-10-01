//! Deferred dispatch shares the transaction runtime's one protected database.
//! The trusted composition root supplies current authority, exact installed
//! provider profiles and protected clock/checkpoint evidence before readiness.

use std::sync::Arc;
use std::time::Instant;

use latent_effects::authority::EffectAuthorityOwner;
use latent_effects::runtime::{
    CommandAdmission, CommandAdmissionSource, DeferredEffectAdapter, DispatcherConfig,
    DispatcherError, DispatcherOwner, EffectTimeSource, RequiredProfilePage,
};
use latent_state::protected_store::ProtectedStoreOwner;

use super::{error, PlatformError, PlatformErrorCode, StandaloneNode};

pub use latent_effects::runtime::{
    DispatcherControlError, DispatcherControlJob, DispatcherControlLookup,
    DispatcherControlRequest, PreparedDispatcherControl,
};
pub use latent_effects::runtime::{DispatcherShutdown as EffectShutdownReport, DispatcherSnapshot};

/// One fixed scheduling owner. Its accepted providers and root registration
/// survive a dropped shutdown waiter until actual physical cleanup completes.
pub struct EffectRuntime {
    owner: DispatcherOwner,
}

impl EffectRuntime {
    #[must_use]
    pub fn management_port(&self) -> latent_effects::runtime::DispatcherManagementPort {
        self.owner.management_port()
    }
    pub async fn start(
        config: DispatcherConfig,
        store: Arc<ProtectedStoreOwner>,
        authority: EffectAuthorityOwner,
        adapters: Vec<Arc<dyn DeferredEffectAdapter>>,
        time: Arc<dyn EffectTimeSource>,
        minimum_checkpoint: Option<(u64, u64)>,
        control_runtime: tokio::runtime::Handle,
    ) -> Result<Self, PlatformError> {
        DispatcherOwner::start_with_runtime(
            config,
            store,
            authority,
            adapters,
            time,
            minimum_checkpoint,
            control_runtime,
        )
        .await
        .map(|owner| Self { owner })
        .map_err(runtime_error)
    }

    #[must_use]
    pub fn command_admission_source(&self) -> CommandAdmissionSource {
        self.owner.command_admission_source()
    }
    pub fn command_admission(&self) -> Result<CommandAdmission, PlatformError> {
        self.owner.command_admission().map_err(runtime_error)
    }
    pub fn command_owner_epoch(&self) -> Result<u64, PlatformError> {
        self.owner.command_owner_epoch().map_err(runtime_error)
    }
    pub fn command_time(&self) -> Result<latent_effects::authority::EffectTime, PlatformError> {
        self.owner.command_time().map_err(runtime_error)
    }

    pub fn snapshot(&self) -> Result<DispatcherSnapshot, PlatformError> {
        self.owner.snapshot().map_err(runtime_error)
    }

    pub async fn required_profile_page(
        &self,
        cursor: Option<Vec<u8>>,
        rows: usize,
        bytes: usize,
    ) -> Result<RequiredProfilePage, PlatformError> {
        self.owner
            .required_profile_page(cursor, rows, bytes)
            .await
            .map_err(runtime_error)
    }

    /// Management checks its current policy before invoking these host ports.
    pub fn pause(&self) {
        self.owner.pause();
    }
    pub fn resume(&self) -> Result<(), PlatformError> {
        self.owner.resume().map_err(runtime_error)
    }
    pub fn prepare_dispatcher_control(
        &self,
        request: DispatcherControlRequest,
    ) -> Result<PreparedDispatcherControl, DispatcherControlError> {
        self.owner.prepare_control(request)
    }
    pub fn submit_dispatcher_control(
        &self,
        prepared: PreparedDispatcherControl,
        authorize: impl FnOnce(
                &mut dyn FnMut() -> Result<(), DispatcherControlError>,
            ) -> Result<(), DispatcherControlError>
            + Send
            + 'static,
    ) -> Result<DispatcherControlJob, DispatcherControlError> {
        self.owner.submit_control(prepared, authorize)
    }
    pub fn lookup_dispatcher_control(
        &self,
        request: DispatcherControlRequest,
    ) -> Result<DispatcherControlLookup, DispatcherControlError> {
        self.owner.lookup_control(request)
    }
    pub fn require_dispatcher_restore_review(&self) -> Result<(), DispatcherControlError> {
        self.owner.require_restore_review()
    }
    pub fn wake(&self) {
        self.owner.wake();
    }
    pub fn close(&self) {
        self.owner.close();
    }

    pub async fn shutdown(
        &mut self,
        deadline: Instant,
    ) -> Result<EffectShutdownReport, PlatformError> {
        self.owner.shutdown(deadline).await.map_err(runtime_error)
    }
}

impl StandaloneNode {
    /// Called by the trusted state composition before exposing readiness. It
    /// supplies the same physical owner, already validated family/link registry,
    /// provider authority and admitted checkpoint; this never opens another DB.
    pub fn install_effects(&mut self, runtime: EffectRuntime) -> Result<(), PlatformError> {
        if self.effects.is_some() {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "effect runtime already installed",
            ));
        }
        self.effects = Some(runtime);
        Ok(())
    }

    pub fn effects_snapshot(&self) -> Result<Option<DispatcherSnapshot>, PlatformError> {
        self.effects
            .as_ref()
            .map(EffectRuntime::snapshot)
            .transpose()
    }
}

fn runtime_error(reason: DispatcherError) -> PlatformError {
    let (code, message) = match reason {
        DispatcherError::InvalidConfiguration
        | DispatcherError::UnsupportedOrdering
        | DispatcherError::InvalidAdapter => (
            PlatformErrorCode::InvalidArgument,
            "invalid deferred effect configuration",
        ),
        DispatcherError::CheckpointRequired => (
            PlatformErrorCode::Unavailable,
            "deferred dispatch requires protected restore checkpoint reconciliation",
        ),
        DispatcherError::AdmissionClosed => (
            PlatformErrorCode::Unavailable,
            "deferred effect admission closed",
        ),
        DispatcherError::Authority(_) => (
            PlatformErrorCode::Unavailable,
            "deferred effect current authority or clock unavailable",
        ),
        DispatcherError::Store(_)
        | DispatcherError::ProtectedStore(_)
        | DispatcherError::Worker(_) => (
            PlatformErrorCode::Unavailable,
            "deferred effect physical owner requires recovery",
        ),
    };
    error(code, message)
}
