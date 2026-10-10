use super::*;
use latent_core::{BudgetProfile, DelegationLimits};

#[test]
fn explicit_phase3_profile_derives_zero_or_exact_counter_ceilings() {
    let (_, mut config) = config();
    assert_eq!(
        config.derive().unwrap().budget_profile,
        BudgetProfile::Phase1
    );
    config.budget_profile = serde_json::from_str(r#"{"mode":"phase3"}"#).unwrap();
    let zero = config.derive().unwrap();
    assert_eq!(zero.budget_profile, BudgetProfile::Phase3);
    assert_eq!(zero.admission.budget_ceiling.child_calls, 0);
    assert_eq!(zero.admission.budget_ceiling.outbound_requests, 0);
    assert_eq!(zero.admission.budget_ceiling.blob_read_bytes, 0);
    config.budget_profile = serde_json::from_str(
        r#"{
        "mode":"phase3", "maximumChildCalls":7, "maximumOutboundRequests":3,
        "maximumBlobReadBytes":1024, "maximumBlobWriteBytes":2048,
        "maximumDepth":4, "maximumLiveDescendants":16, "maximumLiveChildren":2
    }"#,
    )
    .unwrap();
    let settings = config.derive().unwrap();
    let budget = settings.admission.budget_ceiling;
    assert_eq!(
        (
            budget.child_calls,
            budget.outbound_requests,
            budget.blob_read_bytes,
            budget.blob_write_bytes
        ),
        (7, 3, 1024, 2048)
    );
    assert_eq!(
        (
            budget.state_read_bytes,
            budget.state_write_bytes,
            budget.effect_count
        ),
        (0, 0, 0)
    );
    assert_eq!(
        settings.delegation_limits,
        DelegationLimits {
            maximum_depth: 4,
            maximum_live_descendants: 16,
            maximum_live_children: 2,
        }
    );
}

#[test]
fn unknown_profiles_fields_and_invalid_tree_limits_fail_closed() {
    let (_, mut config) = config();
    for input in [
        "null",
        r#"{"mode":"phase4"}"#,
        r#"{"mode":"phase1","maximumChildCalls":1}"#,
        r#"{"mode":"phase3","stateReadBytes":1}"#,
        r#"{"mode":"phase3","maximumChildCalls":-1}"#,
    ] {
        assert!(
            serde_json::from_str::<super::super::BudgetConfig>(input).is_err(),
            "{input}"
        );
    }
    for field in [
        "maximumDepth",
        "maximumLiveChildren",
        "maximumLiveDescendants",
    ] {
        for value in [0, 65535] {
            let document = format!(r#"{{"mode":"phase3","{field}":{value}}}"#);
            if let Ok(budget) = serde_json::from_str(&document) {
                config.budget_profile = budget;
                assert!(config.derive().is_err());
            }
        }
    }
    config.budget_profile = serde_json::from_str(
        r#"{"mode":"phase3","maximumLiveChildren":3,"maximumLiveDescendants":2}"#,
    )
    .unwrap();
    assert!(config.derive().is_err());
}
