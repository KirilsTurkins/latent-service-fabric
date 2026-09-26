use super::*;
use crate::deployment_operations::{
    DeploymentOperationContext, DeploymentOperationLookup, DeploymentOperationReceipt,
    DeploymentOperationRequest,
};

fn operation(id: &str, state: u64) -> DeploymentOperationContext {
    DeploymentOperationContext {
        tenant: TenantId("alice".into()),
        actor: actor(),
        operation_id: id.into(),
        expected_state_version: state,
    }
}
fn apply(id: &str, publication: Option<&PublicationRef>, state: u64) -> DeploymentOperationRequest {
    let mut manifest = deployment(id, "alice", &release());
    manifest.publication = publication.map(|value| value.id.clone());
    DeploymentOperationRequest::Apply {
        context: operation(id, state),
        manifest,
        expected_generation: 0,
    }
}
fn commit(catalog: &Store, input: DeploymentOperationRequest) -> DeploymentOperationReceipt {
    let prepared = run(catalog.prepare_operation(input)).unwrap();
    let committed = catalog.commit_operation(prepared).unwrap();
    committed.value().durability.as_ref().unwrap();
    committed.value().receipt.clone()
}
fn lookup(catalog: &Store, id: &str) -> DeploymentOperationReceipt {
    let found = run(catalog.get_operation(&TenantId("alice".into()), id)).unwrap();
    match found.value() {
        DeploymentOperationLookup::Found(receipt) => receipt.clone(),
        other => panic!("expected retained receipt: {other:?}"),
    }
}

#[test]
fn operation_history_keeps_exact_publication_after_delete_revoke_restart_and_replay() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repository = artifacts(&roots[0]);
    let first = publish(&repository, "alice", "first");
    let second = publish(&repository, "alice", "second");
    let catalog = store(&roots[1], &repository);
    let input = apply("first", Some(&first), 0);
    let original = commit(&catalog, input.clone());
    assert_eq!(original.publication.as_ref(), Some(&first));
    let corrected = commit(&catalog, apply("second", Some(&second), 1));
    assert_eq!(corrected.publication.as_ref(), Some(&second));
    let deleted = commit(
        &catalog,
        DeploymentOperationRequest::Delete {
            context: operation("delete", 2),
            id: DeploymentId("first".into()),
            expected_generation: original.object_generation,
        },
    );
    assert_eq!(deleted.publication.as_ref(), Some(&first));
    revoke(&repository, &first);
    drop(catalog);
    drop(repository);
    let repository = artifacts(&roots[0]);
    let catalog = store(&roots[1], &repository);
    assert_eq!(lookup(&catalog, "first"), original);
    assert_eq!(lookup(&catalog, "delete"), deleted);
    assert_eq!(lookup(&catalog, "second"), corrected);
    let replay = catalog
        .commit_operation(run(catalog.prepare_operation(input)).unwrap())
        .unwrap();
    assert!(replay.value().replayed);
    assert_eq!(replay.value().receipt, original);
    assert_eq!(
        replay
            .value()
            .deployment
            .as_ref()
            .unwrap()
            .publication
            .as_ref(),
        Some(&first)
    );
    assert!(run(
        catalog.get_operation_snapshot(&TenantId("alice".into()), &DeploymentId("first".into()))
    )
    .unwrap()
    .value()
    .deployment
    .is_none());
    assert_eq!(
        catalog
            .resolve(&target("alice", Some("second")), None)
            .unwrap()
            .publication,
        Some(second.id)
    );
    let bytes = std::fs::read(roots[1].0.join("catalog.json")).unwrap();
    let stored: json::Value = json::from_slice(&bytes).unwrap();
    let table = &stored["payload"]["control"]["deployment_operations"];
    assert_eq!(table["format_version"], 2);
    assert_eq!(table["receipts"][0]["publication"]["id"], first.id.as_str());
    assert!(table["receipts"][0]["receipt"].get("publication").is_none());
}

#[test]
fn obsolete_operation_table_is_rejected_without_inventing_publication_receipts() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repository = artifacts(&roots[0]);
    let first = publish(&repository, "alice", "first");
    let catalog = store(&roots[1], &repository);
    commit(&catalog, apply("original", Some(&first), 0));
    drop(catalog);
    let path = roots[1].0.join("catalog.json");
    let mut record: crate::deployments::persistence::Record =
        json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    let table = record
        .payload
        .control
        .as_mut()
        .unwrap()
        .deployment_operations
        .as_mut()
        .unwrap();
    table.format_version = 1;
    for row in &mut table.receipts {
        row.publication = None;
    }
    record.checksum = latent_artifacts::content_digest(&json::to_vec(&record.payload).unwrap()).0;
    let bytes = json::to_vec(&record).unwrap();
    std::fs::write(&path, &bytes).unwrap();
    assert!(run(Store::open_with_catalog(
        &roots[1].0,
        repository.clone(),
        Limits::default(),
        repository.lifecycle_authority(),
        super::super::lifecycle::profile("47.0.4")
    ))
    .is_err());
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
}

#[test]
fn operation_recovery_rejects_dropped_or_forged_scope_with_valid_outer_checksum() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repository = artifacts(&roots[0]);
    let first = publish(&repository, "alice", "first");
    let catalog = store(&roots[1], &repository);
    commit(&catalog, apply("first", Some(&first), 0));
    drop(catalog);
    let path = roots[1].0.join("catalog.json");
    let original = std::fs::read(&path).unwrap();
    for mutation in 0..4 {
        let mut record: crate::deployments::persistence::Record =
            json::from_slice(&original).unwrap();
        let table = record
            .payload
            .control
            .as_mut()
            .unwrap()
            .deployment_operations
            .as_mut()
            .unwrap();
        match mutation {
            0 => table.receipts[0].publication = None,
            1 => {
                table.receipts[0].publication.as_mut().unwrap().scope =
                    LifecycleScope::Tenant(TenantId("bob".into()))
            }
            2 => {
                table.receipts[0].publication.as_mut().unwrap().scope =
                    LifecycleScope::LocalUnscoped
            }
            3 => table.format_version = 1,
            _ => unreachable!(),
        }
        record.checksum =
            latent_artifacts::content_digest(&json::to_vec(&record.payload).unwrap()).0;
        let bytes = json::to_vec(&record).unwrap();
        std::fs::write(&path, &bytes).unwrap();
        assert!(run(Store::open_with_catalog(
            &roots[1].0,
            repository.clone(),
            Limits::default(),
            repository.lifecycle_authority(),
            super::super::lifecycle::profile("47.0.4")
        ))
        .is_err());
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
}
