use super::*;
use crate::capability::{CallRestrictions, CapabilityCeiling, GrantRestriction};
use latent_artifacts::{
    ArtifactDescriptor, ArtifactRepository, CapsuleArtifact, LifecycleScope,
    ManagedPublicationReceipt, ManagedPublicationUpload, ReleaseActor, ReleaseActorKind,
    ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseMutationContext,
    ReleaseOperationPrecondition,
};
use latent_core::{ArtifactReference, BoxFuture};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use std::task::{Context, Poll, Waker};
mod service;

fn ready<T>(mut future: BoxFuture<'_, T>) -> T {
    match future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
    {
        Poll::Ready(value) => value,
        Poll::Pending => panic!("local synchronous catalog fixture unexpectedly queued work"),
    }
}
fn context(id: &str, generation: u64) -> ReleaseMutationContext {
    ReleaseMutationContext {
        scope: LifecycleScope::Tenant(TenantId("a".into())),
        actor: ReleaseActor {
            subject: "operator".into(),
            kind: ReleaseActorKind::Administrator,
        },
        operation: Some(ReleaseOperationPrecondition {
            operation_id: id.into(),
            expected_generation: generation,
        }),
    }
}
fn publish(fixture: &Fixture, label: &str) -> ManagedPublicationReceipt {
    publish_scoped(fixture, label, "a")
}
fn publish_scoped(fixture: &Fixture, label: &str, tenant: &str) -> ManagedPublicationReceipt {
    // Catalog admission/authority tests, not a claim of guest execution. The
    // same valid empty component bytes are shared by both immutable associations.
    let component_bytes = wasm_encoder::Component::new().finish();
    let digest = latent_artifacts::content_digest(&component_bytes);
    let mut value: serde_json::Value = serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../latent-manifest/tests/fixtures/valid-capsule-v1alpha1.json"
    )))
    .unwrap();
    value["component"]["digest"] = digest.0.clone().into();
    value["metadata"]["tenant"] = tenant.into();
    value["metadata"]["name"] = format!("{tenant}/echo").into();
    value["component"]["world"] = format!("{tenant}:echo/service@0.1.0").into();
    value["exports"] = serde_json::json!([format!("{tenant}:echo/api@0.1.0")]);
    let manifest = JsonManifestCodec::default()
        .decode_capsule(&serde_json::to_vec(&value).unwrap())
        .unwrap();
    let artifact = CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("local://tests/{label}")),
            release_digest: digest,
            media_type: "application/vnd.wasm.component.v1+wasm".into(),
            size_bytes: component_bytes.len() as u64,
            publisher: None,
            layers: vec![],
            annotations: latent_core::Metadata::new(),
        },
        manifest,
        contracts: vec![],
        component_bytes,
    };
    let mut publication_context = context(label, 0);
    publication_context.scope = LifecycleScope::Tenant(TenantId(tenant.into()));
    ready(fixture.catalog.publish_managed(
        publication_context,
        ManagedPublicationUpload::Local(artifact),
        &mut |_| Ok(()),
    ))
    .unwrap()
}
#[test]
#[allow(
    clippy::too_many_lines,
    reason = "one real scoped publication decision exercises narrowing and the final revocation boundary"
)]
fn final_admission_checks_real_catalog_owner_publication_and_every_narrowing() {
    let fixture = Fixture::new();
    let p1 = publish(&fixture, "first");
    let p2 = publish(&fixture, "correction");
    let release = p1.operation.record.as_ref().unwrap().release.clone();
    let proof = fixture
        .catalog
        .execution_eligibility_selected(&release, Some(&p1.publication.id))
        .unwrap()
        .unwrap();
    let other = fixture
        .catalog
        .execution_eligibility_selected(&release, Some(&p2.publication.id))
        .unwrap()
        .unwrap();
    assert_ne!(proof.publication(), other.publication());
    let store = fixture.store(PolicyStoreLimits::default());
    let mut value = policy();
    value["rules"][0]["publications"] = serde_json::json!([proof.publication().as_str()]);
    let bytes = serde_json::to_vec(&value).unwrap();
    mutate(&store, "p", "policy", 0, Some(&bytes)).unwrap();
    let bytes = serde_json::to_vec(&binding()).unwrap();
    store
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                kind: RecordKind::ProviderBinding,
                id: "binding",
                operation_id: "binding",
                expected_revision: 0,
                document: Some(&bytes),
            },
            deadline(),
            |_| Ok(()),
        )
        .unwrap();
    let snapshot = store
        .snapshot(&TenantId("a".into()), &["p".into()], "binding", deadline())
        .unwrap();
    let actor = principal();
    let contract = "latent:secrets/reader@0.1.0";
    let input = || EvaluationInput {
        principal: &actor,
        service: "echo",
        publication: proof.publication().as_str(),
        capability: contract,
        operation: "read",
        resource: ResourceTarget::Secrets {
            reference: "test-key",
        },
    };
    let inherited = GrantRestriction::parse(br#"{"operations":[]}"#, contract).unwrap();
    let imported = vec!["read".into()];
    let digest = format!("sha256:{}", "2".repeat(64));
    let mut restriction = CallRestrictions {
        imported_operations: &imported,
        deployment: &inherited,
        provider_configuration: &inherited,
        provider_profile: "local-secrets-v1",
        configuration_digest: &digest,
        configuration_epoch: 1,
        remaining: CapabilityCeiling {
            operations: 2,
            input_bytes: 100,
            output_bytes: 128,
            wall_time_millis: 50,
        },
        input_bytes: 2,
        output_bytes: 128,
    };
    let decision = snapshot.authorize(input(), &restriction, &proof).unwrap();
    let mut started = 0;
    store
        .with_current(&decision, &mut |actual, ceiling| {
            assert_eq!(actual.publication, proof.publication().as_str());
            assert_eq!(ceiling, restriction.remaining);
            started += 1;
            Ok(())
        })
        .unwrap();
    assert_eq!(started, 1);
    assert!(snapshot.authorize(input(), &restriction, &other).is_err());
    restriction.imported_operations = &[];
    assert!(snapshot.authorize(input(), &restriction, &proof).is_err());
    restriction.imported_operations = &imported;
    restriction.configuration_epoch = 2;
    assert!(snapshot.authorize(input(), &restriction, &proof).is_err());
    restriction.configuration_epoch = 1;
    restriction.output_bytes = 129;
    assert!(snapshot.authorize(input(), &restriction, &proof).is_err());
    restriction.output_bytes = 128;
    let denied = GrantRestriction::parse(
        br#"{"operations":[],"resources":{"kind":"secrets","references":[]}}"#,
        contract,
    )
    .unwrap();
    restriction.deployment = &denied;
    assert!(snapshot.authorize(input(), &restriction, &proof).is_err());
    restriction.deployment = &inherited;
    restriction.provider_configuration = &denied;
    assert!(snapshot.authorize(input(), &restriction, &proof).is_err());
    restriction.provider_configuration = &inherited;
    // The guarded-start read fence excludes a concurrent policy mutation.
    let updated = serde_json::to_vec(&value).unwrap();
    store
        .with_current(&decision, &mut |_, _| {
            assert!(mutate(&store, "p", "update", 2, Some(&updated)).is_err());
            Ok(())
        })
        .unwrap();
    mutate(&store, "p", "update", 2, Some(&updated)).unwrap();
    assert!(store
        .with_current(&decision, &mut |_, _| {
            started += 1;
            Ok(())
        })
        .is_err());
    let snapshot = store
        .snapshot(&TenantId("a".into()), &["p".into()], "binding", deadline())
        .unwrap();
    let decision = snapshot.authorize(input(), &restriction, &proof).unwrap();
    // Held decision/prepared reuse cannot authorize a later operation after its
    // exact publication is revoked, while the other publication remains live.
    fixture
        .catalog
        .change_publication_lifecycle(
            context("revoke", 1),
            &p1.publication,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    assert!(store
        .with_current(&decision, &mut |_, _| {
            started += 1;
            Ok(())
        })
        .is_err());
    assert_eq!(started, 1);
    other.check_current().unwrap();
}
