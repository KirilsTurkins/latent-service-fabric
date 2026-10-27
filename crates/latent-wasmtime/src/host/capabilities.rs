//! Store-owned capability authority and canonical-ABI lowering reservations.
use latent_capabilities::broker::{CapabilityCallCost, CapabilitySession, ProviderCall};
use latent_core::PlatformError;
use latent_policy::capability::ResourceTarget;
mod failure;
mod retained;
pub(super) use failure::host_error;
pub(crate) use failure::HostCapabilityFailure;
use retained::Retained;

#[derive(Default)]
pub(crate) struct HostCapabilities {
    #[cfg(feature = "development-test-host")]
    pub(crate) development_host_admission_scope: Option<std::sync::Arc<crate::values::LiftMemory>>,
    // Destroy typed-result reservations before closing/destroying the session.
    // They remain charged through canonical lowering and component post-return.
    pub(super) blobs: super::blob::table::Table,
    pub(super) streams: super::streaming_http::table::Table,
    pub(super) network: super::networking::table::Table,
    lowering: Retained<ProviderCall>,
    secret_lowering: Retained<latent_capabilities::broker::secrets::SecretLowering>,
    pooled_lowering: Retained<latent_capabilities::broker::pools::PoolCall>,
    pub(super) session: Option<CapabilitySession>,
}
impl HostCapabilities {
    pub(super) async fn clock(
        &mut self,
        clock: latent_capabilities::broker::HostClock,
        wait: Option<&dyn latent_executor::PreparationReadWait>,
    ) -> wasmtime::Result<Option<ProviderCall>> {
        match (&self.session, wait) {
            (Some(session), Some(wait)) => session
                .begin_host_clock(clock, wait)
                .await
                .map(Some)
                .map_err(|error| {
                    #[cfg(feature = "development-test-host")]
                    self.observe_host_admission_refusal(
                        session,
                        crate::development_trap_observer::DevelopmentHostAdmissionEdge::ClockAdmission,
                        clock.capability(), clock.operation(), error.code,
                    );
                    host_error(error)
                }),
            _ => self.scalar(
                clock.capability(),
                clock.operation(),
                ResourceTarget::Clock,
                8,
            ),
        }
    }

    pub(crate) fn new(
        session: Option<CapabilitySession>,
        budget: &latent_core::ActivationBudget,
    ) -> Self {
        Self {
            #[cfg(feature = "development-test-host")]
            development_host_admission_scope: None,
            streams: super::streaming_http::table::Table::default(),
            network: super::networking::table::Table::default(),
            blobs: super::blob::table::Table::default(),
            lowering: Retained::new(budget),
            secret_lowering: Retained::new(budget),
            pooled_lowering: Retained::new(budget),
            session,
        }
    }
    pub(super) fn begin(
        &self,
        capability: &str,
        operation: &str,
        resource: ResourceTarget<'_>,
        input: &[u8],
        output_bytes: usize,
    ) -> Result<Option<ProviderCall>, PlatformError> {
        self.begin_typed(
            capability,
            operation,
            resource,
            input,
            CapabilityCallCost::new(output_bytes),
        )
    }
    pub(super) fn begin_typed(
        &self,
        capability: &str,
        operation: &str,
        resource: ResourceTarget<'_>,
        input: &[u8],
        cost: CapabilityCallCost,
    ) -> Result<Option<ProviderCall>, PlatformError> {
        let call = self.dispatch_typed(capability, operation, resource, input, cost)?;
        if let Some(call) = &call {
            call.require_host_mode()?;
        }
        Ok(call)
    }
    fn dispatch_typed(
        &self,
        capability: &str,
        operation: &str,
        resource: ResourceTarget<'_>,
        input: &[u8],
        cost: CapabilityCallCost,
    ) -> Result<Option<ProviderCall>, PlatformError> {
        let Some(session) = &self.session else {
            return Ok(None);
        };
        let handle = session
            .bind(capability, operation, resource)
            .map_err(|error| {
                #[cfg(feature = "development-test-host")]
                self.observe_host_admission_refusal(
                    session,
                    crate::development_trap_observer::DevelopmentHostAdmissionEdge::Bind,
                    capability,
                    operation,
                    error.code,
                );
                error
            })?;
        let call = session.dispatch(handle, operation, resource, input, cost, |call| call);
        // Closing the lookup slot never refunds an accepted call's row/buffer.
        let closed = session.close_handle(handle);
        let call = call?;
        closed?;
        Ok(Some(call))
    }
    #[cfg(feature = "development-test-host")]
    fn observe_host_admission_refusal(
        &self,
        session: &CapabilitySession,
        edge: crate::development_trap_observer::DevelopmentHostAdmissionEdge,
        capability: &str,
        operation: &str,
        code: latent_core::PlatformErrorCode,
    ) {
        if let Some(scope) = &self.development_host_admission_scope {
            scope.host_admission_refusal(
                session,
                edge,
                crate::development_trap_observer::DevelopmentHostOperation::from_import(
                    capability, operation,
                ),
                code,
            );
        }
    }
    pub(super) fn local_tenant(&self) -> Result<latent_core::TenantId, PlatformError> {
        self.session
            .as_ref()
            .map(|session| session.tenant().clone())
            .ok_or_else(super::service::denied)
    }
    pub(super) fn captures_audit(&self) -> bool {
        self.session
            .as_ref()
            .is_some_and(CapabilitySession::captures_audit)
    }
    pub(super) fn local_call(
        &self,
        requested: &latent_routing::InvocationTarget,
        input: &[u8],
        typed_bytes: usize,
        output_bytes: usize,
        digest: Option<latent_capabilities::broker::CapabilityRequestDigest>,
    ) -> Result<latent_capabilities::broker::CapabilityDispatch, PlatformError> {
        let session = self.session.as_ref().ok_or_else(super::service::denied)?;
        let target = session.local_invocation_target(requested)?;
        let resource = ResourceTarget::Service {
            service: &target.target.service.0,
            publication: target
                .publication
                .as_ref()
                .expect("compiled scoped target")
                .as_str(),
        };
        let mut cost = CapabilityCallCost::new(output_bytes).with_typed_input_bytes(typed_bytes);
        if let Some(digest) = digest {
            cost = cost.with_typed_request_digest(digest);
        }
        session.prepare_owned_dispatch(
            latent_capabilities::broker::SERVICE_INVOCATION_CAPABILITY,
            "call",
            resource,
            input,
            cost,
        )
    }
    pub(super) fn http_start(
        &self,
        invoker: &dyn latent_capabilities::broker::http::OutboundHttpInvoker,
        source: &mut dyn latent_capabilities::broker::http::HttpRequestSource,
    ) -> Result<
        latent_capabilities::broker::http::HttpInvocation,
        latent_capabilities::broker::http::HttpError,
    > {
        let session = self
            .session
            .as_ref()
            .ok_or(latent_capabilities::broker::http::HttpError::PermissionDenied)?;
        invoker.start_from(session, source)
    }
    pub(super) fn prepare_secret_lowering(&mut self) -> wasmtime::Result<()> {
        self.secret_lowering.prepare_one()
    }
    pub(super) fn prepare_pool_lowering(&mut self) -> wasmtime::Result<()> {
        self.pooled_lowering.prepare_one()
    }
    pub(super) fn prepare_lowering(&mut self) -> wasmtime::Result<()> {
        self.lowering.prepare_one()
    }
    pub(super) fn retain_secret_lowering(
        &mut self,
        owner: latent_capabilities::broker::secrets::SecretLowering,
    ) {
        self.secret_lowering.push_prepared(owner);
    }
    pub(super) fn retain_pool_lowering(
        &mut self,
        call: latent_capabilities::broker::pools::PoolCall,
    ) {
        self.pooled_lowering.push_prepared(call);
    }
    pub(super) fn retain_lowering(&mut self, call: ProviderCall) {
        self.lowering.push_prepared(call);
    }
    pub(super) fn log(
        &self,
        level: &str,
        encoded_bytes: usize,
        digest: Option<latent_capabilities::broker::CapabilityRequestDigest>,
    ) -> Result<Option<ProviderCall>, PlatformError> {
        let mut cost = CapabilityCallCost::new(0).with_typed_input_bytes(encoded_bytes);
        if let Some(digest) = digest {
            cost = cost.with_typed_request_digest(digest);
        }
        self.begin_typed(
            "latent:log/log@0.1.0",
            "write",
            ResourceTarget::Log { level },
            &[],
            cost,
        )
    }
    pub(super) fn context(&mut self, operation: &str, output_bytes: usize) -> wasmtime::Result<()> {
        // Web context is part of the sealed core ABI even when this activation
        // also has a provider session. The owned host context and request
        // preflight already charge and bound its strings and canonical lowering.
        if let Some(session) = &self.session {
            if session
                .uses_core_web_context(output_bytes)
                .map_err(host_error)?
            {
                return Ok(());
            }
        }
        if let Some(call) = self
            .begin(
                "latent:context/context@0.1.0",
                operation,
                ResourceTarget::Context,
                &[],
                output_bytes,
            )
            .map_err(host_error)?
        {
            // Original authority/result admission preceded this directory
            // reservation; no corresponding guest DTO has been built yet.
            self.prepare_lowering()?;
            // The present typed binding has no post-lowering callback. Keep the
            // affine owner until Store destruction instead of asserting that a
            // returned Rust DTO has already been lowered. Broker call/result and
            // metadata caps bound this vector before each allocation. This also
            // covers reentrant canonical realloc and future async guest calls.
            self.lowering.push_prepared(call);
        }
        Ok(())
    }
    pub(super) fn scalar(
        &self,
        capability: &str,
        operation: &str,
        resource: ResourceTarget<'_>,
        output_bytes: usize,
    ) -> wasmtime::Result<Option<ProviderCall>> {
        if capability == "latent:context/context@0.1.0"
            && matches!(resource, ResourceTarget::Context)
        {
            if let Some(session) = &self.session {
                if session
                    .uses_core_web_context(output_bytes)
                    .map_err(host_error)?
                {
                    return Ok(None);
                }
            }
        }
        let mut cost = CapabilityCallCost::new(output_bytes);
        if matches!(
            capability,
            "latent:clock/monotonic@0.1.0" | "latent:clock/wall@0.1.0"
        ) {
            // Match the installed clock profile's mandatory charge. A clock
            // grant never implies unmetered runtime initialization or GC work.
            cost = cost
                .with_charge(latent_core::BudgetDimension::CpuFuel, 100)
                .map_err(host_error)?;
        }
        self.begin_typed(capability, operation, resource, &[], cost)
            .map_err(host_error)
    }
}
