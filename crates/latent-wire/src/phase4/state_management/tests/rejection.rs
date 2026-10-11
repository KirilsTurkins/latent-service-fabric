//! Actual PolicyStore and directory lifecycle mutations against held accepted
//! effect/native owners. HTTP/TLS qualification is a separate provider schedule.
use super::*;
use latent_artifacts::{
    ArtifactRepository, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
    LifecycleScope, ReleaseActor, ReleaseActorKind, ReleaseLifecycleAction, ReleaseLifecycleReason,
    ReleaseMutationContext, ReleaseOperationPrecondition,
};
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeCapacityLimits, NativeCapacityOwner, NativeReservationRequest,
    },
    InvocationPrincipal, Metadata, PrincipalKind, TenantId,
};
use latent_effects::authority::{
    AuthorityError, CommitLink, DispatchCeiling, DispatchContext, DispatchGrant, DispatchProfile,
    DurableEffectAuthority, EffectAuthorityOwner, EffectRule, EffectScope, EffectTime,
};
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, GrantRestriction, MutationRequest,
    PolicyStoreLimits, RecordKind, RecoveryScopeKind, ResourceTarget,
};
use serde_json::{json, Value};

const CONTRACT: &str = "latent:intents/staging@0.1.0";
fn time() -> EffectTime {
    EffectTime {
        unix_millis: 100,
        continuity_proven: true,
    }
}
fn document(publication: &PublicationRef) -> Value {
    json!({"formatVersion":1,"tenant":"a","rules":[{
        "id":"stage","effect":"allow","principals":[{"kind":"user","subject":"alice"}],
        "services":["a/echo"],"publications":[publication.id.as_str()],"capability":CONTRACT,
        "operations":["stage"],"resources":{"kind":"state","scopes":[{
            "namespace":"orders","incarnation":1,"entity":null,"recoveryKind":"original-caller",
            "recoveryScope":"caller-a","resultPolicy":"visibility-v1"}]},
        "ceiling":{"operations":4,"inputBytes":1024,"outputBytes":1024,"wallTimeMillis":30000}
    }]})
}
struct OriginalOwners {
    catalog: DirectoryArtifactRepository,
    policy: PolicyStore,
    effects: EffectAuthorityOwner,
    native: NativeCapacityOwner,
    publication: PublicationRef,
    component: ReleaseDigest,
    policy_revision: u64,
    _directory: tempfile::TempDir,
}
impl OriginalOwners {
    async fn new() -> Self {
        let directory = tempfile::tempdir().unwrap();
        let effects = EffectAuthorityOwner::new(8, 4, 100).unwrap();
        let catalog = DirectoryArtifactRepository::open(
            directory.path().join("artifacts"),
            DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap();
        catalog
            .lifecycle_authority()
            .install_rejection_observer(effects.rejection_observer())
            .unwrap();
        let (publication, component) = fixture::publish(&catalog, "first").await;
        let policy = PolicyStore::open(
            &directory.path().join("policy"),
            PolicyStoreLimits::default(),
            catalog.lifecycle_authority(),
        )
        .unwrap();
        policy
            .install_rejection_observer(effects.rejection_observer())
            .unwrap();
        let policy_revision = change_policy(&policy, "create", 0, Some(&document(&publication)));
        let binding = json!({"formatVersion":1,"tenant":"a","capability":CONTRACT,
            "providerProfile":"effect-v1","configurationDigest":format!("sha256:{}", "2".repeat(64)),
            "configurationEpoch":1,"restriction":{"operations":[]}});
        policy
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    id: "binding",
                    kind: RecordKind::ProviderBinding,
                    operation_id: "binding-create",
                    expected_revision: 0,
                    document: Some(&serde_json::to_vec(&binding).unwrap()),
                },
                deadline(),
                |_| Ok(()),
            )
            .unwrap();
        Self {
            catalog,
            policy,
            effects,
            native: NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap(),
            publication,
            component,
            policy_revision,
            _directory: directory,
        }
    }

    fn install_current(&self, publication: &PublicationRef) -> Result<EffectRule, PlatformError> {
        let snapshot = self.policy.snapshot(
            &TenantId("a".into()),
            &["intents".into()],
            "binding",
            deadline(),
        )?;
        let eligibility = self
            .catalog
            .execution_eligibility_selected(&self.component, Some(&publication.id))?
            .ok_or_else(denied)?;
        let principal = InvocationPrincipal {
            subject: "alice".into(),
            kind: PrincipalKind::User,
            tenant: Some(TenantId("a".into())),
            service: None,
            claims: Metadata::new(),
        };
        let restrictions = GrantRestriction::parse(br#"{"operations":[]}"#, CONTRACT)?;
        let operations = vec!["stage".into()];
        let digest = format!("sha256:{}", "2".repeat(64));
        let decision = snapshot.authorize(
            EvaluationInput {
                principal: &principal,
                service: "a/echo",
                publication: publication.id.as_str(),
                capability: CONTRACT,
                operation: "stage",
                resource: ResourceTarget::State {
                    namespace: "orders",
                    incarnation: 1,
                    entity: None,
                    recovery_kind: RecoveryScopeKind::OriginalCaller,
                    recovery_scope: "caller-a",
                    result_policy: "visibility-v1",
                },
            },
            &CallRestrictions {
                imported_operations: &operations,
                deployment: &restrictions,
                provider_configuration: &restrictions,
                provider_profile: "effect-v1",
                configuration_digest: &digest,
                configuration_epoch: 1,
                remaining: CapabilityCeiling {
                    operations: 4,
                    input_bytes: 1024,
                    output_bytes: 1024,
                    wall_time_millis: 30000,
                },
                input_bytes: 100,
                output_bytes: 100,
            },
            &eligibility,
        )?;
        let rule = effect_rule(
            publication,
            snapshot.policy_revisions().next().unwrap().revision,
        );
        self.policy.with_current(&decision, &mut |_, _| {
            self.effects.publish(rule.clone()).map_err(|_| denied())
        })?;
        Ok(rule)
    }

    fn accepted(
        &self,
        rule: &EffectRule,
        label: &str,
    ) -> (DispatchContext, DispatchGrant, DurableEffectAuthority) {
        let authority = self
            .effects
            .capture(
                &rule.scope,
                CommitLink {
                    command: format!("command-{label}"),
                    caller_scope: "caller-a".into(),
                    attempt: 1,
                    commit: format!("commit-{label}"),
                    effect: format!("effect-{label}"),
                    sequence: 0,
                },
                100,
                "a".repeat(64),
                time(),
            )
            .unwrap();
        let original = Arc::new(
            self.native
                .reserve(
                    NativeAdmissionClass::Ordinary,
                    NativeReservationRequest {
                        request_bytes: 4096,
                        work_bytes: 8192,
                        response_bytes: 4096,
                    },
                    deadline(),
                )
                .unwrap(),
        );
        let mut context = self.effects.accept(&authority, 1, time()).unwrap();
        context
            .retain_owner(original)
            .unwrap_or_else(|_| panic!("original native keeper refused"));
        let grant = context
            .accept_with(&authority, 1, time(), |grant| grant)
            .unwrap();
        (context, grant, authority)
    }
}

fn change_policy(
    store: &PolicyStore,
    operation: &str,
    expected: u64,
    value: Option<&Value>,
) -> u64 {
    let bytes = value.map(|value| serde_json::to_vec(value).unwrap());
    store
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "intents",
                kind: RecordKind::Policy,
                operation_id: operation,
                expected_revision: expected,
                document: bytes.as_deref(),
            },
            deadline(),
            |_| Ok(()),
        )
        .unwrap()
        .value()
        .revision
}
fn effect_rule(publication: &PublicationRef, revision: u64) -> EffectRule {
    EffectRule {
        scope: EffectScope {
            tenant: "a".into(),
            namespace: "orders".into(),
            incarnation: 1,
            publication: publication.id.as_str().into(),
            binding: "events".into(),
            operation: "event".into(),
        },
        profile: DispatchProfile {
            provider: "events".into(),
            destination: "orders".into(),
            adapter: "qualified-test-v1".into(),
            intent_format: 1,
            payload_format: "value.v1".into(),
            idempotency_profile: "dedup.v1".into(),
        },
        policy_revision: revision,
        credential_epoch: 1,
        protected_credential_reference: "events-secret".into(),
        ceiling: DispatchCeiling {
            maximum_payload_bytes: 1024,
            maximum_response_bytes: 1024,
            maximum_attempts: 3,
            maximum_age_millis: 60000,
            attempt_timeout_millis: 30000,
        },
        enabled: true,
    }
}

#[tokio::test]
async fn actual_policy_withdraw_then_reapprove_reseals_fresh_work_and_keeps_held_original_native_owner(
) {
    let owners = OriginalOwners::new().await;
    let original_rule = owners.install_current(&owners.publication).unwrap();
    let (original_context, original_grant, original_authority) =
        owners.accepted(&original_rule, "original");
    assert_eq!(owners.native.snapshot().unwrap().ordinary.slots, 1);
    let withdrawn = change_policy(&owners.policy, "withdraw", owners.policy_revision, None);
    assert!(original_grant.check_current(time()).is_err());
    assert!(owners.install_current(&owners.publication).is_err());
    assert_eq!(
        owners.effects.publish(original_rule),
        Err(AuthorityError::Stale)
    );
    change_policy(
        &owners.policy,
        "reapprove",
        withdrawn,
        Some(&document(&owners.publication)),
    );
    let current_rule = owners.install_current(&owners.publication).unwrap();
    let (fresh_context, fresh_grant, _) = owners.accepted(&current_rule, "fresh");
    assert_eq!(fresh_grant.check_current(time()), Ok(()));
    assert_eq!(
        original_grant.check_current(time()),
        Err(AuthorityError::Stale)
    );
    assert_eq!(owners.effects.owners().unwrap().physical, 2);
    assert_eq!(owners.native.snapshot().unwrap().ordinary.slots, 2);
    assert_eq!(
        original_authority.scope().publication,
        owners.publication.id.as_str()
    );
    fresh_context.retire().unwrap();
    drop(fresh_grant);
    assert_eq!(owners.native.snapshot().unwrap().ordinary.slots, 1);
    original_context.retire().unwrap();
    assert_eq!(owners.native.snapshot().unwrap().ordinary.slots, 1);
    drop(original_grant);
    assert_eq!(owners.native.snapshot().unwrap().ordinary.slots, 0);
}

#[tokio::test]
async fn actual_publication_withdrawal_denies_held_original_and_stale_install_while_new_current_work_reseals(
) {
    let owners = OriginalOwners::new().await;
    let original_rule = owners.install_current(&owners.publication).unwrap();
    let (context, grant, _) = owners.accepted(&original_rule, "original");
    let mutation = ReleaseMutationContext {
        scope: LifecycleScope::Tenant(TenantId("a".into())),
        actor: ReleaseActor {
            subject: "operator".into(),
            kind: ReleaseActorKind::Administrator,
        },
        operation: Some(ReleaseOperationPrecondition {
            operation_id: "withdraw-publication".into(),
            expected_generation: 1,
        }),
    };
    let receipt = owners
        .catalog
        .change_publication_lifecycle(
            mutation.clone(),
            &owners.publication,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    assert_eq!(grant.check_current(time()), Err(AuthorityError::Stale));
    assert!(owners.install_current(&owners.publication).is_err());
    assert_eq!(
        owners.effects.publish(original_rule),
        Err(AuthorityError::Stale)
    );
    assert_eq!(owners.effects.owners().unwrap().physical, 1);
    assert_eq!(owners.native.snapshot().unwrap().ordinary.slots, 1);
    let (fresh_publication, _) = fixture::publish(&owners.catalog, "replacement").await;
    assert_ne!(fresh_publication.id, owners.publication.id);
    change_policy(
        &owners.policy,
        "approve-replacement",
        owners.policy_revision,
        Some(&document(&fresh_publication)),
    );
    let fresh_rule = owners.install_current(&fresh_publication).unwrap();
    let (fresh_context, fresh_grant, _) = owners.accepted(&fresh_rule, "fresh");
    let recovered = owners
        .catalog
        .change_publication_lifecycle(
            mutation,
            &owners.publication,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    assert_eq!(receipt, recovered);
    assert_eq!(fresh_grant.check_current(time()), Ok(()));
    assert_eq!(grant.check_current(time()), Err(AuthorityError::Stale));
    fresh_context.retire().unwrap();
    drop(fresh_grant);
    context.retire().unwrap();
    assert_eq!(owners.native.snapshot().unwrap().ordinary.slots, 1);
    drop(grant);
    assert_eq!(owners.native.snapshot().unwrap().ordinary.slots, 0);
}
