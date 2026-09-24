use super::*;
use crate::args::Cli;
use clap::Parser;
use prost::Message;
use serde_json::json;
use std::collections::HashMap;

fn revision() -> proto::CapabilityInspectionRevision {
    proto::CapabilityInspectionRevision {
        deployment_id: "web".into(),
        revision_id: format!("revision-v1:sha256:{}", "a".repeat(64)),
        component_digest: format!("sha256:{}", "a".repeat(64)),
        publication_id: Some(format!("publication:sha256:{}", "b".repeat(64))),
        route_generation: u64::MAX,
        catalog_transaction: u64::MAX,
    }
}

fn denial() -> proto::ExplainCapabilityGrantResponse {
    proto::ExplainCapabilityGrantResponse {
        reasons: vec!["capability-not-imported".into()],
        revision: Some(revision()),
        obligations: HashMap::from([
            ("live-admission-required".into(), "true".into()),
            ("activation-budget-reserved".into(), "false".into()),
            ("descriptive-only".into(), "true".into()),
        ]),
        ..Default::default()
    }
}

#[test]
fn capability_grammar_has_no_watch_impersonation_or_generic_provider_mutation() {
    for arguments in [
        vec!["latent", "capability", "list"],
        vec![
            "latent",
            "capability",
            "list",
            "--deployment",
            "web",
            "--page-size",
            "129",
        ],
        vec!["latent", "capability", "watch", "--deployment", "web"],
        vec!["latent", "capability", "apply", "--token", "secret"],
        vec![
            "latent",
            "capability",
            "explain",
            "--deployment",
            "web",
            "--capability",
            "random",
            "--operation",
            "get",
            "--resource",
            "resource.json",
            "--principal",
            "administrator",
        ],
    ] {
        assert!(Cli::try_parse_from(arguments).is_err());
    }
    Cli::try_parse_from([
        "latent",
        "capability",
        "list",
        "--deployment",
        "web",
        "--include-node-usage",
    ])
    .unwrap()
    .validate()
    .unwrap();
}

#[test]
fn local_resource_validation_never_accepts_guest_authority_fields() {
    let directory = tempfile::tempdir().unwrap();
    let file = directory.path().join("resource.json");
    std::fs::write(&file, br#"{"kind":"random"}"#).unwrap();
    let command = CapabilityCommand::Explain {
        deployment: "web".into(),
        capability: "latent:random/random@0.1.0".into(),
        operation: "fill".into(),
        resource: file.clone(),
    };
    let Operation::Capability(operation) = prepare(&command).unwrap() else {
        panic!("capability operation")
    };
    let CapabilityOperation::Explain(request) = *operation else {
        panic!("explain request")
    };
    assert!(request.principal.is_empty());
    assert!(request.attributes.is_empty());
    assert!(request.hypothetical_subject.is_none());
    std::fs::write(
        &file,
        br#"{"kind":"random","label":"nonce","principal":"administrator"}"#,
    )
    .unwrap();
    assert!(prepare(&command).is_err());
}

#[test]
fn descriptive_denials_and_full_width_revision_facts_are_not_execution_permission() {
    let original = denial();
    projection::checked(&original, 4096).unwrap();
    let value = original.clone().project();
    assert_eq!(value["allowed"], false);
    assert_eq!(value["executionPermission"], false);
    assert_eq!(value["revision"]["routeGeneration"], u64::MAX.to_string());
    for mutate in [
        (|value: &mut proto::ExplainCapabilityGrantResponse| value.allowed = true)
            as fn(&mut proto::ExplainCapabilityGrantResponse),
        |value| value.reasons = vec!["raw provider response with credential".into()],
        |value| value.revision.as_mut().unwrap().publication_id = Some(String::new()),
        |value| value.policy_digest = "untyped policy".into(),
        |value| {
            value
                .obligations
                .insert("activation-budget-reserved".into(), "true".into());
        },
    ] {
        let mut value = original.clone();
        mutate(&mut value);
        assert!(projection::checked(&value, 4096).is_err());
    }
}

#[test]
fn protobuf_decoded_single_reason_keeps_bounded_allocation_and_closed_semantics() {
    let encoded = denial().encode_to_vec();
    let decoded = proto::ExplainCapabilityGrantResponse::decode(encoded.as_slice()).unwrap();
    projection::checked(&decoded, 4096).unwrap();
    assert_eq!(decoded.reasons.len(), 1);
    assert!(decoded.reasons.capacity() <= 4);
    let mut excess = decoded;
    excess.reasons.push("policy-denied".into());
    assert!(projection::checked(&excess, 4096).is_err());
    excess.reasons = Vec::with_capacity(5);
    excess.reasons.push("policy-denied".into());
    assert!(projection::checked(&excess, 4096).is_err());
}

#[test]
fn usage_reports_only_fixed_owner_counters_and_preserves_unavailable() {
    let usage = proto::CapabilityResourceUsage {
        scope: "node".into(),
        counters: HashMap::from([
            ("broker_calls".into(), u64::MAX),
            ("audit_queued_bytes".into(), 16 * 1024),
            ("audit_stage_bytes".into(), 68 * 1024),
            ("audit_recovery_pending".into(), 1),
        ]),
        unavailable: vec!["provider-io-no-retained-pool-owner".into()],
    };
    projection::checked(&usage, 4096).unwrap();
    let data = usage.clone().project();
    assert_eq!(data["counters"]["broker_calls"], u64::MAX.to_string());
    assert_eq!(data["counters"]["audit_queued_bytes"], "16384");
    assert_eq!(data["counters"]["audit_stage_bytes"], "69632");
    assert_eq!(data["counters"]["audit_recovery_pending"], "1");
    assert_eq!(
        data["unavailable"],
        json!(["provider-io-no-retained-pool-owner"])
    );
    let mut wrong = usage;
    wrong.counters.insert("credential_file".into(), 0);
    assert!(projection::checked(&wrong, 4096).is_err());
}
