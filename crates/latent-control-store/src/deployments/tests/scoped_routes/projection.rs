use super::*;
use latent_core::{BindingId, ContractId, ServiceId};
use latent_manifest::BindingMode;
use latent_routing::BindingRoute;

#[test]
fn copied_metadata_discards_source_slack_but_injected_output_slack_is_rejected() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("copy-capacity");
    let store = open(&root, &releases);
    run(store.apply(deployment("blue", "alice", &digest))).unwrap();
    {
        let mut current = store.current.write().unwrap();
        let catalog = Arc::get_mut(&mut current).unwrap();
        let record = Arc::get_mut(&mut catalog.records[0]).unwrap();
        let mut slack = String::with_capacity(256 * 1024);
        slack.push('x');
        record.attributes.insert("capacity".to_owned(), slack);
    }
    let mut query = request("alice");
    query.limits.maximum_services = 2;
    query.limits.maximum_revisions = 2;
    let limits = query.limits;
    let selected = run(store.scoped(query)).unwrap();
    assert_eq!(selected.snapshot.services.capacity(), 2);
    for route in &selected.snapshot.services {
        assert_eq!(route.revisions.capacity(), 1);
        let copied = &route.revisions[0].attributes["capacity"];
        assert_eq!(copied, "x");
        assert_eq!(copied.capacity(), copied.len());
    }
    selected.validate(limits).unwrap();
    let mut injected = selected;
    injected.snapshot.services[0].revisions[0]
        .attributes
        .get_mut("capacity")
        .unwrap()
        .reserve(256 * 1024);
    assert_eq!(
        injected.validate(request("alice").limits).unwrap_err().code,
        Code::ResourceExhausted
    );
}

#[test]
fn moved_request_tenant_capacity_is_included_in_returned_cost() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let plain = run(store.scoped(request("alice"))).unwrap();
    let mut query = request("alice");
    let mut tenant = String::with_capacity(4096);
    tenant.push_str("alice");
    let extra = tenant.capacity() - plain.tenant.0.capacity();
    query.tenant = TenantId(tenant);
    let limits = query.limits;
    let moved = run(store.scoped(query)).unwrap();
    assert_eq!(moved.retained_bytes, plain.retained_bytes + extra);
    assert_eq!(moved.snapshot_digest, plain.snapshot_digest);
    moved.validate(limits).unwrap();
}

#[test]
fn borrowed_snapshot_equality_checks_every_public_dimension_without_projection() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("equal-projection");
    let store = open(&root, &releases);
    run(store.apply_many(vec![
        deployment("blue", "alice", &digest),
        deployment("green", "alice", &digest),
    ]))
    .unwrap();
    let catalog = store.read_catalog();
    let original = catalog.snapshot();
    assert!(catalog.matches_snapshot(&original));
    for damage in 0..14 {
        let mut changed = original.clone();
        match damage {
            0 => changed.generation.0 += 1,
            1 => changed.generated_at_unix_millis += 1,
            2 => {
                changed.services.pop();
            }
            3 => changed.services.swap(0, 1),
            4 => changed.services[0].id.0.push('x'),
            5 => changed.services[0].tenant.0.push('x'),
            6 => changed.services[0].service.0.push('x'),
            7 => {
                changed.services[0].revisions.pop();
            }
            8 => changed.services[0].revisions[0].revision.0.push('x'),
            9 => changed.services[0].revisions[0].release.0.push('x'),
            10 => changed.services[0].revisions[0].weight += 1,
            11 => {
                changed.services[0].revisions[0]
                    .attributes
                    .insert("extra".to_owned(), "x".to_owned());
            }
            12 => changed.policy_digests.push("foreign".to_owned()),
            _ => changed.bindings.push(binding()),
        }
        assert!(!catalog.matches_snapshot(&changed), "dimension {damage}");
    }
    let mut reversed = original;
    reversed
        .services
        .iter_mut()
        .find(|route| route.id.0 == "default")
        .unwrap()
        .revisions
        .reverse();
    assert!(!catalog.matches_snapshot(&reversed));
}

fn binding() -> BindingRoute {
    BindingRoute {
        id: BindingId("foreign".to_owned()),
        consumer_tenant: TenantId("alice".to_owned()),
        consumer_service: ServiceId("echo".to_owned()),
        imported_contract: ContractId(CONTRACT.to_owned()),
        provider_tenant: TenantId("alice".to_owned()),
        provider_service: ServiceId("echo".to_owned()),
        provider_contract: ContractId(CONTRACT.to_owned()),
        mode: BindingMode::IsolatedLocal,
        policy_digest: "foreign".to_owned(),
    }
}
