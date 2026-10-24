use super::*;
use crate::{args::Command, output::Category};
use clap::Parser;
use latent_audit::{
    AuditActorIdentity, AuditActorKind, AuditControlAction, AuditIdentities, AuditLimits,
    AuditOperationAttempt, AuditOperationConclusion, AuditOperationResult, AuditReason,
    DirectoryPhase2AuditJournal,
};
use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
    time::{Duration, Instant},
};

struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "latent-cli-audit-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).unwrap();
        Self(path)
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        if !std::thread::panicking() {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }
}
fn text(path: &Path) -> &str {
    path.to_str().unwrap()
}
fn run(args: &[&str]) -> Outcome {
    let cli = Cli::try_parse_from(
        ["latent", "--output", "json"]
            .into_iter()
            .chain(args.iter().copied()),
    )
    .unwrap();
    cli.validate().unwrap();
    let Command::Audit(command) = &cli.command else {
        panic!("audit command required");
    };
    execute(&cli, command)
}
fn fill(root: &Path) {
    let limits = AuditLimits {
        maximum_records: 2,
        ..AuditLimits::default()
    };
    let (handle, mut worker) = DirectoryPhase2AuditJournal::open(root, limits).unwrap();
    let digest: latent_core::ArtifactBlobDigest =
        format!("sha256:{}", "a".repeat(64)).parse().unwrap();
    let attempt = AuditOperationAttempt {
        expected_state_version: None,
        expected_rollback_target_generation: None,
        scope: AuditScope::Tenant(TenantId("test".into())),
        actor: AuditActorIdentity {
            kind: AuditActorKind::Host,
            subject: "operator".into(),
        },
        operation_id: "native-cli-fixture".into(),
        request_digest: digest.clone(),
        preview_receipt_digest: Some(digest.clone()),
        action: AuditControlAction::Publish,
        identities: AuditIdentities::default(),
        replay: false,
        expected_generation: Some(0),
        expected_deployment_generation: None,
        expected_rollout_revision: None,
        occurred_at_unix_millis: 1,
    };
    let mut pending = handle
        .reserve_control_critical(&attempt)
        .unwrap()
        .begin()
        .blocking_wait()
        .unwrap();
    pending.mutation_started().unwrap();
    pending
        .finish(AuditOperationConclusion {
            canary_decision: None,
            result: AuditOperationResult::Committed,
            reason: AuditReason::Committed,
            receipt_digest: Some(digest),
            identities: AuditIdentities::default(),
            replay: false,
            occurred_at_unix_millis: u64::MAX,
        })
        .blocking_wait()
        .unwrap();
    handle.close();
    assert!(worker
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}
fn status(root: &Path) -> Value {
    let outcome = run(&[
        "audit",
        "maintenance",
        "status",
        "--journal",
        text(root),
        "--local-operator",
    ]);
    assert_eq!(outcome.category, Category::Success);
    assert!(!outcome.request_dispatched);
    assert_eq!(
        outcome.data["authorization"],
        "effective-uid-private-filesystem-owner"
    );
    assert_eq!(outcome.data["historyComplete"], false);
    assert_eq!(outcome.data["reservation"], false);
    outcome.data
}
fn roll(root: &Path, archives: &Path, epoch: &str, operation: &str) -> Value {
    let result = run(&[
        "audit",
        "maintenance",
        "rollover",
        "--journal",
        text(root),
        "--archives",
        text(archives),
        "--expected-epoch",
        epoch,
        "--operation-id",
        operation,
        "--local-operator",
    ]);
    assert_eq!(result.category, Category::Success, "{result:?}");
    assert!(result.outcome_known);
    assert_eq!(result.data["durability"], "confirmed");
    assert_eq!(result.data["recovery"]["operationId"], operation);
    result.data
}
fn verify(archive: &Path, epoch: &str) -> Outcome {
    run(&[
        "audit",
        "archive",
        "verify",
        "--archive",
        text(archive),
        "--epoch",
        epoch,
        "--local-operator",
    ])
}
fn query(archive: &Path, epoch: &str, tenant: &str, cursor: Option<&str>) -> Outcome {
    let mut args = vec![
        "--tenant",
        tenant,
        "audit",
        "archive",
        "query",
        "--archive",
        text(archive),
        "--epoch",
        epoch,
        "--scope",
        "tenant",
        "--page-size",
        "1",
        "--local-operator",
    ];
    if let Some(cursor) = cursor {
        args.extend(["--page-token", cursor]);
    }
    run(&args)
}
fn custody(archives: &Path, journal: &str) -> Value {
    let result = run(&[
        "audit",
        "maintenance",
        "custody",
        "--archives",
        text(archives),
        "--journal-id",
        journal,
        "--local-operator",
    ]);
    assert_eq!(result.category, Category::Success);
    result.data
}
fn verify_archive_pages(archives: &Path, first_epoch: &str, second_epoch: &str) {
    let archive = archives.join(first_epoch);
    let verified = verify(&archive, first_epoch);
    assert_eq!(verified.category, Category::Success);
    assert_eq!(verified.data["archive"]["records"], "2");
    let page = query(&archive, first_epoch, "test", None);
    assert_eq!(page.category, Category::Success);
    assert_eq!(page.data["records"][0]["sequence"], "1");
    let cursor = page.data["nextPageToken"].as_str().unwrap();
    let second_page = query(&archive, first_epoch, "test", Some(cursor));
    assert_eq!(second_page.category, Category::Success);
    assert_eq!(second_page.data["records"][0]["sequence"], "2");
    assert!(second_page.data["records"]
        .to_string()
        .contains("18446744073709551615"));
    assert!(second_page.data["nextPageToken"].is_null());
    let wrong_epoch = query(
        &archives.join(second_epoch),
        second_epoch,
        "test",
        Some(cursor),
    );
    assert_eq!(wrong_epoch.category, Category::PlatformError);
    let foreign_scope = query(&archive, first_epoch, "another", None);
    assert_eq!(foreign_scope.category, Category::Success);
    assert_eq!(foreign_scope.data["records"], json!([]));
}

#[test]
fn native_operator_workflow_rolls_multiple_epochs_queries_and_transfers_exact_history() {
    let directory = Directory::new();
    let root = directory.0.join("active");
    let archives = directory.0.join("archives");
    let destination = directory.0.join("off-node-custody");
    fill(&root);
    let initial = status(&root);
    assert_eq!(initial["retainedRecords"], "2");
    let first_epoch = initial["epoch"].as_str().unwrap();
    let first = roll(&root, &archives, first_epoch, &"1".repeat(32));
    assert_eq!(first["receipt"]["nextSequence"], "3");
    let retry = roll(&root, &archives, first_epoch, &"1".repeat(32));
    assert_eq!(retry["alreadyCompleted"], true);
    assert_eq!(first["receipt"], retry["receipt"]);
    assert_eq!(status(&root)["retainedFloor"], "3");
    fill(&root);
    let second_epoch = status(&root)["epoch"].as_str().unwrap().to_owned();
    let second = roll(&root, &archives, &second_epoch, &"2".repeat(32));
    assert_eq!(second["receipt"]["nextSequence"], "5");
    verify_archive_pages(&archives, first_epoch, &second_epoch);
    let retained = custody(&archives, first_epoch);
    assert_eq!(retained["archives"].as_array().unwrap().len(), 2);
    assert_eq!(retained["transferredThrough"], "0");
    let seal = first["receipt"]["archiveSeal"].as_str().unwrap();
    let transfer = run(&[
        "audit",
        "maintenance",
        "transfer",
        "--journal",
        text(&root),
        "--archives",
        text(&archives),
        "--destination",
        text(&destination),
        "--epoch",
        first_epoch,
        "--expected-seal",
        seal,
        "--operation-id",
        &"f".repeat(32),
        "--local-operator",
    ]);
    assert_eq!(transfer.category, Category::Success);
    assert_eq!(transfer.data["receipt"]["transferredThrough"], "2");
    assert!(!archives.join(first_epoch).exists());
    let retained = custody(&archives, first_epoch);
    assert_eq!(retained["archives"].as_array().unwrap().len(), 1);
    assert_eq!(retained["transferredThrough"], "2");
    assert_eq!(
        retained["transferredHistoryAvailability"],
        "not-observed"
    );
    assert_eq!(verify(&destination, first_epoch).category, Category::Success);
    assert_eq!(status(&root)["nextSequence"], "5");
}

#[test]
fn offline_grammar_rejects_rpc_credentials_implicit_scope_and_unbounded_selectors() {
    let base = [
        "latent",
        "audit",
        "maintenance",
        "status",
        "--journal",
        "/not-opened",
        "--local-operator",
    ];
    for suffix in [
        vec!["--profile", "operator"],
        vec!["--config", "/never-read.json"],
        vec!["--endpoint", "http://127.0.0.1:1"],
        vec!["--tenant", "test"],
        vec!["--connect-timeout-ms", "1"],
        vec!["--rpc-timeout-ms", "1"],
        vec!["--phase4"],
    ] {
        let cli = Cli::try_parse_from(base.into_iter().chain(suffix)).unwrap();
        assert!(cli.validate().is_err());
    }
    assert!(Cli::try_parse_from([
        "latent",
        "audit",
        "maintenance",
        "status",
        "--journal",
        "/not-opened"
    ])
    .is_err());
    let epoch = "a".repeat(32);
    let query = [
        "latent",
        "audit",
        "archive",
        "query",
        "--archive",
        "/not-opened",
        "--epoch",
        &epoch,
        "--scope",
        "tenant",
        "--local-operator",
    ];
    assert!(Cli::try_parse_from(query).unwrap().validate().is_err());
    for suffix in [
        vec!["--deadline-seconds", "0"],
        vec!["--deadline-seconds", "121"],
        vec!["--page-size", "0"],
        vec!["--page-size", "129"],
        vec!["--maximum-bytes", "262145"],
    ] {
        assert!(Cli::try_parse_from(query.into_iter().chain(suffix)).is_err());
    }
    let cli = Cli::try_parse_from([
        "latent",
        "audit",
        "maintenance",
        "rollover",
        "--journal",
        "/not-opened",
        "--archives",
        "/never-created",
        "--expected-epoch",
        &epoch,
        "--operation-id",
        "not-an-id",
        "--local-operator",
    ])
    .unwrap();
    assert!(cli.validate().is_err());
}

#[test]
fn missing_and_unsafe_roots_are_never_initialized_and_errors_preserve_uncertainty() {
    let directory = Directory::new();
    let missing = directory.0.join("missing");
    let archives = directory.0.join("archives");
    let status = run(&[
        "audit",
        "maintenance",
        "status",
        "--journal",
        text(&missing),
        "--local-operator",
    ]);
    assert_eq!(status.category, Category::PlatformError);
    assert!(status.outcome_known);
    assert!(!missing.exists());
    let operation = "a".repeat(32);
    let rollover = run(&[
        "audit",
        "maintenance",
        "rollover",
        "--journal",
        text(&missing),
        "--archives",
        text(&archives),
        "--expected-epoch",
        &operation,
        "--operation-id",
        &operation,
        "--local-operator",
    ]);
    assert_eq!(rollover.category, Category::PlatformError);
    assert!(!rollover.outcome_known);
    assert_eq!(rollover.data["recovery"]["operationId"], operation);
    assert!(!missing.exists());
    assert!(!archives.exists());
    assert!(!rollover
        .document("audit maintenance rollover")
        .to_string()
        .contains(text(&directory.0)));
    fill(&missing);
    fs::set_permissions(&missing, fs::Permissions::from_mode(0o755)).unwrap();
    let rejected = run(&[
        "audit",
        "maintenance",
        "status",
        "--journal",
        text(&missing),
        "--local-operator",
    ]);
    assert_eq!(rejected.category, Category::PlatformError);
    fs::set_permissions(&missing, fs::Permissions::from_mode(0o700)).unwrap();
}
