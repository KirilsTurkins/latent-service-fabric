//! Real CLI subprocesses over authenticated tonic and native publication/control/audit files.
//! No guest execution, external service, prepared binary, or model substitutes for these calls.
#![cfg(unix)]
#[path = "standalone_cli/process/common.rs"]
mod process;
#[path = "publication_operator/support.rs"]
mod support;
use support::Harness;
fn assert_lookup_and_reopen(h: Harness, root: &std::path::Path, receipt: &serde_json::Value) {
    assert_ne!(
        h.run(
            "caller",
            &["operation", "--kind", "reclaim", "--operation-id", "delete"]
        )
        .code,
        Some(0)
    );
    let foreign = h
        .run(
            "foreign",
            &["operation", "--kind", "reclaim", "--operation-id", "delete"],
        )
        .json(0, "success");
    assert!(foreign["data"]["receipt"].is_null());
    assert_eq!(foreign["data"]["automaticReplay"], false);
    drop(h);
    let h = Harness::open(root, 128);
    let found = h.call(&["operation", "--kind", "reclaim", "--operation-id", "delete"]);
    assert_eq!(&found["data"]["receipt"], receipt);
    assert_eq!(h.audit.snapshot().retained_records, 10);
    assert_eq!(
        h.artifacts
            .publication_capacity_snapshot()
            .unwrap()
            .release_directories,
        0
    );
}
#[test]
fn native_cli_pins_deletes_reclaims_and_queries_original_receipts_after_reopen() {
    let root = tempfile::tempdir().unwrap();
    let h = Harness::open(root.path(), 128);
    let publication = h.retired("cli-maintenance");
    let (fence, target) = h.selected(&publication);
    let pin = h.call(&[
        "pin",
        "--operation-id",
        "pin",
        "--catalog-fence",
        &fence,
        "--target",
        &target,
    ]);
    assert_eq!(pin["data"]["receipt"]["stage"], "retention-updated");
    let (fence, target) = h.selected(&publication);
    let blocked = h.run(
        "operator",
        &[
            "delete",
            "--operation-id",
            "delete-pinned",
            "--catalog-fence",
            &fence,
            "--target",
            &target,
        ],
    );
    assert_ne!(blocked.code, Some(0));
    assert_eq!(h.audit.snapshot().retained_records, 2);
    h.call(&[
        "unpin",
        "--operation-id",
        "unpin",
        "--catalog-fence",
        &fence,
        "--target",
        &target,
    ]);
    let (fence, target) = h.selected(&publication);
    let delete = h.call(&[
        "delete",
        "--operation-id",
        "delete",
        "--catalog-fence",
        &fence,
        "--target",
        &target,
    ]);
    assert_eq!(delete["data"]["receipt"]["stage"], "visibility-removed");
    assert!(delete["data"]["receipt"]["reclaimed"].is_null());
    let assess = h.call(&[
        "assess",
        "--operation-id",
        "delete",
        "--catalog-fence",
        &fence,
        "--target",
        &target,
    ]);
    assert_eq!(assess["data"]["authorizesLaterDeletion"], false);
    let current = assess["data"]["catalogFence"].as_str().unwrap();
    let reclaim = h.call(&[
        "reclaim",
        "--operation-id",
        "delete",
        "--catalog-fence",
        &fence,
        "--target",
        &target,
        "--reclamation-fence",
        current,
    ]);
    assert_eq!(reclaim["data"]["receipt"]["stage"], "namespaces-reclaimed");
    assert!(reclaim["data"]["receipt"]["reclaimed"]["physicalDiskBlocksFreed"].is_null());
    assert_eq!(
        h.artifacts
            .publication_capacity_snapshot()
            .unwrap()
            .release_directories,
        0
    );
    assert_eq!(h.audit.snapshot().retained_records, 8);
    let replay = h.call(&[
        "reclaim",
        "--operation-id",
        "delete",
        "--catalog-fence",
        &fence,
        "--target",
        &target,
        "--reclamation-fence",
        current,
    ]);
    assert_eq!(replay["data"]["replay"], true);
    assert_eq!(h.audit.snapshot().retained_records, 10);
    assert_lookup_and_reopen(h, root.path(), &reclaim["data"]["receipt"]);
}
#[test]
fn native_cli_audit_capacity_refuses_mutation_and_preserves_pinned_catalog() {
    let root = tempfile::tempdir().unwrap();
    let h = Harness::open(root.path(), 2);
    let publication = h.retired("cli-audit-full");
    let (fence, target) = h.selected(&publication);
    h.call(&[
        "pin",
        "--operation-id",
        "pin",
        "--catalog-fence",
        &fence,
        "--target",
        &target,
    ]);
    let (fresh, target) = h.selected(&publication);
    let rejected = h.run(
        "operator",
        &[
            "unpin",
            "--operation-id",
            "unpin",
            "--catalog-fence",
            &fresh,
            "--target",
            &target,
        ],
    );
    assert_ne!(rejected.code, Some(0));
    assert_eq!(h.audit.snapshot().retained_records, 2);
    assert_ne!(
        h.run(
            "operator",
            &[
                "pin",
                "--operation-id",
                "pin",
                "--catalog-fence",
                &fence,
                "--target",
                &target
            ]
        )
        .code,
        Some(0)
    );
    let snapshot = h.call(&["snapshot", "--publication", &publication]);
    assert_eq!(snapshot["data"]["entries"][0]["pin"]["operationId"], "pin");
    assert_eq!(snapshot["data"]["catalogFence"], fresh);
}
