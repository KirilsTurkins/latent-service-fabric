//! Checked packages and real catalog/policy ownership; no guest execution.
mod fixture;
mod inspection;
mod local;
#[path = "../../../../latent-packaging/tests/fixtures/mod.rs"]
mod package_fixture;
mod publications;
mod rejections;
use fixture::*;
use latent_capabilities::broker::CapabilityPlanSource;
use latent_routing::{RouteCompiler, RouteResolver, RouteSnapshotPublisher};

#[test]
fn exact_host_plan_is_durable_and_old_pins_keep_original_data() {
    let f = Fixture::new();
    f.install();
    let old = f.store.pin().unwrap();
    let revision = old.resolve(&target(), None).unwrap();
    let plan = f.store.plan(&revision).unwrap();
    assert_eq!(f.store.binding_inventory().1, 1);
    let snapshot = run(RouteCompiler::compile(
        &f.store,
        Some(&run(latent_routing::RouteSnapshotSource::current(&f.store)).unwrap()),
    ))
    .unwrap();
    run(f.store.publish(snapshot)).unwrap();
    assert!(f.store.plan(&revision).is_ok());
    assert!(plan.matches_revision(&revision));
    drop(plan);
    drop(old);
    assert!(f.store.plan(&revision).is_err());
    let data = std::fs::read(f.roots[1].0.join("catalog.json")).unwrap();
    let json: serde_json::Value = serde_json::from_slice(&data).unwrap();
    assert_eq!(json["format_version"], 6);
    assert_eq!(
        json["payload"]["capability_bindings"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    let Fixture {
        store,
        releases,
        broker,
        provider,
        policies: _,
        roots,
    } = f;
    drop(store);
    let reopened = open(&roots[1], &releases);
    assert_eq!(reopened.binding_inventory().1, 1);
    assert_eq!(reopened.binding_inventory().2, 0);
    let current = reopened.pin().unwrap().resolve(&target(), None).unwrap();
    assert!(reopened.plan(&current).is_err());
    let prepared = prepare(
        &reopened,
        broker,
        &provider,
        reopened.binding_definitions().unwrap(),
    )
    .unwrap();
    reopened.commit_binding_update(prepared).unwrap();
    let current = reopened.pin().unwrap().resolve(&target(), None).unwrap();
    assert!(reopened.plan(&current).is_ok());
}

#[test]
fn policy_change_between_prepare_and_commit_cannot_publish_stale_binding() {
    let f = Fixture::new();
    let before = f.store.generation();
    let prepared = prepare(&f.store, f.broker.clone(), &f.provider, vec![definition()]).unwrap();
    f.replace_policy();
    assert!(f.store.commit_binding_update(prepared).is_err());
    assert_eq!(f.store.generation(), before);
    assert_eq!(f.store.binding_inventory().1, 0);
    f.install();
    assert_eq!(f.store.binding_inventory().2, 1);
}

#[test]
fn manual_route_publication_wins_against_older_prepared_bindings() {
    let f = Fixture::new();
    let prepared = prepare(&f.store, f.broker.clone(), &f.provider, vec![definition()]).unwrap();
    let previous = run(latent_routing::RouteSnapshotSource::current(&f.store)).unwrap();
    let next = run(RouteCompiler::compile(&f.store, Some(&previous))).unwrap();
    run(f.store.publish(next)).unwrap();
    let current = f.store.generation();
    assert!(f.store.commit_binding_update(prepared).is_err());
    assert_eq!(f.store.generation(), current);
    assert_eq!(f.store.binding_inventory().1, 0);
}

#[test]
fn retiring_installation_denies_retained_plans_without_erasing_definitions() {
    let f = Fixture::new();
    f.install();
    let revision = f.store.pin().unwrap().resolve(&target(), None).unwrap();
    let plan = f.store.plan(&revision).unwrap();
    f.provider.retire();
    assert!(plan.check_eligible().is_err());
    assert!(f.store.plan(&revision).is_err());
    assert_eq!(f.store.binding_definitions().unwrap().len(), 1);
}
