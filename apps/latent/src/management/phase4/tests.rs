use super::*;
use crate::{
    args::{phase4::*, Cli, Command},
    config::{InputLimits, ResolvedConfig},
    operation::Operation,
    output::Category,
};
use clap::Parser;
use latent_rpc::{control::v1 as c, phase4::Request, transaction::v1 as t};
use serde_json::json;
use std::time::Duration;
mod dispatcher;

fn publication() -> String {
    format!("publication:sha256:{}", "a".repeat(64))
}
fn target() -> NamespaceArgs {
    NamespaceArgs {
        namespace: "app".into(),
        incarnation: "1".into(),
        authorization_publication: publication(),
    }
}
fn config() -> ResolvedConfig {
    ResolvedConfig {
        endpoint: "http://127.0.0.1:1".into(),
        tenant: "tenant".into(),
        token: "fixture".into(),
        connect_timeout: Duration::from_secs(1),
        rpc_timeout: Duration::from_secs(1),
        limits: InputLimits::default(),
    }
}
fn command() -> CommandArgs {
    CommandArgs {
        target: target(),
        operation: "save".into(),
        client_key: "original-key".into(),
        entity: None,
        shared_recovery_scope: None,
    }
}

#[test]
fn grammar_requires_current_target_and_original_operation_precondition() {
    assert!(Cli::try_parse_from([
        "latent",
        "state",
        "quiesce",
        "--namespace",
        "app",
        "--incarnation",
        "1",
        "--authorization-publication",
        &publication(),
        "--operation-id",
        "original"
    ])
    .is_err());
    assert!(Cli::try_parse_from([
        "latent",
        "transaction",
        "lookup",
        "--namespace",
        "app",
        "--incarnation",
        "1",
        "--operation",
        "save",
        "--client-key",
        "original"
    ])
    .is_err());
    let cli = Cli::try_parse_from([
        "latent",
        "state",
        "quiesce",
        "--namespace",
        "app",
        "--incarnation",
        "1",
        "--authorization-publication",
        &publication(),
        "--operation-id",
        "original",
        "--expected-generation",
        "0",
    ])
    .unwrap();
    assert!(cli.validate().is_err());
    for command in ["sql", "get-key", "put-key", "watch"] {
        assert!(Cli::try_parse_from(["latent", "state", command]).is_err());
    }
}
#[test]
fn prepared_mutation_and_lost_response_context_keep_original_identity_and_generation() {
    let command = StateCommand::Quiesce(NamespaceMutationArgs {
        target: target(),
        operation_id: "original".into(),
        expected_generation: 9_007_199_254_740_993,
    });
    let Operation::Phase4(request) = prepare_state(&command, &config()).unwrap() else {
        panic!("phase4 operation");
    };
    let Request::MutateNamespace(value) = request.as_ref() else {
        panic!("namespace request");
    };
    assert_eq!(value.operation_id, "original");
    assert_eq!(value.expected_generation, Some(9_007_199_254_740_993));
    let recovery = recovery(&request).unwrap();
    assert_eq!(recovery["expectedGeneration"], "9007199254740993");
    assert_eq!(recovery["operationId"], "original");
    assert_eq!(recovery["authorizationPublication"]["id"], publication());
    let mut failure = Failure::protocol("response-lost", "original transport lost");
    super::super::phase2::RecoveryContext::from_operation(&Operation::Phase4(request), "tenant")
        .failure(&mut failure);
    assert_eq!(failure.data["recovery"]["operationId"], "original");
    assert!(!failure.outcome_known);
}
#[test]
fn configuration_is_closed_bounded_lossless_and_not_arbitrary_state_editing() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("namespace.json");
    let quota = json!({"stateKeys":"4096","stateBytes":"8388608","resultRows":"4096","resultBytes":"8388608",
        "effectRows":"4096","effectBytes":"8388608","payloadBytes":"8388608","recoveryBytes":"1048576"});
    std::fs::write(
        &path,
        serde_json::to_vec(&json!({"stateSchema":"schema","quota":quota})).unwrap(),
    )
    .unwrap();
    let command = StateCommand::Create(ConfigureNamespaceArgs {
        mutation: NamespaceMutationArgs {
            target: target(),
            operation_id: "create-original".into(),
            expected_generation: 0,
        },
        configuration: path.clone(),
    });
    assert!(prepare_state(&command, &config()).is_ok());
    std::fs::write(
        &path,
        br#"{"stateSchema":"schema","quota":{},"key":"raw-edit"}"#,
    )
    .unwrap();
    assert!(prepare_state(&command, &config()).is_err());
}
#[test]
fn command_lookup_keeps_explicit_attempt_and_current_publication_separate() {
    let command = TransactionCommand::Lookup(LookupArgs {
        command: command(),
        attempt_id: Some("original-attempt".into()),
    });
    let Operation::Phase4(request) = prepare_transaction(&command, &config()).unwrap() else {
        panic!("phase4 operation");
    };
    let Request::LookupCommand(value) = *request else {
        panic!("lookup");
    };
    assert_eq!(value.attempt_id.as_deref(), Some("original-attempt"));
    assert_eq!(value.command.unwrap().client_key, "original-key");
    assert_eq!(value.authorization_publication.unwrap().id, publication());
}
#[test]
fn paging_uses_exact_opaque_continuation_without_hidden_polling() {
    let command = StateCommand::Entities(EntityPageArgs {
        target: target(),
        limit: 128,
        cursor: Some("AQ==".into()),
        prefix: None,
    });
    let Operation::Phase4(request) = prepare_state(&command, &config()).unwrap() else {
        panic!("phase4 operation");
    };
    let Request::SelectEntity(value) = *request else {
        panic!("entities");
    };
    assert_eq!(value.page.unwrap().cursor, Some(vec![1]));
    let malformed = StateCommand::Entities(EntityPageArgs {
        target: target(),
        limit: 128,
        cursor: Some("AQ".into()),
        prefix: None,
    });
    assert!(prepare_state(&malformed, &config()).is_err());
}
#[test]
fn rejection_and_ambiguous_outcomes_remain_distinct_from_success_or_abort() {
    let rejected = t::CommandInspection {
        outcome: t::CommandOutcome::Rejected as i32,
        metadata_durable: true,
        ..Default::default()
    };
    let outcome = execute::command_outcome(&rejected, json!({"command":"original"}));
    assert_eq!(outcome.category, Category::DomainError);
    assert!(outcome.outcome_known);
    for outcome in [
        t::CommandOutcome::Unknown,
        t::CommandOutcome::RecoveryRequired,
        t::CommandOutcome::Expired,
        t::CommandOutcome::InProgress,
    ] {
        let value = t::CommandInspection {
            outcome: outcome as i32,
            ..Default::default()
        };
        assert!(!execute::command_outcome(&value, json!({})).outcome_known);
    }
    assert!(
        !execute::state_outcome(c::StateOperationDisposition::Unknown as i32, json!({}))
            .outcome_known
    );
}
#[test]
fn human_and_json_projection_keep_exact_retention_source_and_cleanup_facts() {
    let value = t::CommandInspection {
        outcome: t::CommandOutcome::Rejected as i32,
        metadata_durable: true,
        application_state_committed: false,
        source: Some(t::SourceIdentity {
            publication_id: publication(),
            route_generation: u64::MAX,
            component_digest: "component".into(),
            release_digest: "release".into(),
            ..Default::default()
        }),
        retention: Some(t::LinkedRetention {
            record_format: "old-result".into(),
            record_version: 1,
            payload_expires_at_unix_millis: Some(u64::MAX),
            identity_expires_at_unix_millis: Some(u64::MAX),
            remaining_recovery_millis: Some(u64::MAX),
            ..Default::default()
        }),
        cleanup_failure: Some(latent_rpc::invocation::v1::PlatformError {
            code: "cancelled".into(),
            message: "safe cleanup fact".into(),
            ..Default::default()
        }),
        ..Default::default()
    };
    let data = projection::command(&value);
    assert_eq!(data["source"]["routeGeneration"], u64::MAX.to_string());
    assert_eq!(
        data["retention"]["remainingRecoveryMillis"],
        u64::MAX.to_string()
    );
    assert_eq!(data["metadataDurable"], true);
    assert_eq!(data["applicationStateCommitted"], false);
    assert_eq!(data["provenAbort"], serde_json::Value::Null);
    assert_eq!(data["source"]["componentDigest"], "component");
    assert_eq!(data["source"]["releaseDigest"], "release");
    assert_eq!(data["cleanupFailure"]["code"], "cancelled");
}
#[test]
fn command_name_and_offline_preflight_do_not_contact_a_node() {
    let cli = Cli::try_parse_from([
        "latent",
        "state",
        "inspect",
        "--namespace",
        "app",
        "--incarnation",
        "01",
        "--authorization-publication",
        &publication(),
    ])
    .unwrap();
    assert!(cli.validate().is_err());
    let Command::State(command) = cli.command else {
        panic!("state");
    };
    assert_eq!(command.name(), "state inspect");
}
