use super::*;
use crate::{RouteReadLimits, ScopedRouteRequest};

fn request(tenant: &str) -> ScopedRouteRequest {
    ScopedRouteRequest {
        tenant: TenantId(tenant.to_owned()),
        generation: None,
        limits: RouteReadLimits {
            maximum_services: 8,
            maximum_revisions: 8,
            maximum_attributes_per_revision: 32,
            maximum_string_bytes: 4096,
            maximum_bytes: 128 * 1024,
        },
    }
}

#[test]
fn projection_reads_only_selected_tenant_and_preserves_restart_identity() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("scoped");
    let store = open(&root, &releases);
    for tenant in ["alice", "bob", "carol"] {
        run(store.apply(deployment(tenant, tenant, &digest))).unwrap();
    }
    let before = releases.fetches.load(Ordering::Relaxed);
    let selected = run(store.scoped(request("bob"))).unwrap();
    assert_eq!(selected.snapshot.services.len(), 2);
    assert!(selected
        .snapshot
        .services
        .iter()
        .all(|service| service.tenant.0 == "bob"));
    assert_eq!(selected.snapshot.generation, store.generation());
    selected.validate(request("bob").limits).unwrap();
    assert_eq!(releases.fetches.load(Ordering::Relaxed), before);
    drop(store);
    let reopened = open(&root, &releases);
    assert_eq!(run(reopened.scoped(request("bob"))).unwrap(), selected);
}

#[test]
fn empty_tenant_projections_have_distinct_scoped_digests() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let alice = run(store.scoped(request("alice"))).unwrap();
    let bob = run(store.scoped(request("bob"))).unwrap();
    assert!(alice.snapshot.services.is_empty());
    assert_eq!(alice.snapshot, bob.snapshot);
    assert_ne!(alice.snapshot_digest, bob.snapshot_digest);
    let mut old = request("alice");
    old.generation = Some(RouteGeneration(1));
    assert_code(run(store.scoped(old)), Code::NotFound);
}

#[test]
fn selected_capacity_limits_do_not_visit_unrelated_revision_metadata() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("bounded");
    let store = open(&root, &releases);
    for tenant in ["alice", "bob"] {
        run(store.apply(deployment(tenant, tenant, &digest))).unwrap();
    }
    {
        let mut current = store.current.write().unwrap();
        let catalog = Arc::get_mut(&mut current).unwrap();
        let mut oversized = String::with_capacity(256 * 1024);
        oversized.push('x');
        catalog
            .snapshot
            .services
            .iter_mut()
            .find(|service| service.tenant.0 == "bob")
            .unwrap()
            .revisions[0]
            .attributes
            .insert("large".to_owned(), oversized);
    }
    let mut alice = request("alice");
    alice.limits.maximum_services = 2;
    alice.limits.maximum_revisions = 2;
    let selected = run(store.scoped(alice)).unwrap();
    assert_eq!(selected.snapshot.services.len(), 2);
    assert_code(run(store.scoped(request("bob"))), Code::ResourceExhausted);
}

#[test]
fn projection_bounds_and_digest_cover_returned_values() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("integrity");
    let store = open(&root, &releases);
    run(store.apply(deployment("blue", "alice", &digest))).unwrap();
    let query = request("alice");
    let selected = run(store.scoped(query.clone())).unwrap();
    let mut exact = query.clone();
    exact.limits.maximum_bytes = selected.retained_bytes;
    assert!(run(store.scoped(exact.clone())).is_ok());
    exact.limits.maximum_bytes -= 1;
    assert_code(run(store.scoped(exact)), Code::ResourceExhausted);
    for field in 0..4 {
        let mut damaged = selected.clone();
        match field {
            0 => damaged.snapshot.generated_at_unix_millis += 1,
            1 => damaged.snapshot.services[0].revisions[0].weight += 1,
            2 => damaged.snapshot.services[0].revisions[0]
                .release
                .0
                .push('0'),
            _ => damaged.tenant = TenantId("bob".to_owned()),
        }
        assert!(damaged.validate(query.limits).is_err());
    }
    let mut old = query;
    old.generation = Some(RouteGeneration(0));
    assert_code(run(store.scoped(old)), Code::NotFound);
}

#[test]
fn revision_count_and_attribute_count_are_checked_before_projection() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("counts");
    let store = open(&root, &releases);
    run(store.apply(deployment("blue", "alice", &digest))).unwrap();
    let mut second = deployment("green", "alice", &digest);
    second.route_weight = 1;
    run(store.apply(second)).unwrap();
    let mut limited = request("alice");
    limited.limits.maximum_revisions = 1;
    assert_code(run(store.scoped(limited)), Code::ResourceExhausted);
    let mut limited = request("alice");
    limited.limits.maximum_attributes_per_revision = 1;
    assert_code(run(store.scoped(limited)), Code::ResourceExhausted);
}
