use super::model::{BindingDefinition, BindingLimits, ConfiguredBindingProvider, StoredBinding};
use super::{capacity, compile, denied, invalid, model, CompilerOwner};
use crate::deployments::{
    compiler, observation::Work, persistence, DirectoryDeploymentRepository, PublicationView,
    PublishedCatalog,
};
use latent_capabilities::broker::ActivationCapabilityBroker;
use latent_capabilities::broker::{pools::ProviderMetadata, ProviderReference};
use latent_core::{PlatformError, PlatformErrorCode, RouteGeneration};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, RwLock, Weak,
};

/// Keep the temporary configuration copy charged until the actual catalog
/// commit finishes. The provider owner supplies a reservation from its pool.
pub struct PreparedProviderReferenceUpdate {
    prepared: PreparedBindingUpdate,
    _metadata: ProviderMetadata,
}

pub(super) struct WorkPermit(pub(super) Arc<AtomicBool>);
impl Drop for WorkPermit {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}
/// Affine, owner-bound prepared transaction. Dropping it discards tentative
/// plans and releases the one shared control-work permit without publication.
pub struct PreparedBindingUpdate {
    owner: Weak<RwLock<PublishedCatalog>>,
    previous: PublicationView,
    next: persistence::EncodedCatalog,
    _work: WorkPermit,
}
impl DirectoryDeploymentRepository {
    /// Trusted node control only. Replace the exact installed reference in a
    /// new immutable compiler owner; no binding DTO supplies installation facts.
    pub async fn prepare_provider_reference_update(
        &self,
        expected: &ProviderReference,
        replacement: ProviderReference,
        reserve_metadata: impl FnOnce(usize) -> Result<ProviderMetadata, PlatformError>,
    ) -> Result<PreparedProviderReferenceUpdate, PlatformError> {
        if expected.capability() != replacement.capability()
            || expected.profile() != replacement.profile()
            || replacement.configuration_epoch() < expected.configuration_epoch()
            || (replacement.configuration_epoch() == expected.configuration_epoch()
                && !expected.same_installation(&replacement))
        {
            return Err(denied());
        }
        let previous = self.read_publication();
        if !previous.confirmed {
            return Err(denied());
        }
        let owner = previous.routes.bindings.owner.as_ref().ok_or_else(denied)?;
        if !owner.broker.provider_owner_matches(expected)
            || !owner.broker.provider_owner_matches(&replacement)
        {
            return Err(denied());
        }
        let matches = owner
            .providers
            .iter()
            .filter(|provider| provider.reference.same_installation(expected))
            .count();
        if matches != 1 {
            return Err(denied());
        }
        // Decode/copy only after reserving conservative scratch for this same
        // finite catalog. Existing metadata and retained-generation limits apply.
        let bytes = previous
            .routes
            .bindings
            .data
            .iter()
            .try_fold(4096usize, |total, data| {
                total
                    .checked_add(data.retained_bytes().checked_mul(8).ok_or_else(capacity)?)
                    .ok_or_else(capacity)
            })?
            .checked_add(owner.retained_bytes().checked_mul(2).ok_or_else(capacity)?)
            .ok_or_else(capacity)?;
        let metadata = reserve_metadata(bytes)?;
        let definitions = previous
            .routes
            .bindings
            .data
            .iter()
            .map(|data| data.decode(owner.limits))
            .collect::<Result<Vec<_>, _>>()?;
        let providers = owner
            .providers
            .iter()
            .map(|provider| ConfiguredBindingProvider {
                tenant: provider.tenant.clone(),
                service: provider.service.clone(),
                reference: if provider.reference.same_installation(expected) {
                    replacement.clone()
                } else {
                    provider.reference.clone()
                },
                local_deployment: provider.local_deployment.clone(),
            })
            .collect();
        let prepared = self
            .prepare_binding_update(
                previous.routes.generation,
                previous.transaction,
                definitions,
                Arc::clone(&owner.broker),
                providers,
                owner.limits,
            )
            .await?;
        Ok(PreparedProviderReferenceUpdate {
            prepared,
            _metadata: metadata,
        })
    }

    pub fn commit_provider_reference_update(
        &self,
        prepared: PreparedProviderReferenceUpdate,
    ) -> Result<RouteGeneration, PlatformError> {
        let PreparedProviderReferenceUpdate {
            prepared,
            _metadata,
        } = prepared;
        let result = self.commit_binding_update(prepared);
        drop(_metadata);
        result
    }

    /// Trusted node/operator control entry point. Authenticated management must
    /// separately authorize tenant changes; installation facts never come from
    /// a guest, binding DTO, or explain response.
    pub async fn prepare_binding_update(
        &self,
        expected_generation: RouteGeneration,
        expected_transaction: u64,
        definitions: Vec<BindingDefinition>,
        broker: Arc<ActivationCapabilityBroker>,
        providers: Vec<ConfiguredBindingProvider>,
        limits: BindingLimits,
    ) -> Result<PreparedBindingUpdate, PlatformError> {
        limits.validate()?;
        if definitions.len() > limits.maximum_definitions
            || providers.len() > limits.maximum_providers
        {
            return Err(capacity());
        }
        if self
            .lifecycle
            .as_ref()
            .is_none_or(|catalog| !broker.catalog_owner_matches(catalog))
        {
            return Err(denied());
        }
        for provider in &providers {
            if !model::token(&provider.tenant.0)
                || !model::token(&provider.service.0)
                || provider
                    .local_deployment
                    .as_ref()
                    .is_some_and(|id| !model::token(&id.0))
            {
                return Err(invalid());
            }
        }
        self.rollout_work
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| capacity())?;
        let permit = WorkPermit(Arc::clone(&self.rollout_work));
        let previous = self.read_publication();
        if previous.routes.generation != expected_generation
            || previous.transaction != expected_transaction
            || !previous.confirmed
        {
            return Err(super::error(
                PlatformErrorCode::StateConflict,
                "stale-binding-transaction",
            ));
        }
        let data = definitions
            .into_iter()
            .map(|d| StoredBinding::encode(d, limits))
            .collect::<Result<Vec<_>, _>>()?;
        let owner = Arc::new(CompilerOwner {
            broker,
            providers: providers.into_boxed_slice(),
            current: Arc::downgrade(&self.current),
            limits,
            manifest_profile: self.config.manifest_profile,
        });
        let mut work = Work::default();
        if let Some(authority) = &self.admission {
            authority.renew_control_lease()?;
        }
        let mut next = compiler::compile_catalog_for_bindings(
            previous.routes.deployments.clone(),
            previous.routes.versions.clone(),
            super::super::next_generation(expected_generation)?,
            super::super::now()?,
            self.artifacts.as_ref(),
            self.config,
            &previous.routes,
            &mut work,
            self.runtime_profile.as_deref(),
            self.lifecycle.as_ref(),
            self.admission.as_deref(),
        )
        .await?;
        next.bindings = compile::compile(
            &next,
            data.into(),
            Some(owner),
            self.artifacts.as_ref(),
            true,
            self.admission.as_deref(),
        )
        .await?;
        let next = persistence::encode(next, self.config, &mut work)?;
        Ok(PreparedBindingUpdate {
            owner: Arc::downgrade(&self.current),
            previous,
            next,
            _work: permit,
        })
    }
    pub fn commit_binding_update(
        &self,
        prepared: PreparedBindingUpdate,
    ) -> Result<RouteGeneration, PlatformError> {
        if !prepared.owner.ptr_eq(&Arc::downgrade(&self.current)) {
            return Err(denied());
        }
        if let Some(authority) = &self.admission {
            authority.renew_control_lease()?;
        }
        let generation = prepared.next.catalog().generation;
        self.commit_versioned(
            prepared.previous.routes.generation,
            prepared.previous.transaction,
            prepared.next,
            &mut Work::default(),
        )?;
        Ok(generation)
    }
    /// Read the coherent versions required by a subsequent binding update.
    /// These comparison values grant no authority and are rechecked at commit.
    pub fn binding_version(&self) -> Result<(RouteGeneration, u64), PlatformError> {
        let current = self
            .current
            .try_read()
            .map_err(|_| super::error(PlatformErrorCode::Unavailable, "binding-version-busy"))?;
        if !current.confirmed {
            return Err(super::error(
                PlatformErrorCode::Unavailable,
                "binding-version-unconfirmed",
            ));
        }
        Ok((current.routes.generation, current.transaction))
    }
    /// Counts are diagnostics, not live authority or a clean security verdict.
    #[must_use]
    pub fn binding_inventory(&self) -> (RouteGeneration, usize, usize, usize) {
        let current = self.read_catalog();
        (
            current.generation,
            current.bindings.data.len(),
            current.bindings.plans.len(),
            current.bindings.unavailable,
        )
    }
    pub fn binding_definitions(&self) -> Result<Vec<BindingDefinition>, PlatformError> {
        let current = self.read_catalog();
        current
            .bindings
            .data
            .iter()
            .map(|data| data.decode(BindingLimits::default()))
            .collect()
    }
}
