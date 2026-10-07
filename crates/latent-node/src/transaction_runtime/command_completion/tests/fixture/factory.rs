use super::*;
use crate::transaction_runtime::{PolicyCallBinding, StateAuthorization};
use latent_capabilities::namespace::{
    CallerScope, NamespaceAdmission, NamespaceAuthority, RecoverySelection, STATE_CONTRACT,
};
use latent_commit::atomic::{AdmissionInput, ReplayPolicy, ResultPolicy, SourceIdentity};
use latent_core::{
    transaction_contract::{CommandFingerprint, CommandKey, Value},
    ActivationBudget, BoxFuture, PlatformError, TenantId,
};
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, GrantRestriction, ResourceTarget,
};
use latent_state::{
    namespace::catalog::NamespaceRead,
    session::{StateMode, StateScope},
};
use serde_json::json;

const OPERATIONS: [&str; 16] = [
    "acquire-command",
    "acquire-query",
    "info",
    "query-info",
    "get",
    "get-query",
    "scan",
    "scan-query",
    "put",
    "delete",
    "inspect-effect",
    "describe-page",
    "page-next",
    "commit",
    "read-result",
    "cancel-command",
];
pub(super) fn principal() -> latent_core::InvocationPrincipal {
    latent_core::InvocationPrincipal {
        subject: "alice".into(),
        kind: latent_core::PrincipalKind::User,
        tenant: Some(TenantId("a".into())),
        service: None,
        claims: Metadata::new(),
    }
}
fn binding() -> PolicyCallBinding {
    PolicyCallBinding {
        policies: vec!["state".into()],
        binding: "binding".into(),
        profile: "namespace-v1".into(),
        configuration_digest: format!("sha256:{}", "2".repeat(64)),
        configuration_epoch: 1,
        operations: OPERATIONS.iter().map(|op| (*op).into()).collect(),
        deployment: GrantRestriction::parse(br#"{"operations":[]}"#, STATE_CONTRACT).unwrap(),
        provider_configuration: GrantRestriction::parse(br#"{"operations":[]}"#, STATE_CONTRACT)
            .unwrap(),
    }
}
pub(super) fn install_policy(policy: &PolicyStore, publication: &ReleaseUseEligibility) {
    let caller = CallerScope::derive(&principal(), &RecoverySelection::OriginalCaller).unwrap();
    let scopes: Vec<_> = ["hot", "cold"].iter().map(|entity| json!({
        "namespace":"orders", "incarnation":1, "entity":entity,
        "recoveryKind":caller.kind, "recoveryScope":caller.scope, "resultPolicy":"visibility-v1",
    })).collect();
    let document = json!({"formatVersion":1,"tenant":"a","rules":[{
        "id":"alice","effect":"allow","principals":[{"kind":"user","subject":"alice"}],
        "services":["a/echo"],"publications":[publication.publication().as_str()],
        "capability":STATE_CONTRACT,"operations":OPERATIONS,
        "resources":{"kind":"state","scopes":scopes},
        "ceiling":{"operations":256,"inputBytes":2_097_152,"outputBytes":2_097_152,"wallTimeMillis":10_000}
    }]});
    let provider = json!({"formatVersion":1,"tenant":"a","capability":STATE_CONTRACT,
        "providerProfile":"namespace-v1", "configurationDigest":binding().configuration_digest,
        "configurationEpoch":1, "restriction":{"operations":[]}});
    for (kind, id, operation_id, document) in [
        (
            RecordKind::Policy,
            "state",
            "installed-entity-policy",
            document,
        ),
        (
            RecordKind::ProviderBinding,
            "binding",
            "installed-entity-binding",
            provider,
        ),
    ] {
        policy
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    kind,
                    id,
                    operation_id,
                    expected_revision: 0,
                    document: Some(&serde_json::to_vec(&document).unwrap()),
                },
                Instant::now() + WATCHDOG,
                |_| Ok(()),
            )
            .unwrap();
    }
}

pub(super) struct Factory {
    pub owners: Arc<Owners>,
    pub time: Arc<time::Time>,
    pub client_key: String,
    pub entity: String,
}
impl CommandAdmissionFactory for Factory {
    fn preflight<'a>(
        &'a self,
        envelope: &'a latent_activation::ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            let (first, second) = self.namespaces().await;
            self.seal(first, envelope, budget, "acquire-command")?;
            self.seal(second, envelope, budget, "read-result")?;
            Ok(())
        })
    }

    fn select<'a>(
        &'a self,
        envelope: &'a latent_activation::ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<CommandAdmissionSelection, PlatformError>> {
        Box::pin(async move {
            let (first, second) = self.namespaces().await;
            let execution = self.seal(first, envelope, budget, "acquire-command")?;
            let read = self.seal(second, envelope, budget, "read-result")?;
            let epoch = self.time.capture(budget);
            let caller =
                CallerScope::derive(&envelope.principal, &RecoverySelection::OriginalCaller)?;
            let revision = envelope.resolved_revision.as_ref().unwrap();
            CommandAdmissionSelection::new(
                AdmissionInput {
                    key: CommandKey {
                        tenant: "a".into(),
                        namespace: "orders".into(),
                        incarnation: "1".into(),
                        recovery_scope: caller.scope,
                        operation: "update".into(),
                        entity: Some(self.entity.clone()),
                        client_key: self.client_key.clone(),
                    },
                    fingerprint: CommandFingerprint {
                        input_format: "lsf-wit-values-v1".into(),
                        input: Value {
                            bytes: envelope.input.clone(),
                            media_type: envelope.input_media_type.clone(),
                            metadata: vec![],
                        },
                        expected_versions: vec![],
                    },
                    source: SourceIdentity {
                        publication: self.owners.publication.publication().as_str().into(),
                        revision: revision.revision.0.clone(),
                        release_digest: revision.release.0.clone(),
                        component_digest: self.owners.publication.release().0.clone(),
                        contract_digest: format!("sha256:{}", "3".repeat(64)),
                        route_generation: revision.route_generation.0,
                        state_schema: schema(),
                        input_format: "lsf-wit-values-v1".into(),
                        result_format: "lsf-wit-values-v1".into(),
                    },
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
                },
                vec![],
                StateScope {
                    tenant: TenantId("a".into()),
                    namespace: latent_core::StateNamespaceId("orders".into()),
                    incarnation: 1,
                    state_schema: schema(),
                    entity: Some(self.entity.clone()),
                    mode: StateMode::Command,
                },
                execution,
                read,
                Arc::new(CanonicalCommandResult),
            )
        })
    }
}
impl Factory {
    async fn namespaces(&self) -> (NamespaceRead, NamespaceRead) {
        self.owners
            .store
            .with_store(StoreIoKind::Read, 8192, |store| {
                let view = store.snapshot()?;
                let read = || {
                    NamespaceCatalog::read_in(
                        &view,
                        &TenantId("a".into()),
                        &latent_core::StateNamespaceId("orders".into()),
                    )
                    .unwrap()
                    .unwrap()
                };
                Ok((read(), read()))
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap()
    }

    fn seal(
        &self,
        namespace: NamespaceRead,
        envelope: &latent_activation::ActivationEnvelope,
        budget: &ActivationBudget,
        operation: &str,
    ) -> Result<Arc<StateAuthorization>, PlatformError> {
        let binding = binding();
        let caller = CallerScope::derive(&envelope.principal, &RecoverySelection::OriginalCaller)?;
        let deadline = budget.deadline().monotonic().unwrap();
        let snapshot = self.owners.policy.snapshot(
            &TenantId("a".into()),
            &binding.policies,
            &binding.binding,
            deadline,
        )?;
        let wall = u64::try_from(
            deadline
                .saturating_duration_since(Instant::now())
                .as_millis(),
        )
        .unwrap()
        .min(30_000);
        let decision = snapshot.authorize(
            EvaluationInput {
                principal: &envelope.principal,
                service: "a/echo",
                publication: self.owners.publication.publication().as_str(),
                capability: STATE_CONTRACT,
                operation,
                resource: ResourceTarget::State {
                    namespace: "orders",
                    incarnation: 1,
                    entity: Some(&self.entity),
                    recovery_kind: caller.kind,
                    recovery_scope: &caller.scope,
                    result_policy: "visibility-v1",
                },
            },
            &CallRestrictions {
                imported_operations: &binding.operations,
                deployment: &binding.deployment,
                provider_configuration: &binding.provider_configuration,
                provider_profile: &binding.profile,
                configuration_digest: &binding.configuration_digest,
                configuration_epoch: binding.configuration_epoch,
                remaining: CapabilityCeiling {
                    operations: 256,
                    input_bytes: 2_097_152,
                    output_bytes: 2_097_152,
                    wall_time_millis: wall,
                },
                input_bytes: 0,
                output_bytes: 0,
            },
            &self.owners.publication,
        )?;
        let lifecycle = self.owners.namespaces.lifecycle().pin(&namespace).unwrap();
        let authority = NamespaceAuthority::seal(
            &self.owners.policy,
            &decision,
            &namespace,
            NamespaceAdmission {
                activation: envelope.activation_id.clone(),
                deadline,
                recovery: &RecoverySelection::OriginalCaller,
                state_schema: &schema(),
            },
            lifecycle,
        )?;
        Ok(Arc::new(StateAuthorization::new(
            Arc::clone(&self.owners.policy),
            Arc::new(authority),
            namespace,
            envelope.principal.clone(),
            "a/echo".into(),
            self.owners.publication.clone(),
            binding,
            None,
            budget.clone(),
        )?))
    }
}
