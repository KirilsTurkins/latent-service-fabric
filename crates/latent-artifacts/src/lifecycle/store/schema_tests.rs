use crate::{
    LifecycleScope, ReleaseActor, ReleaseActorKind, ReleaseLifecycleAction, ReleaseLifecycleReason,
    ReleaseLifecycleRecord, ReleaseLifecycleState, ReleaseOperationDisposition,
    ReleaseOperationReceipt,
};
use latent_core::{ReleaseDigest, TenantId};

#[test]
fn local_record_and_receipt_match_shared_schema_fixture() {
    // Diagnostic time is historical metadata, never an admission or clock grant.
    let observed_at_unix_millis = Some(1_700_000_000_000);
    let scope = LifecycleScope::Tenant(TenantId("schema-fixture".to_owned()));
    let actor = ReleaseActor {
        subject: "fixture-admin".to_owned(),
        kind: ReleaseActorKind::Administrator,
    };
    let release = ReleaseDigest(format!("sha256:{}", "a".repeat(64)));
    let record = ReleaseLifecycleRecord {
        scope: scope.clone(),
        release: release.clone(),
        package: None,
        state: ReleaseLifecycleState::Admitted,
        generation: 1,
        actor: actor.clone(),
        reason: ReleaseLifecycleReason::Admitted,
        operation_id: "schema-publish-1".to_owned(),
        policy: None,
        observed_at_unix_millis,
        evidence_revision_digest: None,
    };
    let receipt = ReleaseOperationReceipt {
        operation_id: "schema-publish-1".to_owned(),
        request_digest: format!("sha256:{}", "b".repeat(64)).parse().unwrap(),
        scope,
        actor,
        action: ReleaseLifecycleAction::Publish,
        disposition: ReleaseOperationDisposition::Committed,
        reason: ReleaseLifecycleReason::Admitted,
        component_digest: Some(release),
        package_manifest_digest: None,
        expected_generation: Some(0),
        record: Some(record.clone()),
        policy: None,
        observed_at_unix_millis,
    };
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../../tools/tests/fixtures/release_lifecycle/pair.json"
    ))
    .unwrap();
    assert_eq!(serde_json::to_value(&record).unwrap(), fixture["record"]);
    assert_eq!(serde_json::to_value(&receipt).unwrap(), fixture["receipt"]);
    assert_eq!(
        serde_json::from_value::<ReleaseLifecycleRecord>(fixture["record"].clone()).unwrap(),
        record
    );
    assert_eq!(
        serde_json::from_value::<ReleaseOperationReceipt>(fixture["receipt"].clone()).unwrap(),
        receipt
    );
}
