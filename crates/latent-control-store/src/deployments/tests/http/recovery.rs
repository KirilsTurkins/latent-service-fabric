use super::*;

#[test]
fn http_corrupt_history_and_mismatched_prepared_owner_are_rejected() {
    let (roots, repo, store, _) = setup();
    let definition = definition(&store, "alice", "browser", "web", "/", "prefix");
    let command = request(&store, "create", definition, 0);
    let foreign_root = TempRoot::new();
    let foreign = catalog(&foreign_root, &repo);
    let prepared = store.prepare_trigger_operation(command.clone()).unwrap();
    assert!(foreign.commit_trigger_operation(prepared).is_err());
    execute(&store, command);
    let snapshot = store.read_publication();
    let mut table = snapshot.http.data.clone();
    table.records.clear();
    assert!(crate::deployments::http::table::HttpTable::new(
        table,
        &store.http_budget,
        snapshot.transaction,
        snapshot.routes.generation.0
    )
    .is_err());
    drop(snapshot);
    drop(store);
    let file = roots[1].0.join("catalog.json");
    let mut value: json::Value = json::from_slice(&std::fs::read(&file).unwrap()).unwrap();
    value["payload"]["control"]["http_routes"]["receipts"][0]["actor"]["subject"] =
        json::json!("forged");
    let mut record: crate::deployments::persistence::Record = json::from_value(value).unwrap();
    record.checksum = latent_artifacts::content_digest(&json::to_vec(&record.payload).unwrap()).0;
    std::fs::write(&file, json::to_vec(&record).unwrap()).unwrap();
    assert!(run(Store::open_with_catalog(
        &roots[1].0,
        repo.clone(),
        Limits::default(),
        repo.lifecycle_authority(),
        super::super::lifecycle::profile("47.0.4")
    ))
    .is_err());
}
#[test]
fn http_interrupted_commit_and_uncertain_sync_preserve_whole_state() {
    let (roots, repo, store, _) = setup();
    let command = request(
        &store,
        "create",
        definition(&store, "alice", "browser", "web", "/", "prefix"),
        0,
    );
    let prepared = store.prepare_trigger_operation(command.clone()).unwrap();
    store.fail_before_rename.store(true, Ordering::SeqCst);
    assert!(store.commit_trigger_operation(prepared).is_err());
    assert!(get(&store, "alice", "browser").value().trigger.is_none());
    drop(store);
    let store = catalog(&roots[1], &repo);
    assert!(get(&store, "alice", "browser").value().trigger.is_none());
    let prepared = store.prepare_trigger_operation(command.clone()).unwrap();
    store.fail_parent_sync.store(true, Ordering::SeqCst);
    let receipt = store.commit_trigger_operation(prepared).unwrap();
    assert!(receipt.value().durability.is_err());
    assert!(get(&store, "alice", "browser").value().trigger.is_some());
    assert!(!get(&store, "alice", "browser").value().confirmed);
    assert!(selected(&store, "alice", "/").is_err());
    assert_eq!(
        store
            .get_trigger_operation(&TenantId("alice".into()), "create")
            .unwrap()
            .value(),
        &TriggerOperationLookup::Uncertain
    );
    drop(receipt);
    drop(store);
    let store = catalog(&roots[1], &repo);
    assert!(selected(&store, "alice", "/").is_ok());
    assert!(execute(&store, command).value().replayed);
}

fn page(tenant: &str, token: Option<String>) -> TriggerPageRequest {
    TriggerPageRequest {
        tenant: TenantId(tenant.into()),
        target_service: None,
        page_size: 1,
        page_token: token,
    }
}
#[test]
fn http_pages_receipt_eviction_and_read_owners_remain_bounded_and_scoped() {
    let (roots, repo, store, _) = setup();
    for id in ["a", "b"] {
        execute(
            &store,
            request(
                &store,
                id,
                definition(&store, "alice", id, "web", &format!("/{id}"), "exact"),
                0,
            ),
        );
    }
    let token = store
        .list_triggers(&page("alice", None))
        .unwrap()
        .value()
        .next_page_token
        .clone()
        .unwrap();
    assert_eq!(
        store
            .list_triggers(&page("alice", Some(token.clone())))
            .unwrap()
            .value()
            .triggers[0]
            .manifest
            .id
            .0,
        "b"
    );
    assert!(store
        .list_triggers(&page("bob", Some(token.clone())))
        .is_err());
    let mut forged = token.clone();
    forged.push('0');
    assert!(store.list_triggers(&page("alice", Some(forged))).is_err());
    let before = store.http_budget.used();
    let mut owners = Vec::new();
    while let Ok(read) = store.get_trigger(&TenantId("alice".into()), &TriggerId("a".into())) {
        owners.push(read);
        assert!(owners.len() <= 64);
    }
    assert!(store.http_budget.used() <= 8 * 1024 * 1024);
    drop(owners);
    assert_eq!(store.http_budget.used(), before);
    for n in 0..65 {
        let current = get(&store, "alice", "a");
        let value = current.value().trigger.as_ref().unwrap();
        let command = request(
            &store,
            &format!("update-{n}"),
            value.manifest.clone(),
            value.generation,
        );
        drop(current);
        execute(&store, command);
    }
    assert!(matches!(
        store
            .get_trigger_operation(&TenantId("alice".into()), "a")
            .unwrap()
            .value(),
        TriggerOperationLookup::Unknown {
            retained_floor: 4,
            ..
        }
    ));
    assert!(store
        .list_triggers(&page("alice", Some(token.clone())))
        .is_err());
    let token = store
        .list_triggers(&page("alice", None))
        .unwrap()
        .value()
        .next_page_token
        .clone()
        .unwrap();
    drop(store);
    let store = catalog(&roots[1], &repo);
    assert!(store.list_triggers(&page("alice", Some(token))).is_err());
}
