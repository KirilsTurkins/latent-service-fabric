//! Closed retained-data fixture, never a completed migration or authority receipt.
use super::*;
use latent_state::recovery::migration::{
    AggregateMigrationProgress, AggregateMigrationRecipe, AggregateMigrationRequest,
};
use sha2::{Digest, Sha256};

pub(super) fn retain(
    engine: &latent_state::embedded::EmbeddedStore,
    request: &NamespaceResumeRequest,
) -> Result<(), StoreError> {
    let view = engine.snapshot()?;
    let actual =
        NamespaceRecoveryView::capture(&view, &request.scope.tenant, &request.scope.namespace)?;
    let recipe = AggregateMigrationRecipe::JavaAggregate;
    let migration = AggregateMigrationRequest {
        scope: request.scope.clone(),
        operation_id: "retained-migration".into(),
        operator_id: request.operator_id.clone(),
        expected_view: actual.view_token()?,
        checkpoint_digest: [1; 32],
        checkpoint_manifest_digest: [2; 32],
        package_digest: [3; 32],
        review_digest: [4; 32],
    };
    let key = migration.progress_key()?;
    let mut hash = Sha256::new();
    hash.update(b"lsf-protected-aggregate-migration-input-v2\0");
    hash.update(&key.key);
    hash.update(&migration.expected_view);
    for digest in [
        migration.checkpoint_digest,
        migration.checkpoint_manifest_digest,
        migration.package_digest,
        migration.review_digest,
        recipe.digest(),
    ] {
        hash.update(digest);
    }
    let fingerprint: [u8; 32] = hash.finalize().into();
    let mut bytes = b"LMG\0\x02".to_vec();
    bytes.push(0);
    frame(&mut bytes, migration.operation_id.as_bytes());
    frame(&mut bytes, migration.operator_id.as_bytes());
    for digest in [
        fingerprint,
        migration.checkpoint_digest,
        migration.checkpoint_manifest_digest,
        migration.package_digest,
        migration.review_digest,
        [5; 32],
        [6; 32],
        recipe.digest(),
    ] {
        bytes.extend_from_slice(&digest);
    }
    frame(&mut bytes, &actual.namespace.encode().unwrap());
    bytes.push(1);
    frame(&mut bytes, &actual.history.encode().unwrap());
    bytes.push(0); // Actual original installation has no recovery guard.
    let quota = latent_state::tenant::inspect(&view, &request.scope.tenant)?.unwrap();
    bytes.push(1);
    frame(&mut bytes, &quota.encode()?);
    let mut staged = quota;
    staged.generation += 1;
    bytes.push(1);
    frame(&mut bytes, &staged.encode()?);
    bytes.extend_from_slice(&Sha256::digest(&bytes));
    AggregateMigrationProgress::validate_row(&key, &bytes)?;
    assert!(!AggregateMigrationProgress::decode(&bytes)?.completed());
    drop(view);
    fixture::apply_accounted(
        engine,
        AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key,
                value: Some(bytes),
            }],
        },
    )?;
    let actual = latent_state::recovery::migration::inspect_progress(
        &engine.snapshot()?,
        &request.scope,
        &request.operator_id,
        "retained-migration",
    )?
    .unwrap();
    assert!(!actual.completed());
    Ok(())
}

fn frame(target: &mut Vec<u8>, bytes: &[u8]) {
    target.extend_from_slice(&u16::try_from(bytes.len()).unwrap().to_le_bytes());
    target.extend_from_slice(bytes);
}
