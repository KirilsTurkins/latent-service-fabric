use std::sync::{atomic::Ordering, Arc};

use latent_capabilities::broker::ActivationCapabilityBroker;
use latent_core::{PlatformError, PlatformErrorCode};

use super::{
    capacity, compile, denied, model, BindingDefinition, BindingLimits, CompilerOwner,
    ConfiguredBindingProvider,
};
use crate::deployments::{compiler, observation::Work, DirectoryDeploymentRepository};

impl DirectoryDeploymentRepository {
    pub async fn activate_configured_bindings(
        &self,
        definitions: Vec<BindingDefinition>,
        broker: Arc<ActivationCapabilityBroker>,
        providers: Vec<ConfiguredBindingProvider>,
        limits: BindingLimits,
    ) -> Result<(), PlatformError> {
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
            || providers.iter().any(|provider| {
                !model::token(&provider.tenant.0)
                    || !model::token(&provider.service.0)
                    || provider.local_deployment.as_ref().is_some_and(|id| {
                        !model::token(&id.0)
                            || provider.reference.capability()
                                != latent_capabilities::broker::SERVICE_INVOCATION_CAPABILITY
                            || provider.reference.profile()
                                != latent_capabilities::broker::LOCAL_SERVICE_INVOCATION_PROFILE
                    })
            })
        {
            return Err(denied());
        }
        let previous = self.read_publication();
        if previous.routes.bindings.owner.is_some() || !previous.confirmed {
            return Err(denied());
        }
        if previous.routes.bindings.data.is_empty() {
            let prepared = self
                .prepare_binding_update(
                    previous.routes.generation,
                    previous.transaction,
                    definitions,
                    broker,
                    providers,
                    limits,
                )
                .await?;
            self.commit_binding_update(prepared)?;
            return Ok(());
        }
        let data = definitions
            .into_iter()
            .map(|definition| model::StoredBinding::encode(definition, limits))
            .collect::<Result<Vec<_>, _>>()?;
        if data.as_slice() != previous.routes.bindings.data.as_ref() {
            return Err(super::error(
                PlatformErrorCode::StateConflict,
                "configured-bindings-differ-from-durable-definitions",
            ));
        }
        self.rollout_work
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| capacity())?;
        let _permit = super::update::WorkPermit(Arc::clone(&self.rollout_work));
        let owner = Arc::new(CompilerOwner {
            broker,
            providers: providers.into_boxed_slice(),
            current: Arc::downgrade(&self.current),
            limits,
        });
        let mut next = compiler::compile_catalog_for_bindings(
            previous.routes.deployments.clone(),
            previous.routes.versions.clone(),
            previous.routes.generation,
            previous.routes.generated_at_unix_millis,
            self.artifacts.as_ref(),
            self.config,
            &previous.routes,
            &mut Work::default(),
            self.runtime_profile.as_deref(),
            self.lifecycle.as_ref(),
            None,
        )
        .await?;
        next.bindings = compile::compile(
            &next,
            data.into(),
            Some(owner),
            self.artifacts.as_ref(),
            false,
            None,
        )
        .await?;
        let next = Arc::new(next);
        next.with_current_admission(&mut |_| {
            let mut current = self.current.try_write().map_err(|_| capacity())?;
            if !current.confirmed
                || current.transaction != previous.transaction
                || !Arc::ptr_eq(&current.routes, &previous.routes)
                || current.routes.bindings.owner.is_some()
            {
                return Err(super::error(
                    PlatformErrorCode::StateConflict,
                    "stale-binding-activation",
                ));
            }
            current.routes = Arc::clone(&next);
            Ok(())
        })
    }
}
