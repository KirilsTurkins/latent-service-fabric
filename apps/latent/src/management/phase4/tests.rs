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
mod effect_management;

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

#[test]
fn typed_dispatcher_recovery_and_effect_plan_projection_keep_original_association_losslessly() {
    let audit = Some(c::AuditAck {
        status: c::AuditAckStatus::Durable as i32,
        attempt_sequence: Some(u64::MAX),
    });
    let (original, request) = dispatcher_recovery_request();
    assert_dispatcher_operation_projection(&original, &request, audit);
    assert_effect_plan_projection(audit);

    let Operation::Phase4(request) = prepare_state(
        &StateCommand::Operation(NamespaceOperationArgs {
            target: target(),
            operation_id: "original-namespace".into(),
        }),
        &config(),
    )
    .unwrap() else {
        panic!("namespace lookup")
    };
    let Request::GetStateOperationReceipt(value) = *request else {
        panic!("typed lookup")
    };
    assert_eq!(value.operation_id, "original-namespace");
    assert!(value.original_effect_plan.is_none());
}

fn dispatcher_recovery_request() -> (c::ControlDispatcherRequest, Request) {
    use latent_rpc::phase4::current_profile;

    let original = c::ControlDispatcherRequest {
        profile: Some(current_profile()),
        scope: c::DispatcherScope::Node as i32,
        operation_id: "original-resume".into(),
        action: c::DispatcherAction::Resume as i32,
        expected_generation: Some(c::DispatcherGeneration {
            owner_epoch: 9_007_199_254_740_993,
            revision: u64::MAX - 1,
        }),
    };
    let request = Request::from(original.clone());
    request.validate().unwrap();
    let context = recovery(&request).unwrap();
    assert_eq!(context["operationId"], "original-resume");
    assert_eq!(context["action"], "DISPATCHER_ACTION_RESUME");
    assert_eq!(context["automaticRetry"], false);
    assert_eq!(
        context["expectedGeneration"]["ownerEpoch"],
        "9007199254740993"
    );
    assert_eq!(
        context["expectedGeneration"]["revision"],
        (u64::MAX - 1).to_string()
    );
    let mut failure = Failure::protocol("response-lost", "original transport lost");
    super::super::phase2::RecoveryContext::from_operation(
        &Operation::Phase4(Box::new(request.clone())),
        "tenant",
    )
    .failure(&mut failure);
    let mut expected_context = context.clone();
    expected_context["tenant"] = json!("tenant");
    assert_eq!(failure.data["recovery"], expected_context);
    assert!(!failure.outcome_known);
    (original, request)
}

fn assert_dispatcher_operation_projection(
    original: &c::ControlDispatcherRequest,
    request: &Request,
    audit: Option<c::AuditAck>,
) {
    use latent_rpc::phase4::{current_profile, Response};

    let receipt = c::DispatcherOperationReceipt {
        operation_id: original.operation_id.clone(),
        receipt_id: "exact-receipt".into(),
        action: original.action,
        authenticated_operator: "host-derived-stable-actor".into(),
        actor_tenant: "tenant".into(),
        before_generation: original.expected_generation,
        after_generation: Some(c::DispatcherGeneration {
            owner_epoch: 9_007_199_254_740_993,
            revision: u64::MAX,
        }),
        observed_at_unix_millis: u64::MAX,
        clock_continuity_proven: true,
        restore_review_required: false,
        disposition: c::StateOperationDisposition::Committed as i32,
    };
    let response = Response::from(c::ControlDispatcherResponse {
        receipt: Some(receipt.clone()),
        replayed: true,
        published: false,
        paused: true,
        audit_ack: audit,
    });
    response.validate_for(request).unwrap();
    let outcome = execute::project_outcome(&response);
    assert_eq!(outcome.category, Category::Success);
    assert!(outcome.outcome_known);
    assert_eq!(outcome.data["receipt"]["operationId"], "original-resume");
    assert_eq!(
        outcome.data["receipt"]["afterGeneration"]["revision"],
        u64::MAX.to_string()
    );
    assert_eq!(outcome.data["published"], false);
    let lookup = Request::from(c::GetDispatcherOperationRequest {
        original: Some(original.clone()),
    });
    let response = Response::from(c::GetDispatcherOperationResponse {
        receipt: Some(receipt.clone()),
        audit_ack: audit,
    });
    response.validate_for(&lookup).unwrap();
    assert_eq!(
        projection::response(&response)["receipt"]["observedAtUnixMillis"],
        u64::MAX.to_string()
    );
    let mut changed = original.clone();
    changed.operation_id = "replacement-resume".into();
    assert!(response
        .validate_for(&Request::from(c::GetDispatcherOperationRequest {
            original: Some(changed)
        }))
        .is_err());
    let inspect = Request::from(c::InspectDispatcherRequest {
        profile: Some(current_profile()),
        scope: c::DispatcherScope::Node as i32,
    });
    let response = Response::from(c::InspectDispatcherResponse {
        dispatcher: Some(c::DispatcherSnapshot {
            generation: original.expected_generation,
            paused: true,
            pending_control: true,
            retained_attempt_bytes: u64::MAX,
            counts_observed_at_unix_millis: u64::MAX,
            failure: c::DispatcherFailure::None as i32,
            ..Default::default()
        }),
        audit_ack: audit,
    });
    response.validate_for(&inspect).unwrap();
    assert_eq!(
        projection::response(&response)["dispatcher"]["retainedAttemptBytes"],
        u64::MAX.to_string()
    );
}

fn assert_effect_plan_projection(audit: Option<c::AuditAck>) {
    use base64::{engine::general_purpose::STANDARD, Engine};
    use latent_rpc::phase4::Response;
    use prost::Message;

    let Operation::Phase4(effect) = prepare_transaction(
        &TransactionCommand::Effect(EffectArgs {
            command: command(),
            effect_id: "b".repeat(64),
        }),
        &config(),
    )
    .unwrap() else {
        panic!("effect request")
    };
    let Request::GetEffect(effect) = *effect else {
        panic!("typed effect")
    };
    let original_plan = c::PlanEffectMutationRequest {
        effect: Some(*effect),
        operation_id: "original-effect-stop".into(),
        mutation: c::StateMutationKind::TerminateEffect as i32,
        expected_version: vec![1; 32],
        expected_policy_digest: format!("sha256:{}", "c".repeat(64)),
        reason: "operator reviewed original unknown attempt".into(),
        retry_delay_millis: 0,
    };
    let plan = c::EffectManagementPlan {
        original: Some(original_plan.clone()),
        plan_digest: vec![2; 32],
        management_sequence: 128,
        owner_epoch: u64::MAX,
        claim_generation: 9_007_199_254_740_993,
        dispatch_attempt: 2,
        prepared_at_unix_millis: 10,
        expires_at_unix_millis: 20,
        before: t::EffectDisposition::UncertainAfterDispatch as i32,
        safety: c::EffectPlanSafety::AdministratorDeclared as i32,
        dedup_valid_until_unix_millis: None,
    };
    let request = Request::from(original_plan.clone());
    request.validate().unwrap();
    let response = Response::from(c::PlanEffectMutationResponse {
        plan: Some(plan.clone()),
        replayed: true,
        audit_ack: audit,
    });
    response.validate_for(&request).unwrap();
    let data = projection::response(&response);
    assert_eq!(
        data["plan"]["original"]["operationId"],
        "original-effect-stop"
    );
    assert_eq!(data["plan"]["ownerEpoch"], u64::MAX.to_string());
    assert_eq!(data["plan"]["claimGeneration"], "9007199254740993");
    assert_eq!(
        data["plan"]["encodedPlan"]["data"],
        STANDARD.encode(plan.encode_to_vec())
    );
    let mut changed = original_plan;
    changed.operation_id = "replacement-stop".into();
    assert!(response.validate_for(&Request::from(changed)).is_err());
}
