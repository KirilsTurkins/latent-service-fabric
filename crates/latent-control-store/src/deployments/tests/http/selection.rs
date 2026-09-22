use super::*;
#[test]
fn http_exact_prefix_precedence_canonical_conflicts_and_no_stale_fallback() {
    let (_roots, _repo, store, publication) = setup();
    for (id, path, kind) in [
        ("root", "/", "prefix"),
        ("api", "/api", "prefix"),
        ("exact", "/api", "exact"),
    ] {
        execute(
            &store,
            request(
                &store,
                id,
                definition(&store, "alice", id, "web", path, kind),
                0,
            ),
        );
    }
    assert_eq!(
        selected(&store, "alice", "/api?x=1").unwrap().trigger().0,
        "exact"
    );
    assert_eq!(
        selected(&store, "alice", "/api/x").unwrap().trigger().0,
        "api"
    );
    assert_eq!(
        selected(&store, "alice", "/apis").unwrap().trigger().0,
        "root"
    );
    let mut alias = definition(&store, "alice", "alias", "web", "/%61pi", "exact");
    alias
        .configuration
        .insert("host".into(), json::json!("ALICE.EXAMPLE.TEST:443"));
    assert!(store
        .prepare_trigger_operation(request(&store, "alias", alias, 0))
        .is_err());
    deploy(&store, &publication, "broad");
    let old = get(&store, "alice", "root")
        .value()
        .trigger
        .as_ref()
        .unwrap()
        .generation;
    execute(
        &store,
        request(
            &store,
            "retarget-root",
            definition(&store, "alice", "root", "broad", "/", "prefix"),
            old,
        ),
    );
    let existing = run(store.get(&DeploymentId("web".into())))
        .unwrap()
        .unwrap();
    let held = selected(&store, "alice", "/api").unwrap();
    run(store.delete(&existing.id)).unwrap();
    run(store.apply(existing)).unwrap();
    assert!(selected(&store, "alice", "/api").is_err());
    assert_eq!(
        selected(&store, "alice", "/other").unwrap().trigger().0,
        "root"
    );
    held.catalog().unwrap().admission_policy(held.revision().unwrap()).unwrap();
    let target = CanonicalTarget::parse(Scheme::Https, "alice.example.test", "/other").unwrap();
    assert!(store.select_http(&target, Method::Head).is_err());
}

#[test]
fn http_prepared_mutation_fences_deployment_edits_and_revocation() {
    let (roots, repo, store, publication) = setup();
    let definition = definition(&store, "alice", "browser", "web", "/", "prefix");
    let prepared = store
        .prepare_trigger_operation(request(&store, "raced", definition.clone(), 0))
        .unwrap();
    deploy(&store, &publication, "unrelated");
    assert!(store.commit_trigger_operation(prepared).is_err());
    assert!(get(&store, "alice", "browser").value().trigger.is_none());
    let prepared = store
        .prepare_trigger_operation(request(&store, "revoked", definition, 0))
        .unwrap();
    repo.change_publication_lifecycle(
        publication_context("alice", "revoke", 1),
        &PublicationSelector::Publication(publication),
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    )
    .unwrap();
    assert!(store.commit_trigger_operation(prepared).is_err());
    assert!(get(&store, "alice", "browser").value().trigger.is_none());
    assert!(!std::fs::read(roots[1].0.join("catalog.json"))
        .unwrap()
        .is_empty());
}

#[test]
fn http_publications_sharing_bytes_and_tenants_keep_independent_routes_and_revocation() {
    let (roots, repo, store, first) = setup();
    let corrected = publish(&repo, "alice", "corrected");
    let bob = publish(&repo, "bob", "first");
    deploy(&store, &corrected, "corrected");
    deploy(&store, &bob, "bob-web");
    for (tenant, deployment, path) in [
        ("alice", "web", "/old"),
        ("alice", "corrected", "/new"),
        ("bob", "bob-web", "/"),
    ] {
        execute(
            &store,
            request(
                &store,
                deployment,
                definition(&store, tenant, deployment, deployment, path, "prefix"),
                0,
            ),
        );
    }
    let mut foreign = definition(&store, "bob", "collision", "bob-web", "/disjoint", "exact");
    foreign
        .configuration
        .insert("host".into(), json::json!("alice.example.test"));
    assert!(store
        .prepare_trigger_operation(request(&store, "collision", foreign, 0))
        .is_err());
    let held = selected(&store, "alice", "/old").unwrap();
    repo.change_publication_lifecycle(
        publication_context("alice", "revoke", 1),
        &PublicationSelector::Publication(first),
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    )
    .unwrap();
    assert!(held.catalog().unwrap().admission_policy(held.revision().unwrap()).is_err());
    assert!(selected(&store, "alice", "/old").is_err());
    assert_eq!(
        selected(&store, "alice", "/new")
            .unwrap()
            .revision()
            .unwrap()
            .publication
            .as_ref(),
        Some(&corrected.id)
    );
    assert_eq!(
        selected(&store, "bob", "/")
            .unwrap()
            .revision()
            .unwrap()
            .publication
            .as_ref(),
        Some(&bob.id)
    );
    drop(held);
    drop(store);
    let store = catalog(&roots[1], &repo);
    assert!(selected(&store, "alice", "/old").is_err());
    assert!(selected(&store, "alice", "/new").is_ok());
    let generation = get(&store, "alice", "web")
        .value()
        .trigger
        .as_ref()
        .unwrap()
        .generation;
    delete(&store, "remove-revoked", "alice", "web", generation);
}
