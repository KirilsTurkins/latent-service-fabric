use super::failure::Failure;
use crate::{config::NodeSettings, standalone::StandaloneNode};
use latent_core::{PlatformError, PrincipalKind, SystemActivationClock, TenantId};
use latent_effects::{dispatch_store::DispatchCatalog, runtime::EffectTimeSource};
use latent_state::{
    embedded::StoreError,
    protected_store::{ProtectedStoreConfig, ProtectedStoreOwner, ProtectedStoreStartup},
    store_io::{StoreIoKind, StoreIoSnapshot},
};
use serde::Serialize;
use std::{
    sync::{Arc, Mutex},
    time::Instant,
};

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TransactionStoreDiagnosis {
    schema_version: &'static str,
    stage: Stage,
    failure: Option<Failure>,
    linked_validation_started: bool,
    linked_validation_failure: Option<Failure>,
    original_checkpoint: (u64, u64),
    retained_owner_checkpoint: Option<(u64, u64)>,
    actual_clock_continuity: bool,
    retirement: Option<Retirement>,
}
#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
enum Stage {
    ProtectedInitialization,
    RetainedOwnerRead,
    Complete,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Retirement {
    clean: bool,
    physically_retired: bool,
    live_workers: usize,
    accepted_jobs: usize,
    threads_joined: Option<usize>,
}

impl StandaloneNode {
    /// Private native operator diagnosis of an existing protected owner. Uses
    /// exactly the ordinary settings-bound linked registry and tenant census;
    /// it never creates/reset rows,
    /// initializes an epoch, starts dispatch, invokes a guest or grants recovery.
    /// Configuration and token must come from protected native operator files.
    pub async fn diagnose_transaction_store(
        settings: &NodeSettings,
        credential: &str,
        tenant: &TenantId,
    ) -> Result<TransactionStoreDiagnosis, PlatformError> {
        let principal =
            crate::standalone::transport::credential_principal(&settings.transport, credential)
                .ok_or_else(super::super::denied)?;
        if !settings.credentials_from_protected_file
            || principal.kind != PrincipalKind::Administrator
            || principal.tenant.as_ref() != Some(tenant)
            || settings.state.is_none()
        {
            return Err(super::super::denied());
        }
        let clock: Arc<dyn latent_core::ActivationClock> = Arc::new(SystemActivationClock);
        let time = super::super::clock::ProtectedCommandClock::load(settings, Arc::clone(&clock))?;
        let mut observed = TransactionStoreDiagnosis {
            schema_version: "latent.transaction-store-diagnosis.v1",
            stage: Stage::ProtectedInitialization,
            failure: None,
            linked_validation_started: false,
            linked_validation_failure: None,
            original_checkpoint: time.minimum_checkpoint(),
            retained_owner_checkpoint: None,
            actual_clock_continuity: time.observe().continuity_proven,
            retirement: None,
        };
        let validation = Arc::new(Mutex::new((false, None)));
        let notice = Arc::clone(&validation);
        let deadline = Instant::now() + settings.shutdown_grace();
        let state = settings.state.as_ref().ok_or_else(super::super::denied)?;
        let validator = super::super::validation::startup(state, deadline)?;
        let mut config =
            ProtectedStoreConfig::bounded_linux(state.protected_root(&settings.data_directory));
        config.create_if_missing = false;
        let startup = ProtectedStoreOwner::start_validated_view_with_clock(
            config,
            super::super::validation::STARTUP_VALIDATION_BYTES,
            move |view| {
                *notice.lock().map_err(|_| StoreError::Unavailable)? = (true, None);
                let result = validator.validate(view);
                *notice.lock().map_err(|_| StoreError::Unavailable)? = (true, Some(result));
                result
            },
            clock,
        );
        match startup {
            Err(error) => observed.failure = Some(error.into()),
            Ok(mut startup) => match (&mut startup).await {
                Err(error) => {
                    observed.failure = Some(error.into());
                    observed.retirement = retire_startup(&startup, deadline).await;
                }
                Ok(owner) => {
                    observed.stage = Stage::RetainedOwnerRead;
                    read_owner(&owner, &mut observed).await;
                    observed.retirement = retire_owner(&owner, deadline).await;
                }
            },
        }
        let linked = validation.lock().map_err(|_| super::super::unavailable())?;
        observed.linked_validation_started = linked.0;
        observed.linked_validation_failure = linked.1.and_then(Result::err).map(Failure::from);
        Ok(observed)
    }
}

async fn read_owner(owner: &ProtectedStoreOwner, observed: &mut TransactionStoreDiagnosis) {
    let job = owner.with_store(StoreIoKind::Read, 4 * 1024 * 1024, |store| {
        DispatchCatalog::owner_checkpoint(&store.snapshot()?)
    });
    match job {
        Err(error) => observed.failure = Some(error.into()),
        Ok(job) => match job.await {
            Err(error) => observed.failure = Some(error.into()),
            Ok(Err(error)) => observed.failure = Some(error.into()),
            Ok(Ok(checkpoint)) => {
                observed.retained_owner_checkpoint = checkpoint;
                observed.stage = Stage::Complete;
            }
        },
    }
}

fn retirement(snapshot: StoreIoSnapshot, clean: bool, joined: Option<usize>) -> Retirement {
    Retirement {
        clean,
        physically_retired: snapshot.physically_retired(),
        live_workers: snapshot.live_workers,
        accepted_jobs: snapshot.accepted,
        threads_joined: joined,
    }
}
async fn retire_startup(startup: &ProtectedStoreStartup, deadline: Instant) -> Option<Retirement> {
    startup.close();
    let drain = startup
        .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
        .ok()?;
    let result = drain.await;
    Some(retirement(
        result.snapshot,
        result.clean,
        startup.reap_retired_threads().ok(),
    ))
}
async fn retire_owner(owner: &ProtectedStoreOwner, deadline: Instant) -> Option<Retirement> {
    owner.close();
    let drain = owner
        .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
        .ok()?;
    let result = drain.await;
    Some(retirement(
        result.snapshot,
        result.clean,
        owner.reap_retired_threads().ok(),
    ))
}
