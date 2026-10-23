//! Offline commands use the durable journal's own effective-UID and exclusive
//! filesystem checks. RPC credentials and archive cursors are never authority.
mod projection;
#[cfg(all(test, target_os = "linux"))]
mod tests;

use crate::{args::{audit::{maintenance::{ArchiveCommand, MaintenanceCommand}, AuditCommand, Scope}, Cli},
    error::Failure, output::Outcome};
use latent_audit::{AuditCursor, AuditFilter, AuditMaintenance, AuditQueryRequest, AuditScope};
use latent_core::{PlatformError, TenantId};
use serde_json::{json, Value};

pub fn execute(cli: &Cli, command: &AuditCommand) -> Outcome {
    let (result, mutation, recovery) = match command {
        AuditCommand::Maintenance(command) => (maintenance(command), command.mutation(), recovery(command)),
        AuditCommand::Archive(command) => (archive(command, cli.tenant.as_deref()), false, Value::Null),
        AuditCommand::Query(_) => return Failure::local("invalid-audit-maintenance-input", "Live audit queries require the authenticated RPC path.").into(),
    };
    let mut outcome = match result {
        Ok(data) => Outcome::success(data),
        Err(error) => {
            let (reason, step) = diagnostic(&error.message);
            let mut result = Outcome::platform_failure(json!({"reason":reason,"nextStep":step}), &error);
            // Once the local maintenance owner was invoked, a missing final
            // receipt is not proof that an epoch or transfer did not commit.
            result.outcome_known = !mutation;
            result
        }
    };
    outcome.data["authorization"] = json!("effective-uid-private-filesystem-owner");
    outcome.data["localOperationInvoked"] = json!(true);
    outcome.data["reservation"] = json!(false);
    outcome.data["executionPermission"] = json!(false);
    outcome.data["historyComplete"] = json!(false);
    outcome.data["previousSessionLossUnknown"] = json!(true);
    if !recovery.is_null() { outcome.data["recovery"] = recovery; }
    outcome
}

fn maintenance(command: &MaintenanceCommand) -> Result<Value, PlatformError> {
    match command {
        MaintenanceCommand::Status(args) => AuditMaintenance::status(&args.journal, args.local.timeout()).map(projection::status),
        MaintenanceCommand::Custody(args) => AuditMaintenance::custody_status(&args.archives, &args.journal_id, args.local.timeout()).map(projection::custody),
        MaintenanceCommand::Rollover(args) => AuditMaintenance::rollover(&args.journal.journal, &args.archives,
            &args.expected_epoch, &args.operation_id, args.journal.local.timeout()).map(projection::rollover),
        MaintenanceCommand::Transfer(args) => AuditMaintenance::transfer(&args.journal.journal, &args.archives,
            &args.destination, &args.epoch, &args.expected_seal, &args.operation_id, args.journal.local.timeout()).map(projection::transfer),
    }
}
fn archive(command: &ArchiveCommand, tenant: Option<&str>) -> Result<Value, PlatformError> {
    match command {
        ArchiveCommand::Verify(args) => AuditMaintenance::verify_archive(&args.archive, &args.epoch, args.local.timeout())
            .map(|coverage| json!({"archive":projection::coverage(coverage),"verified":true})),
        ArchiveCommand::Query(args) => {
            let scope = match args.scope {
                Scope::Tenant => AuditScope::Tenant(TenantId(tenant.ok_or_else(invalid)?.into())),
                Scope::Node => AuditScope::Node,
            };
            let query = AuditQueryRequest { scope, filter: AuditFilter { kind: None, actor: args.actor.clone(),
                from_unix_millis: args.from_unix_millis, to_unix_millis: args.to_unix_millis },
                cursor: args.page_token.clone().map(AuditCursor), limit: args.page_size as usize,
                maximum_bytes: args.maximum_bytes as usize };
            let page = AuditMaintenance::query_archive(&args.archive.archive, &args.archive.epoch, &query, args.archive.local.timeout())?;
            projection::page(page)
        }
    }
}
fn recovery(command: &MaintenanceCommand) -> Value {
    match command {
        MaintenanceCommand::Rollover(args) => json!({"family":"audit-rollover","operationId":args.operation_id,"expectedEpoch":args.expected_epoch}),
        MaintenanceCommand::Transfer(args) => json!({"family":"audit-transfer","operationId":args.operation_id,"epoch":args.epoch,"expectedSeal":args.expected_seal}),
        _ => Value::Null,
    }
}
fn invalid() -> PlatformError {
    PlatformError { code: latent_core::PlatformErrorCode::InvalidArgument, message: "audit-invalid".into(), retryable: false, details: Vec::new() }
}
fn diagnostic(reason: &str) -> (&'static str, &'static str) {
    match reason {
        "audit-archive-capacity" => ("audit-archive-capacity", "transfer-oldest-archive-to-verified-operator-custody"),
        "audit-critical-pending" => ("audit-critical-pending", "restart-original-node-and-reconcile-original-operation-without-replay"),
        "audit-maintenance-reopen-required" => ("audit-maintenance-reopen-required", "restart-original-node-for-ordinary-append-recovery-before-maintenance"),
        "audit-maintenance-resume-required" => ("audit-maintenance-resume-required", "resume-original-maintenance-command-with-unchanged-identities-and-paths"),
        "audit-maintenance-identity-mismatch" => ("audit-maintenance-identity-mismatch", "use-original-operation-identities-and-destination"),
        "audit-maintenance-epoch-mismatch" => ("audit-maintenance-epoch-mismatch", "inspect-current-epoch-and-original-maintenance-receipt"),
        "audit-oldest-archive-required" => ("audit-oldest-archive-required", "inspect-verified-custody-and-select-its-oldest-retained-epoch"),
        "audit-empty-epoch" => ("audit-empty-epoch", "inspect-current-epoch-no-rollover-needed"),
        "audit-maintenance-deadline" => ("audit-maintenance-deadline", "resume-original-maintenance-command-after-physical-owner-exits"),
        "audit-maintenance-platform-unsupported" => ("audit-maintenance-platform-unsupported", "run-on-the-supported-linux-node-as-its-filesystem-owner"),
        "audit-corrupt" => ("audit-corrupt", "preserve-all-history-and-inspect-integrity-no-destructive-cleanup"),
        "audit-invalid" => ("audit-invalid", "check-explicit-epoch-scope-cursor-and-bounded-operation-selectors"),
        "audit-archive-custody-unavailable" => ("audit-archive-custody-unavailable", "restore-the-original-archive-custody-before-resuming"),
        _ => ("audit-storage-or-owner-unavailable", "stop-node-and-confirm-original-private-storage-and-exclusive-ownership"),
    }
}
