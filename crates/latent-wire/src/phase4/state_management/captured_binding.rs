use super::{invalid, Arc, PlatformError, StateManagementBinding, StateManagementServices};
use latent_capabilities::namespace::RecoverySelection;
use latent_core::native_capacity::{NativeAdmissionClass, NativeBufferClass, NativeBufferPermit};
use latent_policy::capability::RecoveryScopeKind;

pub(super) struct CapturedBinding {
    pub binding: Arc<StateManagementBinding>,
    pub recovery: Option<RecoveryScopeKind>,
}

impl std::ops::Deref for CapturedBinding {
    type Target = Arc<StateManagementBinding>;

    fn deref(&self) -> &Self::Target {
        &self.binding
    }
}

impl std::ops::DerefMut for CapturedBinding {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.binding
    }
}

pub(super) fn bytes(capacity: usize) -> Result<u64, PlatformError> {
    if capacity > 128 {
        return Err(super::capacity());
    }
    std::mem::size_of::<CapturedBinding>()
        .checked_mul(capacity)
        .and_then(|bytes| u64::try_from(bytes).ok())
        .ok_or_else(super::capacity)
}

pub(super) fn prepaid(
    services: &StateManagementServices,
    selection: &RecoverySelection,
    memory: &[Arc<NativeBufferPermit>],
    bindings: &Vec<StateManagementBinding>,
    retained_asset_bytes: u64,
) -> Result<RecoveryScopeKind, PlatformError> {
    if !matches!(selection, RecoverySelection::OriginalCaller) {
        return Err(invalid());
    }
    let native = services.admission.native_capacity();
    if memory.is_empty()
        || memory.len() > 16
        || memory.iter().enumerate().any(|(index, permit)| {
            !permit.is_from_owner(&native)
                || permit.class() != NativeAdmissionClass::Recovery
                || permit.buffer_class() != NativeBufferClass::Work
                || permit.bytes() == 0
                || memory[..index]
                    .iter()
                    .any(|previous| Arc::ptr_eq(previous, permit))
        })
    {
        return Err(invalid());
    }
    let retained = memory.iter().try_fold(0_u64, |total, permit| {
        total
            .checked_add(permit.bytes())
            .ok_or_else(super::capacity)
    })?;
    let needed = retained_asset_bytes
        .checked_add(peak_bytes(bindings)?)
        .ok_or_else(super::capacity)?;
    if retained < needed {
        return Err(super::capacity());
    }
    Ok(RecoveryScopeKind::OriginalCaller)
}

/// Both vectors coexist while each binding moves into its existing Arc owner.
/// String/vector storage moves once; no metadata clone is credited as free.
pub(super) fn peak_bytes(bindings: &Vec<StateManagementBinding>) -> Result<u64, PlatformError> {
    if bindings.len() > 128 || bindings.capacity() > 128 {
        return Err(super::capacity());
    }
    let mut used = bindings
        .capacity()
        .checked_mul(std::mem::size_of::<StateManagementBinding>())
        .and_then(|input| {
            bytes(bindings.len())
                .ok()
                .and_then(|output| usize::try_from(output).ok()?.checked_add(input))
        })
        .ok_or_else(super::capacity)?;
    for binding in bindings {
        let policy = &binding.state;
        if policy.deployment.resources.is_some()
            || policy.provider_configuration.resources.is_some()
        {
            return Err(super::capacity());
        }
        let tenant = binding.publication.scope.tenant().ok_or_else(invalid)?;
        let fixed =
            std::mem::size_of::<StateManagementBinding>() + 2 * std::mem::size_of::<usize>();
        used = used.checked_add(fixed).ok_or_else(super::capacity)?;
        for capacity in [
            binding.publication.id.as_str().len(),
            tenant.0.capacity(),
            binding.component.0.capacity(),
            binding.service.0.capacity(),
            binding.namespace.0.capacity(),
            binding.state_schema.capacity(),
            binding.result_policy.capacity(),
            policy.binding.capacity(),
            policy.profile.capacity(),
            policy.configuration_digest.capacity(),
        ] {
            used = used.checked_add(capacity).ok_or_else(super::capacity)?;
        }
        for values in [
            &policy.policies,
            &policy.operations,
            &policy.deployment.operations,
            &policy.provider_configuration.operations,
        ] {
            used = used
                .checked_add(
                    values
                        .capacity()
                        .checked_mul(std::mem::size_of::<String>())
                        .ok_or_else(super::capacity)?,
                )
                .ok_or_else(super::capacity)?;
            for value in values {
                used = used
                    .checked_add(value.capacity())
                    .ok_or_else(super::capacity)?;
            }
        }
    }
    u64::try_from(used).map_err(|_| super::capacity())
}
