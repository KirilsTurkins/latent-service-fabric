use super::{
    accept, current, prepare, ActivationClock, Arc, ProtectedStoreError, ProtectedStoreStartup,
    RestoreAdoptionKind, RestoreAdoptionPlan, RestoreAdoptionStartError, StoreError,
    PLAN_RESPONSE_BYTES,
};
use crate::protected_store::{
    checkpoint::CheckpointFile,
    physical::{FailureLatch, PhysicalStore},
    startup::{start_initializer, StartupReservation},
    RESTORE_INPUT_RESPONSE_BYTES,
};

pub(super) fn start(
    mut plan: RestoreAdoptionPlan,
    clock: Arc<dyn ActivationClock>,
) -> Result<ProtectedStoreStartup, RestoreAdoptionStartError> {
    if let Err(reason) = plan.check_retired() {
        return Err(RestoreAdoptionStartError {
            reason,
            plan: Some(Box::new(plan)),
        });
    }
    // A once-Fresh root is now an existing reviewed object. Initialization may
    // never create a replacement engine or issue another Fresh witness.
    plan.config.store.create_if_missing = false;
    let reservation = match StartupReservation::new(
        &plan.config.store,
        RESTORE_INPUT_RESPONSE_BYTES + PLAN_RESPONSE_BYTES,
    ) {
        Ok(reservation) => reservation,
        Err(reason) => {
            return Err(RestoreAdoptionStartError {
                reason,
                plan: Some(Box::new(plan)),
            })
        }
    };
    start_initializer(reservation, clock, move |failure| {
        initialize(&plan, failure)
    })
    .map_err(|reason| RestoreAdoptionStartError { reason, plan: None })
}

fn initialize(
    plan: &RestoreAdoptionPlan,
    failure: Arc<FailureLatch>,
) -> Result<PhysicalStore, ProtectedStoreError> {
    plan.check_retired()?;
    current(plan).map_err(ProtectedStoreError::Store)?;
    let store =
        PhysicalStore::initialize_adopted(&plan.config.store, failure, plan.store_fence, |view| {
            prepare::verify_view(plan, view)
        })?;
    if store.restore_fence()? != plan.store_fence {
        return Err(ProtectedStoreError::UnsafeRoot);
    }
    let view = store
        .engine()
        .snapshot()
        .map_err(ProtectedStoreError::Store)?;
    let dispatch = Some(
        plan.stage
            .owners
            .dispatch_checkpoint(&view)
            .map_err(ProtectedStoreError::Store)?,
    );
    let checkpoint = CheckpointFile::open(
        &store,
        plan.config.checkpoint.clone(),
        plan.config.identity.clone(),
        None,
        dispatch,
        Arc::clone(&store.failure),
        plan.stage.input.original(),
    )
    .map_err(ProtectedStoreError::Store)?;
    if checkpoint
        .restore_fence()
        .map_err(ProtectedStoreError::Store)?
        != plan.checkpoint_fence
        || checkpoint
            .inspect(&view, dispatch)
            .map_err(ProtectedStoreError::Store)?
            .checkpoint
            .as_ref()
            != Some(&plan.stage.checkpoint)
    {
        return Err(ProtectedStoreError::Store(StoreError::Conflict));
    }
    prepare::verify_view(plan, &view).map_err(ProtectedStoreError::Store)?;
    drop(view);
    // Releasing these temporary checkpoint handles happens on this accepted
    // initializer before readiness, never in a caller's timeout path.
    drop(checkpoint);
    store.restore_fence()?;
    accept(plan, RestoreAdoptionKind::PublishPaused).map_err(ProtectedStoreError::Store)?;
    store.restore_fence()?;
    Ok(store)
}
