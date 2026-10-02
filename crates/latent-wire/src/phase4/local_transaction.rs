//! The ordinary authenticated RPC uses the existing native activation lifecycle.
mod projection;
mod selection;

use super::{OwnedPhase4Response, Phase4Call, Phase4Runtime};
use crate::invocation::{
    ActivationCleanupHandle, InvocationLimits, InvocationTraceSource, PrincipalPolicy,
};
use latent_core::{ActivationClock, BoxFuture, IncomingDeadline, PlatformError, PlatformErrorCode};
use latent_node::{
    transaction_runtime::{
        NativeTransactionAdmission, TransactionAdmissionOwners, TransactionInstallation,
    },
    LocalActivationManager,
};
use latent_rpc::phase4 as contract;
use std::sync::Arc;

pub struct LocalTransactionServices {
    pub clock: Arc<dyn ActivationClock>,
    pub principals: Arc<dyn PrincipalPolicy>,
    pub traces: Arc<dyn InvocationTraceSource>,
}

pub struct LocalTransactionRuntime {
    manager: LocalActivationManager,
    cleanup: ActivationCleanupHandle,
    owners: Arc<TransactionAdmissionOwners>,
    installations: Vec<Arc<TransactionInstallation>>,
    management: Arc<dyn Phase4Runtime>,
    limits: InvocationLimits,
    services: LocalTransactionServices,
}
impl LocalTransactionRuntime {
    #[allow(
        clippy::too_many_arguments,
        reason = "Same installed lifecycle and authority owners are explicit"
    )]
    pub fn new(
        manager: LocalActivationManager,
        cleanup: ActivationCleanupHandle,
        owners: Arc<TransactionAdmissionOwners>,
        installations: Vec<Arc<TransactionInstallation>>,
        management: Arc<dyn Phase4Runtime>,
        limits: InvocationLimits,
        services: LocalTransactionServices,
    ) -> Result<Self, PlatformError> {
        limits.validate()?;
        if limits.budget_profile != latent_core::BudgetProfile::Phase4
            || installations.is_empty()
            || installations.len() > 128
        {
            return Err(error(PlatformErrorCode::IncompatibleContract));
        }
        Ok(Self {
            manager,
            cleanup,
            owners,
            installations,
            management,
            limits,
            services,
        })
    }

    fn start(
        &self,
        call: Phase4Call,
    ) -> Result<BoxFuture<'_, Result<OwnedPhase4Response, PlatformError>>, PlatformError> {
        call.request()
            .validate()
            .map_err(|_| error(PlatformErrorCode::InvalidArgument))?;
        self.services
            .principals
            .authenticate(call.context().principal())?;
        let expires_at = call
            .context()
            .transport_expires_at()
            .ok_or_else(|| error(PlatformErrorCode::InvalidArgument))?;
        if self.services.clock.monotonic_now() >= expires_at {
            return Err(error(PlatformErrorCode::DeadlineExceeded));
        }
        let native = self
            .owners
            .reserve_ingress(call.request().encoded_len(), expires_at)?;
        let slot = self.cleanup.reserve_activation()?;
        let (context, message) = call.into_parts();
        let selected = selection::select(&self.installations, message, context.principal())?;
        let trace = self.services.traces.next_trace()?;
        let request = crate::invocation::transaction_request(
            selected.invocation,
            &context,
            trace,
            &self.limits,
            self.services.principals.as_ref(),
        )?;
        let incoming = IncomingDeadline::new(
            expires_at,
            context
                .transport_deadline_unix_millis()
                .ok_or_else(|| error(PlatformErrorCode::InvalidArgument))?,
        );
        let admission = Arc::new(NativeTransactionAdmission::with_ingress_reservation(
            Arc::clone(&self.owners),
            Arc::clone(&selected.installation),
            selected.selection,
            native,
        )?);
        let handle = self.manager.start_transaction_with_deadline(
            request,
            Some(incoming),
            admission.clone(),
        )?;
        let retained = slot.own(handle, admission);
        let installation = selected.installation;
        Ok(Box::pin(async move {
            let (receipt, admission) = retained.await;
            let owned = admission
                .take_owned_completion()?
                .ok_or_else(|| error(PlatformErrorCode::Unavailable))?;
            projection::response(
                receipt,
                owned,
                &installation,
                &self.limits,
                self.services.clock.as_ref(),
            )
        }))
    }
}
impl Phase4Runtime for LocalTransactionRuntime {
    fn execute(
        &self,
        call: Phase4Call,
    ) -> BoxFuture<'_, Result<OwnedPhase4Response, PlatformError>> {
        if !matches!(
            call.request(),
            contract::Request::InvokeCommand(_) | contract::Request::Query(_)
        ) {
            return self.management.execute(call);
        }
        match self.start(call) {
            Ok(future) => future,
            Err(error) => Box::pin(std::future::ready(Err(error))),
        }
    }
}
fn error(code: PlatformErrorCode) -> PlatformError {
    PlatformError {
        code,
        message: "transactional invocation unavailable".into(),
        retryable: false,
        details: Vec::new(),
    }
}
