use super::*;
use std::path::Path;

fn arguments(action: &str, root: &Path) -> Vec<String> {
    [
        "latent",
        "--phase4",
        "transaction",
        action,
        "--namespace",
        "app",
        "--incarnation",
        "9007199254740993",
        "--service",
        "examples/draft",
        "--contract",
        "examples:draft/api@1.0.0",
        "--function",
        if action == "query" { "query" } else { "save" },
        "--route",
        "configured",
        "--input",
        root.join("payload.json").to_str().unwrap(),
        "--budget",
        root.join("budget.json").to_str().unwrap(),
    ]
    .into_iter()
    .map(str::to_owned)
    .collect()
}

fn prepare(arguments: Vec<String>) -> Result<Box<Request>, Failure> {
    let cli = Cli::try_parse_from(arguments).unwrap();
    assert!(cli.phase4);
    cli.validate()?;
    let Command::Transaction(command) = cli.command else {
        panic!("expected transaction command");
    };
    let Operation::Phase4(request) = prepare_transaction(&command, &config())? else {
        panic!("expected Phase 4 request");
    };
    Ok(request)
}

#[test]
fn prepared_cli_command_uses_the_original_input_version_and_abort_proof() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("payload.json"), br#"["test-payload"]"#).unwrap();
    std::fs::write(
        root.path().join("budget.json"),
        br#"{"stateReadBytes":4096,"stateWriteBytes":2048,"effectCount":2}"#,
    )
    .unwrap();
    let versions = root.path().join("versions.json");
    std::fs::write(
        &versions,
        br#"[{"key":"YQ==","version":"AQ=="},{"key":"Yg==","absent":true}]"#,
    )
    .unwrap();
    let retry = root.path().join("retry.json");
    std::fs::write(&retry,
        br#"{"requestId":"repeat","expectedAbort":{"commandId":"command","attemptId":"attempt","transactionId":"transaction","ownerFence":"AQ=="}}"#,
    ).unwrap();
    let mut command = arguments("invoke", root.path());
    command.extend(
        [
            "--client-key",
            "original",
            "--entity",
            "fixed",
            "--shared-recovery-scope",
            "shared",
            "--expected-versions",
            versions.to_str().unwrap(),
            "--retry-attempt",
            retry.to_str().unwrap(),
        ]
        .into_iter()
        .map(str::to_owned),
    );
    let request = prepare(command.clone()).unwrap();
    let Request::InvokeCommand(value) = request.as_ref() else {
        panic!("expected invocation")
    };
    let invocation = value.invocation.as_ref().unwrap();
    assert_eq!(invocation.payload, br#"["test-payload"]"#);
    assert_eq!(invocation.target.as_ref().unwrap().tenant, "tenant");
    let selector = value.command.as_ref().unwrap();
    assert_eq!(
        selector.namespace.as_ref().unwrap().incarnation,
        "9007199254740993"
    );
    assert_eq!(selector.operation, "save");
    assert_eq!(selector.client_key, "original");
    assert_eq!(selector.entity.as_deref(), Some("fixed"));
    assert_eq!(selector.shared_recovery_scope.as_deref(), Some("shared"));
    assert_eq!(value.expected_versions[0].key, b"a");
    assert_eq!(
        value.expected_versions[0].expectation,
        Some(t::expected_version::Expectation::Version(vec![1]))
    );
    assert_eq!(
        value.expected_versions[1].expectation,
        Some(t::expected_version::Expectation::Absent(true))
    );
    assert_eq!(
        value
            .retry_attempt
            .as_ref()
            .unwrap()
            .expected_abort
            .as_ref()
            .unwrap()
            .owner_fence,
        [1]
    );
    let recovery = recovery(&request).unwrap();
    assert_eq!(recovery["command"]["clientKey"], "original");
    assert_eq!(recovery["target"]["route"], "configured");
    assert_eq!(recovery["expectedVersionCount"], 2);
    assert_eq!(recovery["automaticRetry"], false);
    assert!(!recovery.to_string().contains("test-payload"));

    std::fs::write(
        &versions,
        br#"[{"key":"YQ==","absent":true},{"key":"YQ==","version":"AQ=="}]"#,
    )
    .unwrap();
    assert!(prepare(command).is_err());
}

#[test]
fn fresh_query_preserves_the_minimum_view_and_refuses_mutating_bounds() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("payload.json"), b"[]").unwrap();
    let budget = root.path().join("budget.json");
    std::fs::write(&budget, br#"{"stateReadBytes":4096}"#).unwrap();
    let mut command = arguments("query", root.path());
    command.extend(["--minimum-view-version".into(), "AQ==".into()]);
    let request = prepare(command.clone()).unwrap();
    let Request::Query(value) = request.as_ref() else {
        panic!("expected query")
    };
    assert_eq!(value.minimum_view_version, Some(vec![1]));
    assert_eq!(value.namespace.as_ref().unwrap().tenant, "tenant");
    let invocation = value.invocation.as_ref().unwrap();
    assert_eq!(invocation.target.as_ref().unwrap().function, "query");
    assert_eq!(invocation.budget.as_ref().unwrap().state_write_bytes, 0);
    assert!(recovery(&request).is_none());

    std::fs::write(&budget, br#"{"stateReadBytes":4096,"effectCount":1}"#).unwrap();
    assert!(prepare(command).is_err());
}

#[test]
fn direct_submission_reports_the_invocation_status_and_command_certainty() {
    use crate::output::Category;
    use latent_rpc::{invocation::v1 as i, phase4::Response, transaction::v1 as t};

    let failure = i::PlatformError {
        code: "unavailable".into(),
        message: "original result requires lookup".into(),
        ..Default::default()
    };
    let invocation = i::InvokeResponse {
        result: Some(i::invoke_response::Result::PlatformFailure(failure)),
        ..Default::default()
    };
    let query = Response::from(t::QueryResponse {
        invocation: Some(invocation.clone()),
        ..Default::default()
    });
    let outcome = super::execute::project_outcome(&query);
    assert_eq!(outcome.category, Category::PlatformError);
    assert!(outcome.outcome_known);
    assert_eq!(
        outcome.data["invocation"]["result"]["kind"],
        "technical-failure"
    );

    let command = Response::from(t::InvokeCommandResponse {
        invocation: Some(invocation),
        command: Some(t::CommandInspection {
            outcome: t::CommandOutcome::Unknown as i32,
            ..Default::default()
        }),
        ..Default::default()
    });
    let outcome = super::execute::project_outcome(&command);
    assert_eq!(outcome.category, Category::PlatformError);
    assert!(!outcome.outcome_known);

    let query = Response::from(t::QueryResponse {
        invocation: Some(i::InvokeResponse {
            result: Some(i::invoke_response::Result::DeclaredError(
                i::DeclaredError::default(),
            )),
            ..Default::default()
        }),
        ..Default::default()
    });
    let outcome = super::execute::project_outcome(&query);
    assert_eq!(outcome.category, Category::DomainError);
    assert!(outcome.outcome_known);
}
