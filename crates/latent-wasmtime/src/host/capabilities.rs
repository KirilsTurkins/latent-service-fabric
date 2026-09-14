//! Store-owned capability authority and canonical-ABI lowering reservations.
use latent_capabilities::broker::{CapabilityCallCost, CapabilitySession, ProviderCall};
use latent_core::PlatformError;
use latent_policy::capability::ResourceTarget;

#[derive(Default)]
pub(crate) struct HostCapabilities {
    // Destroy typed-result reservations before closing/destroying the session.
    // They remain charged through canonical lowering and component post-return.
    lowering: Vec<ProviderCall>,
    session: Option<CapabilitySession>,
}
impl HostCapabilities {
    pub(crate) fn new(session: Option<CapabilitySession>) -> Self {
        Self {
            lowering: Vec::new(),
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
    fn begin_typed(
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
        let handle = session.bind(capability, operation, resource)?;
        let call = session.dispatch(handle, operation, resource, input, cost, |call| call);
        // Closing the lookup slot never refunds an accepted call's row/buffer.
        let closed = session.close_handle(handle);
        let call = call?;
        closed?;
        Ok(Some(call))
    }
    pub(super) fn log(
        &self,
        level: &str,
        encoded_bytes: usize,
    ) -> Result<Option<ProviderCall>, PlatformError> {
        self.begin_typed(
            "latent:log/log@0.1.0",
            "write",
            ResourceTarget::Log { level },
            &[],
            CapabilityCallCost::new(0).with_typed_input_bytes(encoded_bytes),
        )
    }
    pub(super) fn context(&mut self, operation: &str, output_bytes: usize) -> wasmtime::Result<()> {
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
            // The present typed binding has no post-lowering callback. Keep the
            // affine owner until Store destruction instead of asserting that a
            // returned Rust DTO has already been lowered. Broker call/result and
            // metadata caps bound this vector before each allocation. This also
            // covers reentrant canonical realloc and future async guest calls.
            self.lowering.push(call);
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
        self.begin(capability, operation, resource, &[], output_bytes)
            .map_err(host_error)
    }
}
pub(super) fn host_error(error: PlatformError) -> wasmtime::Error {
    // No policy document, token, provider location or untrusted detail in traps.
    let code = error.code;
    drop(error);
    wasmtime::Error::msg(format!("capability admission: {code:?}"))
}
