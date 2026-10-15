//! Real current signed Catalog capture, protected snapshot, migration and restore.
mod configuration;
mod export;
mod fixture;
mod package;
mod policy;
mod restore;
mod seed;

use fixture::*;
use latent_state::{embedded::StoreError, recovery::snapshot::RequiredArtifact};

fn canonical(fixture: &Fixture) -> RequiredArtifact {
    let source = fixture.codecs.catalog.primary();
    RequiredArtifact {
        identity: format!(
            "package:{}",
            source.operation.publication().package().unwrap()
        ),
        digest: source.schema.declaration().package_digest,
    }
}

fn migration_stage_code(error: &latent_core::PlatformError) -> &'static str {
    match error.message.as_str() {
        "protected-migration:Source(Invalid)" => "Source(Invalid)",
        "protected-migration:Source(Capacity)" => "Source(Capacity)",
        "protected-migration:Source(Conflict)" => "Source(Conflict)",
        "protected-migration:Source(Corrupt)" => "Source(Corrupt)",
        "protected-migration:Source(UnsupportedFormat)" => "Source(UnsupportedFormat)",
        "protected-migration:Source(Unavailable)" => "Source(Unavailable)",
        "protected-migration:Source(CommitUncertain)" => "Source(CommitUncertain)",
        "protected-migration:Source(SnapshotExpired)" => "Source(SnapshotExpired)",
        "protected-migration:Review(Invalid)" => "Review(Invalid)",
        "protected-migration:Review(Capacity)" => "Review(Capacity)",
        "protected-migration:Review(Conflict)" => "Review(Conflict)",
        "protected-migration:Review(Corrupt)" => "Review(Corrupt)",
        "protected-migration:Review(UnsupportedFormat)" => "Review(UnsupportedFormat)",
        "protected-migration:Review(Unavailable)" => "Review(Unavailable)",
        "protected-migration:Review(CommitUncertain)" => "Review(CommitUncertain)",
        "protected-migration:Review(SnapshotExpired)" => "Review(SnapshotExpired)",
        "protected-migration:Deadline" => "Deadline",
        "protected-migration:Capacity" => "Capacity",
        "native-original-deadline" => "native-original-deadline",
        _ => "unmapped",
    }
}

#[tokio::test]
async fn actual_installed_current_snapshot_stages_migration_under_original_owners() {
    let mut fixture = Box::pin(Fixture::new(1)).await;
    assert_eq!(fixture.codecs.catalog.schemas.len(), 1);
    assert_eq!(
        fixture.codecs.catalog.primary().profile,
        super::super::profile::Profile::CurrentWriter
    );
    let original_owner = fixture.codecs.original.is_from_owner(&fixture.native)
        && fixture.store.uses_native_capacity(&fixture.native)
        && fixture
            .codecs
            .catalog
            .schemas
            .iter()
            .all(|schema| Arc::ptr_eq(&schema.operation.original, &fixture.codecs.original));
    let snapshot = fixture.snapshot().await;
    let required: Vec<RequiredArtifact> = serde_json::from_value(
        snapshot.get()["manifest"]["metadata"]["required_artifacts"].clone(),
    )
    .unwrap();
    let package = fixture
        .codecs
        .catalog
        .primary()
        .operation
        .publication()
        .package()
        .unwrap();
    let bare = required.iter().any(|artifact| {
        artifact.identity == package.as_str()
            && artifact.digest
                == fixture
                    .codecs
                    .catalog
                    .primary()
                    .schema
                    .declaration()
                    .package_digest
    });
    let has_canonical = required.contains(&canonical(&fixture));
    let stage = fixture.stage(snapshot.get(), "installed.snapshot").await;
    let succeeded = stage.get().is_ok();
    let error_code = stage.get().as_ref().err().map(migration_stage_code);
    let error_platform = stage
        .get()
        .as_ref()
        .err()
        .map(|error| error.code.wire_code());
    let error_layer = stage.get().as_ref().err().map(|error| {
        match error.message.split_once(':').map(|(layer, _)| layer) {
            Some("protected-migration") => "migration",
            Some("protected-snapshot") => "snapshot",
            Some("protected-owner") => "owner",
            Some("native-original-job") => "job",
            Some("native-review") => "native-review",
            _ if error.message == "native-original-deadline" => "original-deadline",
            _ => "unmapped",
        }
    });
    if let Ok(value) = stage.get() {
        assert_eq!(value["action"], "stage-migration");
        assert_eq!(value["completed"], false);
        assert_eq!(value["resourcePhysicallyRetired"], true);
    }
    drop((stage, snapshot));
    let retired = fixture.finish().await;
    eprintln!(
        "baseline-migration-package: {}",
        json!({
            "catalogCaptured":true,"snapshotSucceeded":true,"barePackageDeclared":bare,
            "canonicalPackageDeclared":has_canonical,"stageErrorCode":error_code,
            "stagePlatformCode":error_platform,"stageErrorLayer":error_layer,
            "originalNativeOwner":original_owner,"nativePhysicallyRetired":retired,
        })
    );
    assert!(bare && original_owner && retired);
    assert!(
        succeeded,
        "actual current snapshot must reach accepted protected migration stage"
    );
}

#[tokio::test]
async fn actual_current_snapshot_package_superset_restores_under_current_authority() {
    let mut fixture = Box::pin(Fixture::new(1)).await;
    let snapshot = fixture.snapshot().await;
    let result = fixture.restore(snapshot.get(), "installed.snapshot").await;
    let restored = result.get().as_ref().is_ok_and(|value| {
        value["action"] == "restore"
            && value["resourcePhysicallyRetired"] == true
            && value["pausedForReconciliation"] == true
    });
    drop((result, snapshot));
    fixture.finish().await;
    assert!(
        restored,
        "the actual newly exported metadata superset must restore"
    );
}

#[tokio::test]
async fn actual_old_current_snapshot_restores_but_missing_package_role_refuses_migration() {
    let mut fixture = Box::pin(Fixture::new(1)).await;
    let legacy = fixture.legacy_metadata("old-current");
    assert!(!legacy.required_artifacts.contains(&canonical(&fixture)));
    let exported = fixture.export_metadata(legacy, "old.snapshot").await;
    let snapshot = exported.get().as_ref().unwrap();
    let stage = fixture.stage(snapshot, "old.snapshot").await;
    let refused = stage
        .get()
        .as_ref()
        .is_err_and(|error| error.message == "protected-migration:Review(UnsupportedFormat)");
    drop(stage);
    let restored = fixture.restore(snapshot, "old.snapshot").await;
    let accepted = restored.get().as_ref().is_ok_and(|value| {
        value["action"] == "restore"
            && value["resourcePhysicallyRetired"] == true
            && value["pausedForReconciliation"] == true
    });
    drop((restored, exported));
    fixture.finish().await;
    assert!(
        refused && accepted,
        "old current snapshots keep restore compatibility and strict migration refusal"
    );
}

async fn rejected_artifact(kind: &str) {
    let fixture = Box::pin(Fixture::new(1)).await;
    let mut artifact = canonical(&fixture);
    match kind {
        "digest" => artifact.digest[0] ^= 1,
        "role" => {
            artifact.identity = format!(
                "package:{}",
                fixture
                    .codecs
                    .catalog
                    .primary()
                    .operation
                    .publication()
                    .publication()
                    .as_str()
            );
        }
        "foreign" => artifact.identity = format!("package:sha256:{}", "1".repeat(64)),
        _ => unreachable!(),
    }
    let mut metadata = fixture.legacy_metadata(kind);
    metadata.required_artifacts.push(artifact);
    let result = fixture.export_metadata(metadata, "rejected.snapshot").await;
    let refused = result
        .get()
        .as_ref()
        .is_err_and(|error| error.message == "protected-snapshot:Review(UnsupportedFormat)");
    drop(result);
    fixture.finish().await;
    assert!(
        refused,
        "actual protected snapshot must reject the substituted artifact"
    );
}

#[tokio::test]
async fn actual_wrong_package_digest_is_refused_by_protected_snapshot() {
    rejected_artifact("digest").await;
}

#[tokio::test]
async fn actual_same_digest_wrong_package_role_is_refused_by_protected_snapshot() {
    rejected_artifact("role").await;
}

#[tokio::test]
async fn actual_foreign_package_identity_is_refused_by_protected_snapshot() {
    rejected_artifact("foreign").await;
}

#[tokio::test]
async fn actual_canonical_package_requires_original_bare_association() {
    let mut fixture = Box::pin(Fixture::new(1)).await;
    let artifact = canonical(&fixture);
    assert_eq!(fixture.codecs.artifact(&artifact), Ok(()));
    let bare = artifact.identity.strip_prefix("package:").unwrap();
    Arc::get_mut(&mut fixture.codecs)
        .unwrap()
        .catalog
        .artifacts
        .retain(|entry| entry.identity != bare);
    let result = fixture.codecs.artifact(&artifact);
    let refused_producer = fixture.codecs.catalog.snapshot_artifacts().is_err();
    fixture.finish().await;
    assert_eq!(result, Err(StoreError::UnsupportedFormat));
    assert!(refused_producer);
}

#[tokio::test]
async fn actual_four_selected_packages_fit_original_paid_metadata() {
    let fixture = Box::pin(Fixture::new(4)).await;
    assert_eq!(fixture.codecs.catalog.schemas.len(), 4);
    let metadata = fixture.codecs.catalog.snapshot_artifacts().unwrap();
    assert_eq!(
        metadata
            .iter()
            .filter(|entry| entry.identity.starts_with("package:"))
            .count(),
        4
    );
    assert!(metadata.len() <= 52 && metadata.capacity() <= 128);
    let vector_bytes = |entries: &Vec<RequiredArtifact>| {
        entries.capacity() * size_of::<RequiredArtifact>()
            + entries
                .iter()
                .map(|entry| entry.identity.capacity())
                .sum::<usize>()
    };
    let original = vector_bytes(&fixture.codecs.catalog.artifacts)
        + fixture
            .codecs
            .catalog
            .schemas
            .iter()
            .map(|schema| vector_bytes(&schema.artifacts))
            .sum::<usize>();
    let encoded = serde_json::to_vec(&metadata).unwrap();
    // Include the moved input, readback metadata clone and their encoded overlap;
    // all existing schema vectors are counted while their original keeper lives.
    let peak = original + 3 * vector_bytes(&metadata) + 2 * encoded.capacity();
    let conservative_artifact_peak =
        5 * 128 * (size_of::<RequiredArtifact>() + 256) + 4 * 128 * 512;
    let Codecs {
        _metadata: paid_metadata,
        ..
    } = fixture.codecs.as_ref();
    assert_eq!(paid_metadata.bytes(), 1024 * 1024);
    assert!(paid_metadata.is_from_owner(&fixture.native));
    assert!(peak <= conservative_artifact_peak);
    assert!(conservative_artifact_peak < usize::try_from(paid_metadata.bytes()).unwrap());
    eprintln!(
        "migration-package-metadata: {}",
        json!({
            "sources":4,"requiredArtifacts":metadata.len(),"vectorCapacity":metadata.capacity(),
            "actualArtifactPeakBytes":peak,"conservativeArtifactPeakBytes":conservative_artifact_peak,
            "originalPaidMetadataBytes":paid_metadata.bytes(),
        })
    );
    let snapshot = fixture.snapshot().await;
    assert_eq!(
        snapshot.get()["manifest"]["metadata"]["required_artifacts"]
            .as_array()
            .unwrap()
            .len(),
        metadata.len()
    );
    drop((metadata, encoded, snapshot));
    fixture.finish().await;
}

#[tokio::test]
async fn actual_current_policy_withdrawal_refuses_snapshot_output() {
    let fixture = Box::pin(Fixture::new(1)).await;
    policy::revoke(&fixture);
    let metadata = fixture.legacy_metadata("withdrawn");
    let result = fixture
        .export_metadata(metadata, "withdrawn.snapshot")
        .await;
    let refused = result.get().is_err();
    drop(result);
    fixture.finish().await;
    assert!(refused);
}
