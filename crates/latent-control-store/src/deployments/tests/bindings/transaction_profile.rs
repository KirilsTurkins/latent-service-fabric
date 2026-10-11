use super::*;

#[test]
fn selected_transaction_import_keeps_the_ordinary_signed_clock_plan() {
    let fixture = Fixture::transactional();
    fixture.install();
    assert_eq!(fixture.store.binding_inventory().1, 1);
    assert_eq!(fixture.store.binding_inventory().2, 1);
    let revision = fixture
        .store
        .pin()
        .unwrap()
        .resolve(&target(), None)
        .unwrap();
    let plan = fixture.store.plan(&revision).unwrap();
    assert!(plan.matches_revision(&revision));
    plan.check_eligible().unwrap();
    fixture.provider.retire();
    assert!(plan.check_eligible().is_err());
    assert!(fixture.store.plan(&revision).is_err());
}

#[test]
fn selected_transaction_profile_cannot_bypass_an_ordinary_import_definition() {
    let fixture = Fixture::transactional();
    let before = fixture.store.generation();
    assert!(prepare(
        &fixture.store,
        fixture.broker.clone(),
        &fixture.provider,
        Vec::new(),
    )
    .is_err());
    assert_eq!(fixture.store.generation(), before);
    assert_eq!(fixture.store.binding_inventory().1, 0);
    assert_eq!(fixture.store.binding_inventory().2, 0);
}

#[test]
fn selected_transaction_binding_restart_uses_original_profile_and_current_provider() {
    let fixture = Fixture::transactional();
    fixture.install();
    let Fixture {
        store,
        releases,
        broker,
        provider,
        roots,
        authority: _,
        policies: _,
    } = fixture;
    drop(store);
    assert!(run(crate::DirectoryDeploymentRepository::open_with_catalog(
        &roots[1].0,
        releases.clone(),
        crate::DirectoryDeploymentRepositoryConfig::default(),
        releases.lifecycle_authority(),
        Arc::new(
            latent_manifest::RuntimeCompatibilityProfile::new(
                "wasmtime",
                "48.0.3",
                "x86_64-unknown-linux-gnu",
                &["x86_64.sse2"],
                64 * 1024 * 1024,
                100_000_000,
            )
            .unwrap()
        ),
    ))
    .is_err());
    let reopened = open_selected(&roots[1], &releases, package_fixture::transaction_profile());
    let definitions = reopened.binding_definitions().unwrap();
    reopened
        .commit_binding_update(prepare(&reopened, broker, &provider, definitions).unwrap())
        .unwrap();
    let revision = reopened.pin().unwrap().resolve(&target(), None).unwrap();
    reopened.plan(&revision).unwrap().check_eligible().unwrap();
}
