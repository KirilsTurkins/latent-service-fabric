//! One finite offline action and positive retirement on the original owner.
use super::{
    assets,
    codecs::Codecs,
    failure::Failure,
    request::{Action, File},
};
use latent_state::{
    protected_store::{ProtectedStoreConfig, ProtectedStoreError},
    recovery::{
        migration::{AggregateMigrationProgress, AggregateMigrationRequest},
        offline::{
            OfflineAggregateMigrationRequest, OfflineRecoveryError, OfflineRecoverySource,
            OfflineRestoreRequest, RecoveryCodecs, RecoveryReviewRequest, SnapshotFile,
        },
        restore::RestoreRequest,
        resume::{NamespaceRecoveryView, NamespaceResumeRequest},
        snapshot::{SnapshotMetadata, SnapshotReceipt},
    },
};
use serde::Serialize;
use std::{sync::Arc, time::Instant};

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRecoveryReport {
    schema_version: &'static str,
    operation_succeeded: bool,
    failure: Option<OfflineFailure>,
    result: Option<serde_json::Value>,
    retirement: Option<Retirement>,
    catalogs_retired: Option<bool>,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Retirement {
    clean: bool,
    physically_retired: bool,
    live_workers: usize,
    accepted_jobs: usize,
    threads_joined: Option<usize>,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase", tag = "stage", content = "failure")]
enum OfflineFailure {
    Configuration,
    Busy,
    Destination,
    Input(Failure),
    Review(Failure),
    Target(Failure),
    Protected(Failure),
}
impl NativeRecoveryReport {
    /// Catalog retirement is separate from the original action disposition.
    pub(in crate::standalone) fn catalogs_retired(&mut self, clean: bool) {
        self.catalogs_retired = Some(clean);
    }
}
impl From<OfflineRecoveryError> for OfflineFailure {
    fn from(error: OfflineRecoveryError) -> Self {
        match error {
            OfflineRecoveryError::InvalidConfiguration => Self::Configuration,
            OfflineRecoveryError::Busy => Self::Busy,
            OfflineRecoveryError::UnsafeDestination => Self::Destination,
            OfflineRecoveryError::Input(error) => Self::Input(error.into()),
            OfflineRecoveryError::Review(error) => Self::Review(error.into()),
            OfflineRecoveryError::Target(error) => Self::Target(error.into()),
            OfflineRecoveryError::Protected(error) => Self::Protected(error.into()),
        }
    }
}
pub(super) async fn execute(
    config: ProtectedStoreConfig,
    codecs: Arc<Codecs>,
    grace: std::time::Duration,
) -> NativeRecoveryReport {
    let mut report = NativeRecoveryReport {
        schema_version: "latent.native-transaction-recovery.v1",
        operation_succeeded: false,
        failure: None,
        result: None,
        retirement: None,
        catalogs_retired: None,
    };
    let tenant = codecs.catalog.primary().operation.target().tenant.0.clone();
    let installed: Arc<dyn RecoveryCodecs> = codecs.clone();
    let startup = if codecs.action.reviewed_open() {
        OfflineRecoverySource::start_review(config, tenant, installed)
    } else {
        OfflineRecoverySource::start(config, tenant, installed)
    };
    let mut startup = match startup {
        Ok(startup) => startup,
        Err(error) => {
            report.failure = Some(error.into());
            return report;
        }
    };
    let source = match (&mut startup).await {
        Ok(source) => source,
        Err(error) => {
            report.failure = Some(error.into());
            startup.close();
            let cutoff = Instant::now() + grace;
            if let Ok(drain) = startup.drain_async(cutoff, tokio::time::sleep_until(cutoff.into()))
            {
                let retired = drain.await;
                report.retirement = Some(retirement(
                    retired.clean,
                    retired.snapshot,
                    startup.reap_retired_threads(),
                ));
            }
            return report;
        }
    };
    match operate(&source, &codecs).await {
        Ok(result) => {
            report.operation_succeeded = true;
            report.result = Some(result);
        }
        Err(error) => report.failure = Some(error.into()),
    }
    source.close();
    let cutoff = Instant::now() + grace;
    if let Ok(drain) = source.drain_async(cutoff, tokio::time::sleep_until(cutoff.into())) {
        let retired = drain.await;
        report.retirement = Some(retirement(
            retired.clean,
            retired.snapshot,
            source.reap_retired_threads(),
        ));
    }
    // Codecs and every original authority/publication stay retained until this
    // physical completion. Cleanup failure never erases an operation outcome.
    report
}
fn retirement(
    clean: bool,
    snapshot: latent_state::store_io::StoreIoSnapshot,
    joined: Result<usize, ProtectedStoreError>,
) -> Retirement {
    let physically_retired = snapshot.physically_retired();
    Retirement {
        clean: clean && physically_retired && joined.is_ok(),
        physically_retired,
        live_workers: snapshot.live_workers,
        accepted_jobs: snapshot.accepted,
        threads_joined: joined.ok(),
    }
}
async fn operate(
    source: &OfflineRecoverySource,
    codecs: &Codecs,
) -> Result<serde_json::Value, OfflineRecoveryError> {
    match &codecs.action {
        Action::Snapshot { operation_id, file } => {
            let metadata = SnapshotMetadata {
                tenant: codecs.catalog.primary().operation.target().tenant.0.clone(),
                operation_id: operation_id.clone(),
                operator_id: codecs.authority.actor.clone(),
                runtime_digest: codecs.runtime,
                decoder_formats: codecs.catalog.formats.clone(),
                required_artifacts: codecs.catalog.artifacts.clone(),
            };
            let receipt = source
                .backup_to(snapshot_file(file), metadata, codecs.authority.deadline)?
                .await?;
            Ok(snapshot(&receipt))
        }
        Action::InspectRestore {
            file,
            destination_root,
            operation_id,
            snapshot_digest,
        } => {
            let request = restore_request(
                codecs,
                file,
                destination_root,
                operation_id,
                snapshot_digest,
                [0; 32],
            )?;
            let observed = source
                .inspect_restore(request, codecs.authority.deadline)?
                .await?;
            Ok(
                serde_json::json!({"action":"inspect-restore", "snapshot":snapshot(&observed.snapshot),
                "windowDigest":digest(observed.window.digest().map_err(OfflineRecoveryError::Review)?),
                "window":observed.window}),
            )
        }
        Action::Restore {
            file,
            destination_root,
            operation_id,
            snapshot_digest,
            window_acknowledgement,
        } => {
            let acknowledgement =
                assets::digest_bytes(window_acknowledgement).map_err(|_| invalid())?;
            let request = restore_request(
                codecs,
                file,
                destination_root,
                operation_id,
                snapshot_digest,
                acknowledgement,
            )?;
            let result = source
                .restore_to(request, codecs.authority.deadline)?
                .await?;
            Ok(
                serde_json::json!({"action":"restore", "guard":result.guard.encode().map_err(OfflineRecoveryError::Target)?,
                "snapshotDigest":digest(result.snapshot_digest), "manifestDigest":digest(result.manifest_digest),
                "destinationIdentity":result.destination_identity}),
            )
        }
        _ => metadata_action(source, codecs).await,
    }
}
async fn metadata_action(
    source: &OfflineRecoverySource,
    codecs: &Codecs,
) -> Result<serde_json::Value, OfflineRecoveryError> {
    let operation = &codecs.catalog.primary().operation;
    let observed = source
        .inspect_namespace(
            codecs.authority.actor.clone(),
            latent_core::StateNamespaceId(operation.namespace().into()),
            codecs.authority.deadline,
        )?
        .await?;
    match &codecs.action {
        Action::InspectNamespace => namespace(&observed),
        Action::StageMigration { .. } | Action::CompleteMigration { .. } => {
            migrate(source, codecs, &observed).await
        }
        Action::Review => {
            let request = RecoveryReviewRequest {
                operator_id: codecs.authority.actor.clone(),
                expected_guard: observed.guard.ok_or_else(invalid)?,
                review_digest: codecs.review,
            };
            let guard = source
                .review_reconciliation(request, codecs.authority.deadline)?
                .await?;
            Ok(
                serde_json::json!({"action":"review", "guard":guard.encode().map_err(OfflineRecoveryError::Target)?,
                "reviewDigest":digest(codecs.review)}),
            )
        }
        Action::Resume {
            operation_id,
            expected_view,
        } => {
            let request = NamespaceResumeRequest {
                scope: observed.scope(),
                operation_id: operation_id.clone(),
                operator_id: codecs.authority.actor.clone(),
                expected_view: expected_view.clone(),
                review_digest: codecs.review,
            };
            let result = source
                .resume_namespace(request, codecs.authority.deadline)?
                .await?;
            Ok(
                serde_json::json!({"action":"resume", "receipt":result.encode().map_err(OfflineRecoveryError::Target)?,
                "view":result.view_token().map_err(OfflineRecoveryError::Target)?,
                "reviewDigest":digest(codecs.review)}),
            )
        }
        _ => Err(invalid()),
    }
}
async fn migrate(
    source: &OfflineRecoverySource,
    codecs: &Codecs,
    observed: &NamespaceRecoveryView,
) -> Result<serde_json::Value, OfflineRecoveryError> {
    let (Action::StageMigration {
        operation_id,
        file,
        expected_view,
        checkpoint_digest,
        checkpoint_manifest_digest,
    }
    | Action::CompleteMigration {
        operation_id,
        file,
        expected_view,
        checkpoint_digest,
        checkpoint_manifest_digest,
    }) = &codecs.action
    else {
        return Err(invalid());
    };
    let mut scope = observed.scope();
    // The original operation always names the fixed recipe's V1 source. A
    // completed replay must not adopt the later V2 namespace/view identity.
    scope.state_schema = latent_state::recovery::migration::schema_ids()
        .map_err(OfflineRecoveryError::Review)?
        .0
        .as_str()
        .into();
    let request = OfflineAggregateMigrationRequest {
        checkpoint: snapshot_file(file),
        review: AggregateMigrationRequest {
            scope,
            operation_id: operation_id.clone(),
            operator_id: codecs.authority.actor.clone(),
            expected_view: expected_view.clone(),
            checkpoint_digest: assets::digest_bytes(checkpoint_digest).map_err(|_| invalid())?,
            checkpoint_manifest_digest: assets::digest_bytes(checkpoint_manifest_digest)
                .map_err(|_| invalid())?,
            package_digest: codecs.catalog.primary().schema.declaration().package_digest,
            review_digest: codecs.review,
        },
    };
    let result = if matches!(codecs.action, Action::StageMigration { .. }) {
        source
            .stage_aggregate_migration(request, codecs.authority.deadline)?
            .await?
    } else {
        source
            .complete_aggregate_migration(request, codecs.authority.deadline)?
            .await?
    };
    migration_result(&result)
}
fn snapshot(receipt: &SnapshotReceipt) -> serde_json::Value {
    serde_json::json!({"action":"snapshot", "snapshotDigest":digest(receipt.snapshot_digest),
        "manifestDigest":digest(receipt.manifest_digest), "fileBytes":receipt.file_bytes.to_string(),
        "manifest":receipt.manifest})
}
fn namespace(observed: &NamespaceRecoveryView) -> Result<serde_json::Value, OfflineRecoveryError> {
    Ok(serde_json::json!({"action":"inspect-namespace",
        "namespace":observed.namespace.encode().map_err(|_| invalid())?,
        "history":observed.history.encode().map_err(|_| invalid())?,
        "guard":observed.guard.as_ref().map(latent_state::recovery::RecoveryGuard::encode).transpose().map_err(OfflineRecoveryError::Input)?,
        "view":observed.view_token().map_err(OfflineRecoveryError::Input)?}))
}
fn migration_result(
    progress: &AggregateMigrationProgress,
) -> Result<serde_json::Value, OfflineRecoveryError> {
    Ok(
        serde_json::json!({"action":"migration", "completed":progress.completed(),
        "progress":progress.encode().map_err(OfflineRecoveryError::Target)?,
        "sourceNamespace":progress.source_namespace().map_err(OfflineRecoveryError::Target)?
            .encode().map_err(|_| invalid())?}),
    )
}
fn restore_request(
    codecs: &Codecs,
    file: &File,
    root: &std::path::Path,
    operation: &str,
    snapshot: &str,
    acknowledgement: [u8; 32],
) -> Result<OfflineRestoreRequest, OfflineRecoveryError> {
    Ok(OfflineRestoreRequest {
        input: snapshot_file(file),
        destination: ProtectedStoreConfig::bounded_linux(root.to_owned()),
        review: RestoreRequest {
            operation_id: operation.into(),
            operator_id: codecs.authority.actor.clone(),
            snapshot_digest: assets::digest_bytes(snapshot).map_err(|_| invalid())?,
            runtime_digest: codecs.runtime,
            window_acknowledgement: acknowledgement,
        },
    })
}
fn snapshot_file(input: &File) -> SnapshotFile {
    SnapshotFile {
        root: input.root.clone(),
        file_name: input.name.clone(),
    }
}
fn invalid() -> OfflineRecoveryError {
    OfflineRecoveryError::InvalidConfiguration
}
fn digest(bytes: [u8; 32]) -> String {
    format!("sha256:{:x}", latent_core::digest::HexDigest(bytes))
}
