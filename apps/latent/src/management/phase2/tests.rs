use super::{
    projection::{self, Project},
    proto, RecoveryContext,
};
use crate::{
    args::{Cli, Command},
    config::{InputLimits, ResolvedConfig},
    error::Failure,
    operation::Operation,
};
use clap::Parser;
use std::time::Duration;

fn parse(args: &[&str]) -> Cli {
    Cli::try_parse_from(args).unwrap()
}
fn config() -> ResolvedConfig {
    ResolvedConfig {
        endpoint: "http://127.0.0.1:1".into(),
        tenant: "examples".into(),
        token: "private-test-credential".into(),
        connect_timeout: Duration::from_secs(1),
        rpc_timeout: Duration::from_secs(1),
        limits: InputLimits::default(),
    }
}

#[test]
fn rollout_start_requires_matching_candidate_weight_without_rewriting_the_manifest() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("candidate.json");
    let mut manifest: serde_json::Value = serde_json::from_slice(include_bytes!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../examples/echo-contract/deployment.json"
    )))
    .unwrap();
    manifest["spec"]["route"]["weight"] = serde_json::json!(10000);
    let original = serde_json::to_vec(&manifest).unwrap();
    std::fs::write(&path, &original).unwrap();
    let cli = parse(&[
        "latent",
        "rollout",
        "start",
        "ship",
        "--base",
        "base",
        "--expected-base-generation",
        "1",
        "--candidate",
        path.to_str().unwrap(),
        "--weights",
        "1000,10000",
        "--operation-id",
        "start-1",
        "--expected-revision",
        "0",
    ]);
    cli.validate().unwrap();
    let failure = crate::management::prepare(&cli.command, &config())
        .err()
        .unwrap();
    assert_eq!(failure.error["code"], "rollout-candidate-weight");
    assert!(!failure.request_dispatched);
    assert_eq!(std::fs::read(&path).unwrap(), original);

    manifest["spec"]["route"]["weight"] = serde_json::json!(1000);
    let aligned = serde_json::to_vec(&manifest).unwrap();
    std::fs::write(&path, &aligned).unwrap();
    let Operation::StartRollout(request) =
        crate::management::prepare(&cli.command, &config()).unwrap()
    else {
        panic!("start")
    };
    assert_eq!(request.candidate.unwrap().route_weight, 1000);
    assert_eq!(request.candidate_weights, vec![1000, 10000]);
    assert_eq!(std::fs::read(&path).unwrap(), aligned);
}

#[test]
fn managed_preconditions_preserve_u64_max_without_automatic_operation_ids() {
    let maximum = u64::MAX.to_string();
    let cli = parse(&[
        "latent",
        "deployment",
        "delete",
        "ship",
        "--operation-id",
        "delete-1",
        "--expected-state-version",
        &maximum,
        "--expected-generation",
        &maximum,
    ]);
    cli.validate().unwrap();
    let Operation::DeleteDeployment(request) =
        crate::management::prepare(&cli.command, &config()).unwrap()
    else {
        panic!("delete")
    };
    assert_eq!(request.expected_generation, Some(u64::MAX));
    assert_eq!(
        request.operation.unwrap().expected_state_version,
        Some(u64::MAX)
    );
    let legacy = parse(&["latent", "deployment", "delete", "ship"]);
    legacy.validate().unwrap();
    let Operation::DeleteDeployment(request) =
        crate::management::prepare(&legacy.command, &config()).unwrap()
    else {
        panic!("delete")
    };
    assert!(request.operation.is_none());
    for args in [
        vec![
            "latent",
            "deployment",
            "delete",
            "ship",
            "--operation-id",
            "op",
        ],
        vec![
            "latent",
            "rollout",
            "rollback",
            "ship",
            "--operation-id",
            "op",
            "--expected-revision",
            "1",
        ],
        vec![
            "latent",
            "release",
            "revoke",
            "digest",
            "--operation-id",
            "op",
            "--expected-generation",
            "0",
        ],
    ] {
        assert!(Cli::try_parse_from(args).is_err());
    }
}

#[test]
fn explicit_snapshot_and_exact_rollback_target_are_prepared_without_network() {
    let cli = parse(&[
        "latent",
        "deployment",
        "get",
        "ship",
        "--operation-snapshot",
    ]);
    cli.validate().unwrap();
    let Operation::GetDeployment(request) =
        crate::management::prepare(&cli.command, &config()).unwrap()
    else {
        panic!("snapshot")
    };
    assert!(request.include_operation_snapshot);
    let cli = parse(&[
        "latent",
        "rollout",
        "rollback",
        "ship",
        "--operation-id",
        "op",
        "--expected-revision",
        "3",
        "--target-generation",
        "2",
    ]);
    cli.validate().unwrap();
    let Operation::ChangeRollout(request) =
        crate::management::prepare(&cli.command, &config()).unwrap()
    else {
        panic!("rollback")
    };
    assert_eq!(request.operation.unwrap().expected_revision, Some(3));
    assert!(matches!(
        request.command,
        Some(proto::change_rollout_request::Command::Rollback(
            proto::RollbackRollout {
                target_generation: 2
            }
        ))
    ));
}

#[test]
fn audit_scope_filters_are_explicit_and_paging_is_one_request() {
    let cli = parse(&[
        "latent",
        "audit",
        "query",
        "--scope",
        "node",
        "--kind",
        "cache-hit",
        "--page-size",
        "2",
        "--page-token",
        "opaque",
    ]);
    cli.validate().unwrap();
    let Operation::QueryAudit(request) =
        crate::management::prepare(&cli.command, &config()).unwrap()
    else {
        panic!("audit")
    };
    assert_eq!(
        request.scope.unwrap(),
        proto::AuditQueryScope {
            kind: proto::AuditScopeKind::Node as i32,
            tenant: None
        }
    );
    assert_eq!(request.page.unwrap().page_token.as_deref(), Some("opaque"));
    assert_eq!(
        request.filter.unwrap().kind,
        Some(proto::Phase2AuditEventKind::CacheHit as i32)
    );
    let invalid = parse(&[
        "latent",
        "audit",
        "query",
        "--from-unix-millis",
        "2",
        "--to-unix-millis",
        "1",
    ]);
    assert!(invalid.validate().is_err());
}

#[test]
fn projection_preserves_large_counters_and_rejects_spare_capacity_before_json() {
    let counters = proto::RolloutCanaryCounters {
        selected: u64::MAX,
        admitted: u64::MAX,
        admitted_terminal: u64::MAX,
        success: u64::MAX,
        latency_buckets: vec![u64::MAX; 9],
        ..Default::default()
    };
    projection::checked(&counters, 4096).unwrap();
    let value = counters.project();
    assert_eq!(value["selected"], u64::MAX.to_string());
    assert_eq!(value["latencyBuckets"][8], u64::MAX.to_string());
    let mut name = String::with_capacity(16384);
    name.push_str("actor");
    let bad = proto::ReleaseActor {
        subject: name,
        kind: proto::ReleaseActorKind::Administrator as i32,
    };
    assert!(projection::checked(&bad, 4096).is_err());
    let malformed = proto::DeploymentOperationReceipt {
        action: 999,
        ..Default::default()
    };
    assert!(projection::checked(&malformed, 4096).is_err());
    let malformed = proto::ReleaseOperationReceipt {
        action: 999,
        ..Default::default()
    };
    assert!(projection::checked(&malformed, 4096).is_err());
}

#[test]
fn interruption_recovery_keeps_only_exact_small_selectors() {
    let operation = Operation::ChangeRollout(proto::ChangeRolloutRequest {
        id: "ship".into(),
        operation: Some(proto::RolloutOperationPrecondition {
            operation_id: "rollback-1".into(),
            expected_revision: Some(u64::MAX),
        }),
        command: Some(proto::change_rollout_request::Command::Rollback(
            proto::RollbackRollout {
                target_generation: 5,
            },
        )),
    });
    let recovery = RecoveryContext::from_operation(&operation, "examples");
    let mut failure = Failure::interrupted(true);
    recovery.failure(&mut failure);
    assert!(!failure.outcome_known);
    assert_eq!(failure.data["recovery"]["operationId"], "rollback-1");
    assert_eq!(
        failure.data["recovery"]["expectedRevision"],
        u64::MAX.to_string()
    );
    assert_eq!(failure.data["recovery"]["targetGeneration"], "5");
    assert!(failure.data["recovery"].get("token").is_none());
}

#[test]
fn fixed_audit_metadata_survives_rpc_error_without_remote_text() {
    let mut status = tonic::Status::aborted("private remote diagnostic");
    status
        .metadata_mut()
        .insert("latent-audit-status", "durable".parse().unwrap());
    status.metadata_mut().insert(
        "latent-audit-attempt",
        u64::MAX.to_string().parse().unwrap(),
    );
    let failure = Failure::from_status(&status);
    assert_eq!(
        failure.data["auditAck"]["attemptSequence"],
        u64::MAX.to_string()
    );
    assert!(!failure.error.to_string().contains("private"));
    status
        .metadata_mut()
        .insert("latent-audit-status", "private-secret".parse().unwrap());
    assert_eq!(
        Failure::from_status(&status).error["code"],
        "invalid-management-response"
    );
}

#[test]
fn typed_audit_ack_requires_the_same_positive_sequence_as_metadata() {
    for status in [
        proto::AuditAckStatus::Durable,
        proto::AuditAckStatus::OutcomeUnknown,
    ] {
        for attempt_sequence in [None, Some(0)] {
            assert!(projection::checked(
                &proto::AuditAck {
                    status: status as i32,
                    attempt_sequence
                },
                4096
            )
            .is_err());
        }
        projection::checked(
            &proto::AuditAck {
                status: status as i32,
                attempt_sequence: Some(u64::MAX),
            },
            4096,
        )
        .unwrap();
    }
    projection::checked(
        &proto::AuditAck {
            status: proto::AuditAckStatus::Disabled as i32,
            attempt_sequence: None,
        },
        4096,
    )
    .unwrap();
}

#[test]
fn canary_advance_is_not_a_healthy_flag_and_missing_target_is_rejected() {
    for args in [
        vec!["latent", "rollout", "promote", "ship", "--healthy"],
        vec!["latent", "rollout", "rollback", "ship", "--force"],
        vec!["latent", "release", "revoke", "digest", "--retry"],
    ] {
        assert!(Cli::try_parse_from(args).is_err());
    }
    let cli = parse(&[
        "latent",
        "rollout",
        "start",
        "ship",
        "--base",
        "base",
        "--expected-base-generation",
        "1",
        "--candidate",
        "candidate.json",
        "--weights",
        "5000,1000,10000",
        "--operation-id",
        "start",
        "--expected-revision",
        "0",
    ]);
    assert!(matches!(cli.command, Command::Rollout(_)));
    assert!(cli.validate().is_err());
}
