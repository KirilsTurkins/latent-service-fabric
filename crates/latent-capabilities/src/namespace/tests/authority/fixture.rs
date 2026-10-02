use super::*;
use latent_artifacts::{
    ArtifactDescriptor, ArtifactRepository, CapsuleArtifact, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, LifecycleScope, ManagedPublicationUpload, ReleaseActor,
    ReleaseActorKind, ReleaseMutationContext, ReleaseOperationPrecondition, ReleaseUseEligibility,
};
use latent_core::ArtifactReference;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_policy::capability::{
    CallRestrictions, GrantRestriction, MutationRequest, PolicySnapshot, PolicyStoreLimits,
    RecordKind, StateResourceScope,
};
use latent_state::{
    embedded::{EmbeddedStore, StoreLimits},
    namespace::catalog::{NamespaceCatalog, NamespaceMutation, NamespaceOperationContext},
};
use serde_json::{json, Value};
use std::{
    cell::Cell,
    fs::OpenOptions,
    future::Future,
    task::{Context, Poll, Waker},
    time::Duration,
};

pub(super) fn schema() -> String {
    format!("sha256:{}", "1".repeat(64))
}
pub(super) fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(10)
}

pub(super) struct Fixture {
    pub policy: PolicyStore,
    pub database: Arc<EmbeddedStore>,
    pub namespaces: NamespaceCatalog,
    pub publication: ReleaseUseEligibility,
    pub other: ReleaseUseEligibility,
    pub catalog: DirectoryArtifactRepository,
    pub document: Value,
    revision: Cell<u64>,
    _dir: tempfile::TempDir,
}
impl Fixture {
    pub fn new() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let catalog = DirectoryArtifactRepository::open(
            dir.path().join("artifacts"),
            DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap();
        let publication = publish(&catalog, "first");
        let other = publish(&catalog, "same-component-correction");
        let policy = PolicyStore::open(
            &dir.path().join("policy"),
            PolicyStoreLimits::default(),
            catalog.lifecycle_authority(),
        )
        .unwrap();
        let document = json!({"formatVersion":1,"tenant":"a","rules":[
            rule("alice", Some("alice-order"), &publication), rule("bob", Some("bob-order"), &publication)]});
        let receipt = policy
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    kind: RecordKind::Policy,
                    id: "state",
                    operation_id: "state-create",
                    expected_revision: 0,
                    document: Some(&serde_json::to_vec(&document).unwrap()),
                },
                deadline(),
                |_| Ok(()),
            )
            .unwrap();
        let revision = receipt.value().revision;
        drop(receipt);
        let binding = json!({"formatVersion":1,"tenant":"a","capability":STATE_CONTRACT,
            "providerProfile":"namespace-v1","configurationDigest":format!("sha256:{}","2".repeat(64)),
            "configurationEpoch":1,"restriction":{"operations":[]}});
        policy
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    kind: RecordKind::ProviderBinding,
                    id: "binding",
                    operation_id: "binding-create",
                    expected_revision: 0,
                    document: Some(&serde_json::to_vec(&binding).unwrap()),
                },
                deadline(),
                |_| Ok(()),
            )
            .unwrap();
        let database = Arc::new(
            EmbeddedStore::open_file(
                OpenOptions::new()
                    .read(true)
                    .write(true)
                    .create_new(true)
                    .open(dir.path().join("transaction.redb"))
                    .unwrap(),
                StoreLimits::default(),
            )
            .unwrap(),
        );
        let namespaces = NamespaceCatalog::new();
        let mutation = NamespaceMutation::Create {
            id: latent_core::StateNamespaceId("orders".into()),
            state_schema: schema(),
            quota: latent_state::namespace::NamespaceQuota::default(),
        };
        // Trusted fixture data only. Production lifecycle operations use the
        // current `NamespaceControl` fence, tested below.
        database
            .apply(
                namespaces
                    .prepare(
                        &database,
                        NamespaceOperationContext {
                            tenant: TenantId("a".into()),
                            actor: "operator".into(),
                            operation_id: "create".into(),
                        },
                        &mutation,
                        0,
                    )
                    .unwrap()
                    .batch,
            )
            .unwrap();
        Self {
            policy,
            database,
            namespaces,
            publication,
            other,
            catalog,
            document,
            revision: Cell::new(revision),
            _dir: dir,
        }
    }
    pub fn read(&self) -> NamespaceRead {
        NamespaceCatalog::read_in(
            &self.database.snapshot().unwrap(),
            &TenantId("a".into()),
            &latent_core::StateNamespaceId("orders".into()),
        )
        .unwrap()
        .unwrap()
    }
    pub fn snapshot(&self) -> PolicySnapshot {
        self.policy
            .snapshot(
                &TenantId("a".into()),
                &["state".into()],
                "binding",
                deadline(),
            )
            .unwrap()
    }
    pub fn update(&self, document: Option<&Value>, operation: &str) {
        let bytes = document.map(|value| serde_json::to_vec(value).unwrap());
        let receipt = self
            .policy
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    kind: RecordKind::Policy,
                    id: "state",
                    operation_id: operation,
                    expected_revision: self.revision.get(),
                    document: bytes.as_deref(),
                },
                deadline(),
                |_| Ok(()),
            )
            .unwrap();
        self.revision.set(receipt.value().revision);
    }
    pub fn decision<'a>(
        &'a self,
        snapshot: &'a PolicySnapshot,
        actor: &'a latent_core::InvocationPrincipal,
        scope: &'a StateResourceScope,
        operation: &'a str,
    ) -> SealedPolicyDecision<'a> {
        self.decision_for(snapshot, actor, scope, operation, &self.publication)
            .unwrap()
    }
    pub fn decision_for<'a>(
        &'a self,
        snapshot: &'a PolicySnapshot,
        actor: &'a latent_core::InvocationPrincipal,
        scope: &'a StateResourceScope,
        operation: &'a str,
        publication: &'a ReleaseUseEligibility,
    ) -> Result<SealedPolicyDecision<'a>, PlatformError> {
        let inherited = GrantRestriction::parse(br#"{"operations":[]}"#, STATE_CONTRACT).unwrap();
        let imported = vec![operation.into()];
        let digest = format!("sha256:{}", "2".repeat(64));
        let decision = snapshot.authorize(
            EvaluationInput {
                principal: actor,
                service: "echo",
                publication: publication.publication().as_str(),
                capability: STATE_CONTRACT,
                operation,
                resource: ResourceTarget::State {
                    namespace: &scope.namespace,
                    incarnation: scope.incarnation,
                    entity: scope.entity.as_deref(),
                    recovery_kind: scope.recovery_kind,
                    recovery_scope: &scope.recovery_scope,
                    result_policy: &scope.result_policy,
                },
            },
            &CallRestrictions {
                imported_operations: &imported,
                deployment: &inherited,
                provider_configuration: &inherited,
                provider_profile: "namespace-v1",
                configuration_digest: &digest,
                configuration_epoch: 1,
                remaining: CapabilityCeiling {
                    operations: 16,
                    input_bytes: 1_048_576,
                    output_bytes: 1_048_576,
                    wall_time_millis: 10_000,
                },
                input_bytes: 0,
                output_bytes: 0,
            },
            publication,
        )?;
        self.policy.with_current(&decision, &mut |_, _| Ok(()))?;
        Ok(decision)
    }
}
pub(super) fn scope(
    actor: &latent_core::InvocationPrincipal,
    entity: Option<&str>,
    selection: &RecoverySelection,
) -> StateResourceScope {
    let caller = CallerScope::derive(actor, selection).unwrap();
    StateResourceScope {
        namespace: "orders".into(),
        incarnation: 1,
        entity: entity.map(str::to_owned),
        recovery_kind: caller.kind,
        recovery_scope: caller.scope,
        result_policy: "visibility-v1".into(),
    }
}
fn rule(subject: &str, entity: Option<&str>, publication: &ReleaseUseEligibility) -> Value {
    json!({"id":subject,"effect":"allow","principals":[{"kind":"user","subject":subject}],
        "services":["echo"],"publications":[publication.publication().as_str()],"capability":STATE_CONTRACT,
        "operations":["acquire-command","acquire-query","get","get-query","put","delete","page-next","commit","read-result","inspect-effect","cancel-command"],
        "resources":{"kind":"state","scopes":[scope(&principal(subject),entity,&RecoverySelection::OriginalCaller)]},
        "ceiling":{"operations":16,"inputBytes":1_048_576,"outputBytes":1_048_576,"wallTimeMillis":10_000}})
}
fn ready<T>(future: impl Future<Output = T>) -> T {
    let mut future = Box::pin(future);
    match future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
    {
        Poll::Ready(value) => value,
        Poll::Pending => panic!("synchronous fixture queued work"),
    }
}
fn publish(catalog: &DirectoryArtifactRepository, label: &str) -> ReleaseUseEligibility {
    // Real catalog/currentness, no guest execution or runtime qualification.
    let component = b"\0asm\x0d\0\x01\0".to_vec();
    let digest = latent_artifacts::content_digest(&component);
    let mut value: Value = serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../latent-manifest/tests/fixtures/valid-capsule-v1alpha1.json"
    )))
    .unwrap();
    value["component"]["digest"] = digest.0.clone().into();
    value["metadata"]["tenant"] = "a".into();
    value["metadata"]["name"] = "a/echo".into();
    value["component"]["world"] = "a:echo/service@0.1.0".into();
    value["exports"] = json!(["a:echo/api@0.1.0"]);
    let manifest = JsonManifestCodec::default()
        .decode_capsule(&serde_json::to_vec(&value).unwrap())
        .unwrap();
    let artifact = CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("local://tests/{label}")),
            release_digest: digest,
            media_type: "application/vnd.wasm.component.v1+wasm".into(),
            size_bytes: component.len() as u64,
            publisher: None,
            layers: vec![],
            annotations: Metadata::new(),
        },
        manifest,
        contracts: vec![],
        component_bytes: component,
    };
    let receipt = ready(catalog.publish_managed(
        ReleaseMutationContext {
            scope: LifecycleScope::Tenant(TenantId("a".into())),
            actor: ReleaseActor {
                subject: "operator".into(),
                kind: ReleaseActorKind::Administrator,
            },
            operation: Some(ReleaseOperationPrecondition {
                operation_id: label.into(),
                expected_generation: 0,
            }),
        },
        ManagedPublicationUpload::Local(artifact),
        &mut |_| Ok(()),
    ))
    .unwrap();
    catalog
        .execution_eligibility_selected(
            &receipt.operation.record.as_ref().unwrap().release,
            Some(&receipt.publication.id),
        )
        .unwrap()
        .unwrap()
}
