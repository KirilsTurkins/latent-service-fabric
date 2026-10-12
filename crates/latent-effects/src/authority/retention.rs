//! Resident rule maps use the original startup admission, not refreshed jobs.
use super::{AuthorityError, EffectAuthorityOwner, EffectRule};
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeCapacityOwner,
    NativeReservation,
};
use std::sync::Arc;

// Each slot covers all eleven owned rule strings, the five duplicated key
// strings, two closed-namespace strings, rule/token/Arc shells, rejection entry
// tenant/publication bytes and conservative BTree node capacity. Every string
// is bounded by its actual capacity before retaining or cloning it. The fixed
// allowance covers roots/owner/observer shells and four lookup registry slots.
const FIXED_METADATA_BYTES: u64 = 16 * 1024;
const RULE_METADATA_BYTES: u64 = 16 * 1024;

pub(super) struct RetainedAuthority {
    pub(super) original: Arc<NativeReservation>,
    _memory: NativeBufferPermit,
}

impl EffectAuthorityOwner {
    /// Physical resident footprint of this actual finite owner. No global
    /// ceiling changes: callers with insufficient original Work are refused.
    pub fn retained_memory_bytes(maximum_rules: usize) -> Result<u64, AuthorityError> {
        if !(1..=4096).contains(&maximum_rules) {
            return Err(AuthorityError::Invalid);
        }
        u64::try_from(maximum_rules)
            .ok()
            .and_then(|rules| rules.checked_mul(RULE_METADATA_BYTES))
            .and_then(|bytes| bytes.checked_add(FIXED_METADATA_BYTES))
            .ok_or(AuthorityError::Capacity)
    }

    /// Prepay before allocating the real rule/rejection owners. Initializer
    /// expiry never refunds resident metadata or existing contexts/captures.
    /// Existing stateless callers can continue using `new` unchanged.
    pub fn with_retained_capacity(
        maximum_rules: usize,
        maximum_physical: usize,
        clock_floor: u64,
        native: &NativeCapacityOwner,
        original: Arc<NativeReservation>,
    ) -> Result<Self, AuthorityError> {
        let bytes = Self::retained_memory_bytes(maximum_rules)?;
        if !(1..=128).contains(&maximum_physical)
            || !original.is_from_owner(native)
            || original.class() != NativeAdmissionClass::Recovery
        {
            return Err(AuthorityError::Invalid);
        }
        let memory = original
            .reserve_buffer(NativeBufferClass::Work, bytes)
            .map_err(|_| AuthorityError::Capacity)?;
        let owner = Self::construct(
            maximum_rules,
            maximum_physical,
            clock_floor,
            Some(RetainedAuthority {
                original: Arc::clone(&original),
                _memory: memory,
            }),
        )?;
        original
            .with_live(|| ())
            .map_err(|_| AuthorityError::Unavailable)?;
        Ok(owner)
    }

    #[must_use]
    pub fn uses_native_capacity(&self, native: &NativeCapacityOwner) -> bool {
        self.0
            .retained
            .as_ref()
            .is_some_and(|retained| retained.original.is_from_owner(native))
    }
}

pub(super) fn within_prepaid_capacities(rule: &EffectRule) -> bool {
    [
        &rule.scope.tenant,
        &rule.scope.namespace,
        &rule.scope.publication,
        &rule.scope.binding,
        &rule.scope.operation,
        &rule.profile.provider,
        &rule.profile.destination,
        &rule.profile.adapter,
        &rule.profile.payload_format,
        &rule.profile.idempotency_profile,
        &rule.protected_credential_reference,
    ]
    .into_iter()
    .all(|value| value.capacity() <= 256)
}
