//! A sealed handle to the already installed dispatcher and physical engine.
use super::{
    control, worker::Services, DispatcherControlError, DispatcherControlOutcome,
    DispatcherControlReceipt, DispatcherControlRequest, DispatcherError, DispatcherOwner,
    DispatcherSnapshot, PreparedDispatcherControl,
};
use latent_state::{
    protected_store::{ProtectedStoreError, ProtectedStoreOwner},
    store_io::{StoreIoJob, StoreIoKind, StoreIoOwner},
};
use std::sync::Arc;

#[derive(Clone)]
pub struct DispatcherManagementPort {
    pub(super) services: Arc<Services>,
    pub(super) jobs: StoreIoOwner<Arc<Services>>,
}
/// Values drop before the same original retained request owner. An unclaimed
/// native completion therefore cannot refund the global work/response budget.
pub struct RetainedDispatcherControl<R> {
    pub outcome: Result<DispatcherControlOutcome, DispatcherControlError>,
    pub retained: R,
}
pub type RetainedDispatcherControlJob<R> =
    StoreIoJob<Result<RetainedDispatcherControl<R>, ProtectedStoreError>>;
pub struct RetainedDispatcherLookup<R> {
    pub receipt: Result<Option<DispatcherControlReceipt>, DispatcherControlError>,
    pub retained: R,
}
pub type RetainedDispatcherControlLookup<R> =
    StoreIoJob<Result<RetainedDispatcherLookup<R>, ProtectedStoreError>>;

impl DispatcherOwner {
    /// Creates no scheduler, provider pool, engine, recovery worker or role.
    #[must_use]
    pub fn management_port(&self) -> DispatcherManagementPort {
        DispatcherManagementPort {
            services: Arc::clone(&self.services),
            jobs: self.jobs.clone(),
        }
    }
}
impl DispatcherManagementPort {
    /// Call only inside the original Policy -> Namespace lifecycle fence, then
    /// accept under the original Native request gate before entering disk I/O.
    pub fn prepare_namespace_close(
        &self,
        tenant: &str,
        namespace: &str,
        incarnation: u64,
    ) -> Result<crate::authority::NamespaceEffectCloseFence<'_>, crate::authority::AuthorityError>
    {
        self.services
            .authority
            .prepare_namespace_close(tenant, namespace, incarnation)
    }
    #[must_use]
    pub fn uses_store(&self, store: &ProtectedStoreOwner) -> bool {
        self.services.store.is_same_owner(store)
    }
    /// Identity only. Operator inspection and reconciliation remain possible
    /// while ordinary execution is paused or restore review is required.
    #[must_use]
    pub fn uses_native_capacity(
        &self,
        owner: &latent_core::native_capacity::NativeCapacityOwner,
    ) -> bool {
        self.services.native_capacity.lock().is_ok_and(|binding| {
            binding
                .owner
                .as_ref()
                .is_some_and(|installed| installed.is_same_owner(owner))
        })
    }
    pub fn snapshot(&self) -> Result<DispatcherSnapshot, DispatcherError> {
        Ok(self
            .services
            .shared
            .snapshot(self.jobs.snapshot()?, self.services.authority.owners()?))
    }
    #[must_use]
    pub fn clock_continuity_proven(&self) -> bool {
        self.services.time.observe().continuity_proven
    }
    pub fn prepare_control(
        &self,
        request: DispatcherControlRequest,
    ) -> Result<PreparedDispatcherControl, DispatcherControlError> {
        control::prepare(&self.services, request)
    }
    /// `authorize` retains original node policy through final acceptance. `live`
    /// is called inside the actual dispatcher lock, after lifecycle validation,
    /// and encloses the bounded acceptance action under the original capacity/
    /// deadline gate. Neither callback may perform I/O, audit flush or await.
    pub fn submit_control_retained<R: Send + 'static>(
        &self,
        prepared: PreparedDispatcherControl,
        retained: R,
        retained_bytes: u64,
        authorize: impl FnOnce(
                &mut dyn FnMut() -> Result<(), DispatcherControlError>,
            ) -> Result<(), DispatcherControlError>
            + Send
            + 'static,
        live: impl FnOnce(
                &mut dyn FnMut() -> Result<(), DispatcherControlError>,
            ) -> Result<(), DispatcherControlError>
            + Send
            + 'static,
        complete: impl FnOnce(
                &Result<DispatcherControlOutcome, DispatcherControlError>,
                &mut R,
            ) -> Result<(), latent_state::embedded::StoreError>
            + Send
            + 'static,
    ) -> Result<RetainedDispatcherControlJob<R>, DispatcherControlError> {
        if !prepared.uses_services(&self.services) {
            return Err(DispatcherControlError::Conflict);
        }
        let bytes = retained_bytes
            .checked_add(64 * 1024)
            .ok_or(DispatcherControlError::Capacity)?;
        self.services
            .store
            .with_store(StoreIoKind::RecoveryWrite, bytes, move |store| {
                let mut retained = retained;
                let result = control::execute_guarded(store, &prepared, authorize, live);
                // The receipt/audit conclusion is completed by the accepted native
                // worker, including after the RPC waiter has gone away. No fence
                // lock remains held when this bounded completion callback runs.
                complete(&result, &mut retained)?;
                match result {
                    Err(DispatcherControlError::Store(error)) => Err(error),
                    outcome => Ok(RetainedDispatcherControl { outcome, retained }),
                }
            })
            .map_err(DispatcherControlError::from)
    }
    /// Caller seals current operator access before lookup and again before
    /// delivery. This preserves the exact historical action and precondition.
    pub fn lookup_control_retained<R: Send + 'static>(
        &self,
        request: DispatcherControlRequest,
        retained: R,
        retained_bytes: u64,
        before_lookup: impl FnOnce() -> Result<(), DispatcherControlError> + Send + 'static,
        complete: impl FnOnce(
                &Result<Option<DispatcherControlReceipt>, DispatcherControlError>,
                &mut R,
            ) -> Result<(), latent_state::embedded::StoreError>
            + Send
            + 'static,
    ) -> Result<RetainedDispatcherControlLookup<R>, DispatcherControlError> {
        request.validate()?;
        let bytes = retained_bytes
            .checked_add(32 * 1024)
            .ok_or(DispatcherControlError::Capacity)?;
        self.services
            .store
            .with_store(StoreIoKind::RecoveryRead, bytes, move |store| {
                let mut retained = retained;
                let receipt = match before_lookup() {
                    Ok(()) => Ok(crate::dispatch_store::control::ControlCatalog::lookup(
                        &store.snapshot()?,
                        &request,
                    )?),
                    Err(error) => Err(error),
                };
                complete(&receipt, &mut retained)?;
                Ok(RetainedDispatcherLookup { receipt, retained })
            })
            .map_err(DispatcherControlError::from)
    }
}
