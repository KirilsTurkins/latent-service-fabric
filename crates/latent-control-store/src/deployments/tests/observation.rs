mod cleanup;

use std::sync::atomic::Ordering;
use std::sync::Arc;

use latent_core::{DeploymentId, RouteGeneration, TenantId};
use latent_routing::{RouteCompiler, RouteResolver, RouteSnapshotPublisher, RouteSnapshotSource};

use super::fixtures::*;
use crate::{
    CatalogWorkObserver, CatalogWorkOperation as Operation, CatalogWorkOutcome as Outcome,
    CatalogWorkReceipt, DeploymentStore,
};

fn observed(root: &TempRoot, releases: &Arc<Releases>, observer: &CatalogWorkObserver) -> Store {
    run(Store::open_observed(
        root.0.clone(),
        releases.clone(),
        Limits::default(),
        observer.clone(),
    ))
    .unwrap()
}

fn receipt(
    observer: &CatalogWorkObserver,
    sequence: u64,
    operation: Operation,
    outcome: Outcome,
) -> CatalogWorkReceipt {
    let state = observer.snapshot();
    assert_eq!(
        (state.started, state.finished, state.active),
        (sequence, sequence, 0)
    );
    assert_eq!(state.maximum_active, 1);
    assert!(!state.overflowed && !state.poisoned);
    let receipt = state.last.unwrap();
    assert_eq!(
        (receipt.sequence, receipt.operation, receipt.outcome),
        (sequence, operation, outcome)
    );
    assert!(!receipt.overflowed);
    receipt
}

fn assert_staged_file(root: &TempRoot, receipt: &CatalogWorkReceipt, name: &str) {
    let length = std::fs::metadata(root.0.join(name)).unwrap().len();
    let counts = receipt.counts;
    assert_eq!(counts.stage_calls, 1);
    assert_eq!(counts.stage_completed, 1);
    assert_eq!(counts.stage_requested_bytes, length);
    assert_eq!(counts.stage_written_bytes, Some(length));
    assert_eq!(counts.stage_synced_bytes, length);
    assert_eq!(counts.stage_write_failures + counts.stage_sync_failures, 0);
    assert_eq!(
        counts.encoded_buffer_bytes,
        length * counts.encoder_completed
    );
    assert!(counts.encoded_capacity_max >= length);
    assert!(counts.encoded_capacity_max <= Limits::default().max_state_bytes as u64);
}

#[test]
fn observed_initialization_apply_and_reapply_count_the_existing_two_encodes() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("observation-known-work");
    let observer = CatalogWorkObserver::new();
    let store = observed(&root, &releases, &observer);
    let open = receipt(&observer, 1, Operation::Open, Outcome::ReturnedOk);
    assert_eq!(open.compiled_generation, Some(0));
    assert_eq!(
        (open.counts.compiler_calls, open.counts.compiler_completed),
        (1, 1)
    );
    assert_eq!(
        (open.counts.encoder_calls, open.counts.encoder_completed),
        (2, 2)
    );
    assert_staged_file(&root, &open, "catalog.json");
    let one = deployment("blue", "alice", &digest);
    let two = deployment("green", "alice", &digest);
    run(store.apply_many(vec![one.clone(), two])).unwrap();
    let applied = receipt(&observer, 2, Operation::ApplyMany, Outcome::ReturnedOk);
    let count = applied.counts;
    assert_eq!(applied.compiled_generation, Some(1));
    assert_eq!(count.normalization_deployment_encodes, 2);
    assert_eq!(
        (
            count.compiler_calls,
            count.compiler_completed,
            count.compiler_failed
        ),
        (1, 1, 0)
    );
    assert_eq!(
        (
            count.compiler_deployment_encodes,
            count.revision_identity_encodes
        ),
        (2, 2)
    );
    assert_eq!(count.contract_schema_encodes, 1);
    assert_eq!(
        (
            count.record_derivations,
            count.record_payload_reuses,
            count.record_derivation_reuses
        ),
        (2, 0, 0)
    );
    assert_eq!(
        (
            count.scopes_staged,
            count.scope_content_reuses,
            count.route_memberships_staged,
            count.route_memberships_remapped
        ),
        (1, 0, 4, 0)
    );
    assert_eq!(
        (
            count.encoder_calls,
            count.encoder_completed,
            count.encoder_failed
        ),
        (2, 2, 0)
    );
    assert_eq!(count.persistence_deployment_encodes, 4);
    assert_eq!(
        (
            count.payload_serializations,
            count.envelope_serializations,
            count.load_payload_serializations
        ),
        (2, 2, 0)
    );
    assert_staged_file(&root, &applied, "catalog.json");
    let first_record = Arc::clone(&store.read_catalog().records[0]);
    run(store.apply_versioned(&TenantId("alice".into()), one, Some(1))).unwrap();
    let reapplied = receipt(&observer, 3, Operation::ApplyVersioned, Outcome::ReturnedOk);
    assert_eq!(reapplied.compiled_generation, Some(2));
    assert_eq!(reapplied.counts.normalization_deployment_encodes, 1);
    assert_eq!(reapplied.counts.record_payload_reuses, 2);
    assert_eq!(reapplied.counts.record_derivations, 2);
    assert_eq!(reapplied.counts.record_derivation_reuses, 0);
    assert_eq!(reapplied.counts.persistence_deployment_encodes, 4);
    assert!(Arc::ptr_eq(&first_record, &store.read_catalog().records[0]));
    assert_eq!(releases.fetches.load(Ordering::Relaxed), 2);
    assert_staged_file(&root, &reapplied, "catalog.json");
}

#[test]
fn reopen_counts_load_validation_separately_and_reads_and_oracles_do_not_change_receipts() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("observation-reopen");
    let observer = CatalogWorkObserver::new();
    let store = observed(&root, &releases, &observer);
    let manifest = deployment("blue", "alice", &digest);
    run(store.apply_many(vec![manifest.clone()])).unwrap();
    let expected = snapshot(&store);
    drop(store);
    let store = observed(&root, &releases, &observer);
    let reopened = receipt(&observer, 3, Operation::Open, Outcome::ReturnedOk);
    assert_eq!(reopened.compiled_generation, Some(1));
    assert_eq!(reopened.counts.encoder_calls, 1);
    assert_eq!(reopened.counts.persistence_deployment_encodes, 1);
    assert_eq!(reopened.counts.load_payload_serializations, 1);
    assert!(reopened.counts.load_payload_buffer_bytes > 0);
    assert!(reopened.counts.load_payload_capacity_max >= reopened.counts.load_payload_buffer_bytes);
    assert_eq!(reopened.counts.stage_calls, 0);
    assert_eq!(reopened.counts.stage_written_bytes, Some(0));
    assert_eq!(snapshot(&store), expected);
    let before = observer.snapshot();
    let _ = crate::deployment_revision_id(&manifest).unwrap();
    let _ = store
        .pin()
        .unwrap()
        .resolve(&target("alice", None), None)
        .unwrap();
    let _ = run(DeploymentStore::get(&store, &manifest.id)).unwrap();
    let _ = run(store.list()).unwrap();
    drop(store);
    assert_eq!(observer.snapshot(), before);
    // The independent observer never keeps the root ownership lock alive.
    drop(run(Store::open(root.0.clone(), releases, Limits::default())).unwrap());
    assert_eq!(observer.snapshot(), before);
}

#[test]
fn rejection_and_late_durability_failure_preserve_actual_work_and_product_state() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("observation-errors");
    let observer = CatalogWorkObserver::new();
    let store = observed(&root, &releases, &observer);
    let manifest = deployment("blue", "alice", &digest);
    let error = run(store.apply_versioned(&TenantId("alice".into()), manifest.clone(), Some(4)))
        .unwrap_err();
    assert_eq!(error.code, Code::StateConflict);
    let rejected = receipt(
        &observer,
        2,
        Operation::ApplyVersioned,
        Outcome::ReturnedError,
    );
    assert_eq!(rejected.compiled_generation, None);
    assert_eq!(rejected.counts.normalization_deployment_encodes, 1);
    assert_eq!(
        (
            rejected.counts.compiler_calls,
            rejected.counts.encoder_calls,
            rejected.counts.stage_calls
        ),
        (0, 0, 0)
    );
    store.fail_before_rename.store(true, Ordering::SeqCst);
    assert_eq!(
        run(store.apply_many(vec![manifest.clone()]))
            .unwrap_err()
            .message,
        "injected-before-rename"
    );
    let before_rename = receipt(&observer, 3, Operation::ApplyMany, Outcome::ReturnedError);
    assert_staged_file(&root, &before_rename, ".catalog.pending");
    assert_eq!(store.generation(), RouteGeneration(0));
    store.fail_parent_sync.store(true, Ordering::SeqCst);
    assert_eq!(
        run(store.apply_many(vec![manifest])).unwrap_err().message,
        "commit-durability-uncertain"
    );
    let uncertain = receipt(&observer, 4, Operation::ApplyMany, Outcome::ReturnedError);
    assert_staged_file(&root, &uncertain, "catalog.json");
    assert_eq!(store.generation(), RouteGeneration(1));
    assert!(store.writer.try_lock().is_ok());
    assert!(store.current.try_write().is_ok());
}

#[test]
fn explicit_compile_publish_delete_and_empty_batch_keep_distinct_receipts() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("observation-operations");
    let observer = CatalogWorkObserver::new();
    let store = observed(&root, &releases, &observer);
    run(store.apply_many(vec![deployment("blue", "alice", &digest)])).unwrap();
    let current = run(RouteSnapshotSource::current(&store)).unwrap();
    let next = run(RouteCompiler::compile(&store, Some(&current))).unwrap();
    let compiled = receipt(
        &observer,
        3,
        Operation::CompileSnapshot,
        Outcome::ReturnedOk,
    );
    assert_eq!(compiled.compiled_generation, Some(2));
    assert_eq!(
        (compiled.counts.encoder_calls, compiled.counts.stage_calls),
        (1, 0)
    );
    run(RouteSnapshotPublisher::publish(&store, next)).unwrap();
    let published = receipt(
        &observer,
        4,
        Operation::PublishSnapshot,
        Outcome::ReturnedOk,
    );
    assert_eq!(
        (
            published.counts.compiler_calls,
            published.counts.encoder_calls,
            published.counts.stage_calls
        ),
        (1, 2, 1)
    );
    run(store.delete_versioned(
        &TenantId("alice".into()),
        &DeploymentId("blue".into()),
        Some(1),
    ))
    .unwrap();
    let deleted = receipt(
        &observer,
        5,
        Operation::DeleteVersioned,
        Outcome::ReturnedOk,
    );
    assert_eq!(deleted.compiled_generation, Some(3));
    assert_eq!(deleted.counts.compiler_deployment_encodes, 0);
    assert_eq!(deleted.counts.encoder_calls, 2);
    assert_eq!(
        run(store.apply_many(Vec::new())).unwrap(),
        RouteGeneration(3)
    );
    let empty = receipt(&observer, 6, Operation::ApplyMany, Outcome::ReturnedOk);
    assert_eq!(empty.compiled_generation, None);
    assert_eq!(empty.counts, crate::CatalogWorkCounts::default());
}
