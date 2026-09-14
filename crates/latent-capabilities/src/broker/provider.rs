use super::{
    busy, checked_text, denied, invalid, ActivationCapabilityBroker, Charge, Inner, Kind,
    PlatformError,
};
use latent_core::{ArtifactBlobDigest, BudgetDimension};
use latent_policy::capability::{GrantRestriction, MAX_DOCUMENT_BYTES};
use std::sync::{Arc, RwLock};

/// Trusted installation facts, supplied by the actual node provider owner.
/// They are never obtained from a guest descriptor or an explain response.
#[derive(Clone, Copy)]
pub struct ProviderConfiguration<'a> {
    pub capability: &'a str,
    pub profile: &'a str,
    pub configuration_digest: &'a str,
    pub configuration_epoch: u64,
    pub restriction_json: &'a [u8],
    pub minimum_call_charges: &'a [ProviderBudgetRequirement<'a>],
}
/// The installed provider's minimum cumulative charge for one named operation.
/// These trusted facts are part of its configuration identity, not guest input.
#[derive(Debug, Clone, Copy)]
pub struct ProviderBudgetRequirement<'a> {
    pub operation: &'a str,
    pub dimension: BudgetDimension,
    pub minimum: u64,
}
pub(super) struct RequiredCharge {
    pub operation: String,
    pub dimension: BudgetDimension,
    pub minimum: u64,
}
pub(super) struct Provider {
    pub owner: Arc<Inner>,
    pub capability: String,
    pub profile: String,
    pub digest: String,
    pub epoch: u64,
    pub restriction: GrantRestriction,
    pub minimum_call_charges: Vec<RequiredCharge>,
    pub live: RwLock<bool>,
    _metadata: Charge,
    _slot: Charge,
}
/// Affine configured installation lifetime. Dropping it revokes future starts;
/// plans and existing calls can keep the data, but cannot keep it installed.
pub struct ProviderRegistration {
    entry: Arc<Provider>,
}
#[derive(Clone)]
pub struct ProviderReference {
    pub(super) entry: Arc<Provider>,
}
impl ProviderReference {
    #[must_use]
    pub fn capability(&self) -> &str {
        &self.entry.capability
    }
    #[must_use]
    pub fn profile(&self) -> &str {
        &self.entry.profile
    }
    #[must_use]
    pub fn configuration_digest(&self) -> &str {
        &self.entry.digest
    }
    #[must_use]
    pub fn configuration_epoch(&self) -> u64 {
        self.entry.epoch
    }
}
impl ProviderRegistration {
    #[must_use]
    pub fn reference(&self) -> ProviderReference {
        ProviderReference {
            entry: Arc::clone(&self.entry),
        }
    }
    pub fn retire(&self) {
        *self
            .entry
            .live
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = false;
    }
}
impl Drop for ProviderRegistration {
    fn drop(&mut self) {
        self.retire();
    }
}
impl ActivationCapabilityBroker {
    pub fn register_provider(
        &self,
        input: ProviderConfiguration<'_>,
    ) -> Result<ProviderRegistration, PlatformError> {
        let live = self.inner.live.try_read().map_err(|_| busy())?;
        if !*live {
            return Err(denied());
        }
        if input.minimum_call_charges.len() > 128
            || input.configuration_epoch == 0
            || input.configuration_digest.len() != 71
            || input
                .configuration_digest
                .parse::<ArtifactBlobDigest>()
                .is_err()
            || input.restriction_json.len() > MAX_DOCUMENT_BYTES
        {
            return Err(invalid());
        }
        let slot = self.inner.counters.acquire(Kind::Provider, 1)?;
        let metadata = self.inner.counters.acquire(
            Kind::Metadata,
            4096 + input.restriction_json.len().saturating_mul(16)
                + input.minimum_call_charges.len() * 512,
        )?;
        let restriction = GrantRestriction::parse(input.restriction_json, input.capability)?;
        let mut minimum_call_charges: Vec<RequiredCharge> =
            Vec::with_capacity(input.minimum_call_charges.len());
        for charge in input.minimum_call_charges {
            if !super::token(charge.operation)
                || !charge.dimension.is_cumulative()
                || charge.minimum == 0
                || minimum_call_charges.iter().any(|old| {
                    old.operation == charge.operation && old.dimension == charge.dimension
                })
            {
                return Err(invalid());
            }
            GrantRestriction {
                operations: vec![charge.operation.to_owned()],
                resources: None,
                ceiling: None,
            }
            .validate(input.capability)?;
            minimum_call_charges.push(RequiredCharge {
                operation: charge.operation.to_owned(),
                dimension: charge.dimension,
                minimum: charge.minimum,
            });
        }

        Ok(ProviderRegistration {
            entry: Arc::new(Provider {
                owner: Arc::clone(&self.inner),
                capability: checked_text(input.capability)?,
                profile: checked_text(input.profile)?,
                digest: input.configuration_digest.to_owned(),
                epoch: input.configuration_epoch,
                restriction,
                minimum_call_charges,
                live: RwLock::new(true),
                _metadata: metadata,
                _slot: slot,
            }),
        })
    }
}
