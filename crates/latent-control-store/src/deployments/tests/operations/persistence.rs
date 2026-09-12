use super::*;
use latent_artifacts::content_digest;

#[test]
fn before_and_after_rename_failures_keep_receipt_and_catalog_commit_together() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("cutpoint");
    let store = open(&root, &releases);
    run(store.apply(deployment("base", "alice", &one))).unwrap();
    let original = bytes(&root);
    let request = apply("managed", 1, "blue", 0, &one);
    let prepared = run(store.prepare_operation(request.clone())).unwrap();
    store.fail_before_rename.store(true, Ordering::SeqCst);
    assert_code(store.commit_operation(prepared), Code::Unavailable);
    assert_eq!(bytes(&root), original);
    assert!(matches!(
        lookup(&store, "managed").value(),
        DeploymentOperationLookup::Unknown { .. }
    ));
    assert_eq!(store.generation(), RouteGeneration(1));
    let prepared = run(store.prepare_operation(request.clone())).unwrap();
    let receipt = prepared.preview().clone();
    store.fail_parent_sync.store(true, Ordering::SeqCst);
    let committed = store.commit_operation(prepared).unwrap();
    assert_eq!(committed.value().receipt, receipt);
    assert_eq!(
        committed.value().durability.as_ref().unwrap_err().code,
        Code::Unavailable
    );
    assert_eq!(store.generation(), RouteGeneration(2));
    assert_eq!(
        lookup(&store, "managed").value(),
        &DeploymentOperationLookup::Uncertain
    );
    let snapshot =
        run(store.get_operation_snapshot(&alice(), &DeploymentId("blue".into()))).unwrap();
    assert!(!snapshot.value().confirmed);
    assert!(snapshot.value().deployment.is_some());
    assert_code(
        run(store.prepare_operation(request.clone())),
        Code::Unavailable,
    );
    drop(snapshot);
    drop(committed);
    drop(store);
    let reopened = open(&root, &releases);
    assert_eq!(
        lookup(&reopened, "managed").value(),
        &DeploymentOperationLookup::Found(receipt.clone())
    );
    let replay = execute(&reopened, request);
    assert!(replay.value().replayed);
    assert_eq!(replay.value().receipt, receipt);
}

#[test]
fn recovery_rejects_invalid_receipt_history_even_with_valid_outer_checksum() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("corruption");
    let store = open(&root, &releases);
    drop(execute(&store, apply("first", 0, "blue", 0, &one)));
    drop(execute(&store, apply("second", 1, "blue", 1, &one)));
    drop(store);
    let original = bytes(&root);
    for mutation in 0..8 {
        let mut record: crate::deployments::persistence::Record =
            json::from_slice(&original).unwrap();
        let control = record.payload.control.as_mut().unwrap();
        let table = control.deployment_operations.as_mut().unwrap();
        match mutation {
            0 => table.receipts[0].sequence += 1,
            1 => table.operation_sequence += 1,
            2 => table.receipts[1].receipt = table.receipts[0].receipt.clone(),
            3 => table.receipts[0].receipt.component = releases.add("foreign"),
            4 => table.receipt_slots = 1,
            5 => {
                table.receipts[0].receipt.state_version = u64::MAX;
                table.receipts[0].receipt.receipt_digest =
                    crate::deployment_operations::codec::receipt_hash(&table.receipts[0].receipt)
                        .unwrap();
            }
            6 => {
                table.receipts.remove(0);
            }
            7 => {
                table.receipt_slots = 2;
                table.operation_sequence = 100;
                table.receipts[0].sequence = 99;
                table.receipts[1].sequence = 100;
                control.transaction_version = 100;
            }
            _ => unreachable!(),
        }
        record.checksum = content_digest(&json::to_vec(&record.payload).unwrap()).0;
        std::fs::write(root.0.join("catalog.json"), json::to_vec(&record).unwrap()).unwrap();
        assert_code(
            run(Store::open(&root.0, releases.clone(), Limits::default())),
            Code::CorruptArtifact,
        );
    }
    for field in ["missing", "null"] {
        let mut value: json::Value = json::from_slice(&original).unwrap();
        let control = value["payload"]["control"].as_object_mut().unwrap();
        if field == "missing" {
            control.remove("deployment_operations");
        } else {
            control.insert("deployment_operations".into(), json::Value::Null);
        }
        std::fs::write(root.0.join("catalog.json"), json::to_vec(&value).unwrap()).unwrap();
        assert_code(
            run(Store::open(&root.0, releases.clone(), Limits::default())),
            Code::CorruptArtifact,
        );
    }
}

#[test]
fn rejected_or_dropped_preparation_never_publishes_operation_history() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("preflight");
    let store = open(&root, &releases);
    let original = bytes(&root);
    let prepared = run(store.prepare_operation(apply("preview", 0, "blue", 0, &one))).unwrap();
    assert_eq!(prepared.preview().state_version, 1);
    assert_eq!(bytes(&root), original);
    assert!(!root.0.join(".catalog.pending").exists());
    drop(prepared);
    assert_eq!(
        lookup(&store, "preview").value(),
        &DeploymentOperationLookup::Unknown {
            retained_floor: 1,
            high_watermark: 0
        }
    );
    assert_eq!(store.generation(), RouteGeneration(0));
    drop(execute(&store, apply("accepted", 0, "blue", 0, &one)));
    assert_eq!(
        stored(&root)["payload"]["control"]["deployment_operations"]["operation_sequence"],
        1
    );
}
