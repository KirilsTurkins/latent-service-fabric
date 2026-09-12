#![allow(clippy::unwrap_used)]

#[cfg(target_os = "linux")]
mod authority;
#[cfg(target_os = "linux")]
mod catalog;
#[cfg(target_os = "linux")]
mod clock;
#[cfg(target_os = "linux")]
mod history;
#[cfg(target_os = "linux")]
mod lifecycle;
#[cfg(target_os = "linux")]
mod runtime;
mod support;

use super::*;
use support::*;

#[test]
fn closed_policy_rejects_duplicates_bounds_and_unbound_snapshots() {
    let fixture = Fixture::new();
    let mut value = fixture.policy.clone();
    value["unknown"] = serde_json::json!(true);
    assert!(SupplyChainPolicy::from_json(&serde_json::to_vec(&value).unwrap()).is_err());
    let bytes = serde_json::to_string(&fixture.policy).unwrap();
    let duplicate = bytes.replacen("\"generation\":1", "\"generation\":1,\"generation\":1", 1);
    assert!(SupplyChainPolicy::from_json(duplicate.as_bytes()).is_err());
    let mut value = fixture.policy.clone();
    value["publisherRevocations"]["policyDigest"] =
        serde_json::json!(format!("sha256:{}", "0".repeat(64)));
    assert!(SupplyChainPolicy::from_json(&serde_json::to_vec(&value).unwrap()).is_err());
    let mut value = fixture.policy.clone();
    value["tenants"][0]["publishers"] = serde_json::json!(["publisher-a", "publisher-a"]);
    assert!(SupplyChainPolicy::from_json(&serde_json::to_vec(&value).unwrap()).is_err());
    assert!(SupplyChainPolicy::from_json(&vec![b' '; 256 * 1024 + 1]).is_err());
}

#[test]
fn same_generation_policy_changes_and_component_floor_rollbacks_fail() {
    let fixture = Fixture::new();
    let original = fixture.approved();
    let mut value = fixture.policy.clone();
    value["tenants"][0]["publishers"] = serde_json::json!([]);
    let changed = SupplyChainPolicy::from_json(&serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(changed.identity.replaces(&original.identity).is_err());
    value["generation"] = serde_json::json!(2);
    let next = SupplyChainPolicy::from_json(&serde_json::to_vec(&value).unwrap()).unwrap();
    next.identity.replaces(&original.identity).unwrap();
    assert!(original.identity.replaces(&next.identity).is_err());
}
