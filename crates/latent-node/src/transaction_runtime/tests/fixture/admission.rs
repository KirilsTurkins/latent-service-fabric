//! Thin fixture composition through the real command/query admission and affine hooks.
use super::super::super::command_completion::{
    CanonicalCommandResult, CommandAdmissionFactory, CommandAdmissionSelection, CommandCoordinator,
};
use super::*;
use crate::{TransactionActivationAdmission, TransactionAdmission, TransactionExecution};
use latent_activation::ActivationEnvelope;
use latent_capabilities::namespace::{CallerScope, RecoverySelection};
use latent_commit::atomic::{AdmissionInput, ReplayPolicy, ResultPolicy, SourceIdentity};
use latent_core::{
    transaction_contract::{CommandFingerprint, CommandKey},
    ActivationBudget, BoxFuture, PlatformError, StateNamespaceId,
};
use latent_state::{
    namespace::catalog::NamespaceRead,
    session::{StateMode, StateScope},
};

pub(super) fn execute(admitted: TransactionAdmission) -> TransactionExecution {
    let TransactionAdmission::Execute(execution) = admitted else {
        panic!("native execution absent")
    };
    execution
}

pub(super) fn key(client: &str) -> CommandKey {
    CommandKey {
        tenant: "a".into(),
        namespace: "orders".into(),
        incarnation: "1".into(),
        recovery_scope: CallerScope::derive(
            &policy::principal(),
            &RecoverySelection::OriginalCaller,
        )
        .unwrap()
        .scope,
        operation: "update".into(),
        entity: None,
        client_key: client.into(),
    }
}

pub(super) fn scope(query: bool) -> StateScope {
    StateScope {
        tenant: latent_core::TenantId("a".into()),
        namespace: StateNamespaceId("orders".into()),
        incarnation: 1,
        state_schema: schema(),
        entity: None,
        mode: if query {
            StateMode::Query
        } else {
            StateMode::Command
        },
    }
}

pub(super) fn installed(
    fixture: &Fixture,
    query: bool,
    client: &str,
    minimum: Option<Vec<u8>>,
    envelope: &ActivationEnvelope,
    budget: &ActivationBudget,
) -> Arc<dyn TransactionActivationAdmission> {
    let time = TransactionAdmissionTime::new(fixture.command.clone(), fixture.native.clone());
    let admission: Arc<dyn TransactionActivationAdmission> = if query {
        let selection = super::super::super::query::QuerySelection::installed(
            envelope.target.clone(),
            fixture.publication.clone(),
            &fixture.declaration,
            &fixture.metadata.manifest().metadata.name,
            &fixture.deployment.id.0,
            super::super::super::query::QueryScope {
                incarnation: 1,
                entity: None,
                recovery: RecoverySelection::OriginalCaller,
                result_policy: "visibility-v1".into(),
                minimum_view_token: minimum,
            },
        )
        .unwrap();
        Arc::new(
            super::super::super::query::QueryAdmission::new(
                super::super::super::query::QueryOwners {
                    store: Arc::clone(&fixture.store),
                    policy: Arc::clone(&fixture.policy),
                    namespaces: Arc::clone(&fixture.namespaces),
                    time,
                },
                selection,
                policy::call_binding(),
            )
            .unwrap(),
        )
    } else {
        let factory = Factory {
            store: Arc::clone(&fixture.store),
            policy: Arc::clone(&fixture.policy),
            namespaces: Arc::clone(&fixture.namespaces),
            publication: fixture.publication.clone(),
            metadata: Arc::clone(&fixture.metadata),
            declaration: Arc::clone(&fixture.declaration),
            deployment: Arc::clone(&fixture.deployment),
            client: client.into(),
            time: Arc::clone(&time),
        };
        CommandCoordinator::new(
            Arc::clone(&fixture.store),
            fixture.waiters.clone(),
            Some(fixture.effects.clone()),
            time,
        )
        .admission(Arc::new(factory))
    };
    admission
        .bind_control(fixture.commit_control(envelope, budget))
        .unwrap();
    admission
}

struct Factory {
    store: Arc<ProtectedStoreOwner>,
    policy: Arc<PolicyStore>,
    namespaces: Arc<NamespaceCatalog>,
    publication: ReleaseUseEligibility,
    metadata: Arc<latent_artifacts::VerifiedArtifactMetadata>,
    declaration: Arc<latent_manifest::TransactionBinding>,
    deployment: Arc<latent_manifest::DeploymentManifest>,
    client: String,
    time: Arc<TransactionAdmissionTime>,
}
impl Factory {
    fn source(&self, envelope: &ActivationEnvelope) -> Result<SourceIdentity, PlatformError> {
        let denied = super::super::super::authorization::denied;
        self.declaration
            .check_links(
                &self.metadata.manifest().metadata.name,
                &self.deployment.id.0,
                &self.declaration.binding,
            )
            .map_err(|_| denied())?;
        let resolved = envelope.resolved_revision.as_ref().ok_or_else(denied)?;
        let operation = self
            .declaration
            .operations
            .iter()
            .find(|operation| operation.operation == envelope.target.function.0)
            .ok_or_else(denied)?;
        let contract = self
            .metadata
            .contracts()
            .iter()
            .find(|contract| contract.id == envelope.target.contract)
            .ok_or_else(denied)?;
        if resolved.target != envelope.target
            || resolved.release != *self.publication.release()
            || resolved.publication.as_ref() != Some(self.publication.publication())
            || self.metadata.verified_digest() != self.publication.release()
            || envelope.target.service.0 != self.metadata.manifest().metadata.name
            || Some(&envelope.target.tenant) != self.publication.tenant()
            || operation.mode != latent_manifest::TransactionOperationMode::StrictCommand
            || !self
                .metadata
                .manifest()
                .exports
                .iter()
                .any(|export| export.contract == envelope.target.contract)
        {
            return Err(denied());
        }
        Ok(SourceIdentity {
            publication: self.publication.publication().as_str().into(),
            revision: resolved.revision.0.clone(),
            release_digest: self.publication.release().0.clone(),
            component_digest: self.metadata.verified_digest().0.clone(),
            contract_digest: contract.digest.clone(),
            route_generation: resolved.route_generation.0,
            state_schema: self.declaration.state_schema.clone(),
            input_format: operation.input_format.clone(),
            result_format: operation.result_format.clone(),
        })
    }
    async fn namespace(&self) -> Result<NamespaceRead, PlatformError> {
        let retained: Arc<dyn std::any::Any + Send + Sync> = self.time.clone();
        let unavailable = || PlatformError {
            code: latent_core::PlatformErrorCode::Unavailable,
            message: "native-fixture-history-unavailable".into(),
            retryable: false,
            details: Vec::new(),
        };
        let selected = self
            .store
            .with_store_retaining(StoreIoKind::Read, 8192, retained, |store| {
                let view = store.snapshot()?;
                match latent_state::recovery::require_namespace_ready(
                    &view,
                    &latent_core::TenantId("a".into()),
                    &StateNamespaceId("orders".into()),
                    1,
                ) {
                    Ok(()) => (),
                    Err(latent_state::embedded::StoreError::Unavailable) => return Ok(Ok(None)),
                    Err(error) => return Err(error),
                }
                Ok(NamespaceCatalog::read_in(
                    &view,
                    &latent_core::TenantId("a".into()),
                    &StateNamespaceId("orders".into()),
                ))
            })
            .map_err(|_| unavailable())?
            .await
            .map_err(|_| unavailable())?
            .map_err(|_| unavailable())?;
        selected.map_err(|_| unavailable())?.ok_or_else(unavailable)
    }
}
impl CommandAdmissionFactory for Factory {
    fn select<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<CommandAdmissionSelection, PlatformError>> {
        Box::pin(async move {
            let source = self.source(envelope)?;
            self.time.retain_admission(envelope, budget)?;
            let execute = policy::seal(
                &self.policy,
                &self.namespaces,
                &self.publication,
                self.namespace().await?,
                envelope,
                budget,
                "acquire-command",
            )?;
            let read = policy::seal(
                &self.policy,
                &self.namespaces,
                &self.publication,
                self.namespace().await?,
                envelope,
                budget,
                "read-result",
            )?;
            let epoch = self.time.capture()?;
            let input = AdmissionInput {
                key: key(&self.client),
                fingerprint: CommandFingerprint {
                    input_format: source.input_format.clone(),
                    input: latent_core::transaction_contract::Value {
                        bytes: envelope.input.clone(),
                        media_type: envelope.input_media_type.clone(),
                        metadata: Vec::new(),
                    },
                    expected_versions: Vec::new(),
                },
                source,
                result_read_policy: "visibility-v1".into(),
                result_policy: ResultPolicy {
                    replay: ReplayPolicy::Full,
                    maximum_result_bytes: 4096,
                    result_millis: 10_000,
                    identity_millis: 20_000,
                    maximum_attempts: 3,
                },
                inbox: None,
                owner_epoch: epoch,
            };
            CommandAdmissionSelection::new(
                input,
                Vec::new(),
                scope(false),
                execute,
                read,
                Arc::new(CanonicalCommandResult),
            )
        })
    }
}
