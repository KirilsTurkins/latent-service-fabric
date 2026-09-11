use latent_wire::management::proto;

use super::super::association;
use super::{bounds, deployment, release};

#[test]
fn release_replies_must_match_expected_digest_tenant_and_service_filter() {
    let value = release();
    association::release(
        Some(&value),
        "examples",
        Some(&value.digest),
        Some("examples/echo"),
    )
    .unwrap();
    let other_digest = format!("sha256:{}", "b".repeat(64));
    assert!(association::release(Some(&value), "examples", Some(&other_digest), None).is_err());
    assert!(association::release(Some(&value), "foreign", None, None).is_err());
    assert!(association::release(Some(&value), "examples", None, Some("examples/other")).is_err());
    let mut missing_scope = value;
    missing_scope.tenant = None;
    assert!(association::release(Some(&missing_scope), "examples", None, None).is_err());
}

#[test]
fn deployment_replies_cannot_substitute_a_different_valid_object_or_scope() {
    let value = deployment();
    association::deployment(
        Some(&value),
        "examples",
        Some("echo-production"),
        Some("examples/echo"),
    )
    .unwrap();
    let mut substituted = value.clone();
    substituted.id = "echo-staging".to_owned();
    substituted.metadata.as_mut().unwrap().name = substituted.id.clone();
    bounds::checked(&substituted, 4096).unwrap();
    assert!(
        association::deployment(Some(&substituted), "examples", Some(&value.id), None).is_err()
    );
    assert!(association::deployment(Some(&value), "foreign", None, None).is_err());
    assert!(
        association::deployment(Some(&value), "examples", None, Some("examples/other")).is_err()
    );
}

#[test]
fn node_reply_and_explicit_route_generation_are_bound_to_the_request() {
    let node = proto::NodeInventory {
        node: Some(proto::NodeDescriptor {
            id: "node-a".to_owned(),
            ..proto::NodeDescriptor::default()
        }),
        ..proto::NodeInventory::default()
    };
    association::node(Some(&node), "node-a").unwrap();
    assert!(association::node(Some(&node), "node-b").is_err());
    let snapshot = snapshot();
    association::route(Some(&snapshot), "examples", Some(u64::MAX)).unwrap();
    association::route(Some(&snapshot), "examples", None).unwrap();
    assert!(association::route(Some(&snapshot), "examples", Some(0)).is_err());
    assert!(association::route(Some(&snapshot), "foreign", None).is_err());
}

#[test]
fn absent_optional_get_results_remain_not_found_without_invented_identities() {
    association::release(None, "examples", Some("requested"), None).unwrap();
    association::deployment(None, "examples", Some("requested"), None).unwrap();
    association::node(None, "requested").unwrap();
    association::route(None, "examples", Some(1)).unwrap();
}

#[test]
fn explicit_page_sizes_bound_all_lists_and_zero_preserves_the_server_default() {
    association::page_count(0, 1).unwrap();
    association::page_count(1, 1).unwrap();
    assert!(association::page_count(2, 1).is_err());
    association::page_count(50, 0).unwrap();
}

#[test]
fn node_list_rows_must_match_every_requested_filter() {
    let mut value = proto::NodeInventory {
        node: Some(proto::NodeDescriptor {
            trust_classes: vec!["internal".to_owned(), "secondary".to_owned()],
            region: Some("region-a".to_owned()),
            zone: Some("zone-a".to_owned()),
            ..proto::NodeDescriptor::default()
        }),
        ..proto::NodeInventory::default()
    };
    association::node_filters(&value, Some("internal"), Some("region-a"), Some("zone-a")).unwrap();
    association::node_filters(&value, Some("secondary"), None, None).unwrap();
    assert!(association::node_filters(&value, Some("foreign"), None, None).is_err());
    assert!(association::node_filters(&value, None, Some("region-b"), None).is_err());
    assert!(association::node_filters(&value, None, None, Some("zone-b")).is_err());
    value.node.as_mut().unwrap().zone = None;
    assert!(association::node_filters(&value, None, None, Some("zone-a")).is_err());
    association::node_filters(&value, None, None, None).unwrap();
}

#[test]
fn malformed_release_digests_are_rejected_even_when_other_receipt_fields_are_valid() {
    for invalid in [
        "not-a-digest".to_owned(),
        "a".repeat(64),
        format!("sha256:{}", "A".repeat(64)),
        format!("sha256:{}", "a".repeat(63)),
    ] {
        let mut value = release();
        value.digest = invalid;
        assert!(bounds::checked(&value, 4096).is_err());
    }
    bounds::checked(&release(), 4096).unwrap();
}

#[test]
fn route_snapshot_and_revision_release_digests_use_the_actual_sha256_grammar() {
    let mut value = proto::GetRouteSnapshotResponse {
        snapshot: Some(snapshot()),
    };
    bounds::checked(&value, 4096).unwrap();
    value.snapshot.as_mut().unwrap().snapshot_digest = "invalid".to_owned();
    assert!(bounds::checked(&value, 4096).is_err());
    value.snapshot = Some(snapshot());
    value.snapshot.as_mut().unwrap().services[0].revisions[0].release_digest = "invalid".to_owned();
    assert!(bounds::checked(&value, 4096).is_err());
}

fn snapshot() -> proto::RouteSnapshot {
    proto::RouteSnapshot {
        tenant: Some("examples".to_owned()),
        generation: u64::MAX,
        snapshot_digest: format!("sha256:{}", "a".repeat(64)),
        services: vec![proto::ServiceRoute {
            route_id: "route".to_owned(),
            service: "examples/echo".to_owned(),
            tenant: "examples".to_owned(),
            revisions: vec![proto::RevisionRoute {
                revision_id: "revision".to_owned(),
                release_digest: release().digest,
                weight: 10_000,
                attributes: std::collections::HashMap::default(),
            }],
        }],
        ..proto::RouteSnapshot::default()
    }
}
