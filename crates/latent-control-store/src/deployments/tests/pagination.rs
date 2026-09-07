//! Small scoped fixtures verify paging work and response bounds directly.

use std::sync::atomic::Ordering;
use std::sync::Arc;

use latent_core::{DeploymentId, ReleaseDigest, RouteGeneration, ServiceId, TenantId};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_routing::{RouteCompiler, RouteSnapshotPublisher};

use super::super::pagination::instrumentation::PageProbe;
use super::fixtures::*;
use crate::{DeploymentPage, DeploymentPageRequest, DeploymentStore};

fn request(
    tenant: &str,
    service: Option<&str>,
    page_size: u32,
    token: Option<&str>,
) -> DeploymentPageRequest {
    DeploymentPageRequest {
        tenant: TenantId(tenant.to_owned()),
        service: service.map(|value| ServiceId(value.to_owned())),
        page_size,
        page_token: token.map(str::to_owned),
    }
}

fn release_for_service(releases: &Releases, service: &str) -> ReleaseDigest {
    // Give each service distinct component content and its own immutable metadata.
    let mut value = artifact(&format!("paging-{service}"));
    value.manifest.metadata.name = service.to_owned();
    let digest = value.descriptor.release_digest.clone();
    assert!(releases
        .values
        .write()
        .unwrap()
        .insert(digest.clone(), value)
        .is_none());
    digest
}

fn seeded(config: Limits) -> (TempRoot, Arc<Releases>, Store) {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let echo = release_for_service(&releases, "echo");
    let other = release_for_service(&releases, "other");
    let store = run(Store::open(root.0.clone(), releases.clone(), config)).unwrap();
    let values = [
        ("a-00", "alice", "echo"),
        ("a-01", "bob", "echo"),
        ("a-02", "alice", "other"),
        ("a-03", "alice", "echo"),
        ("a-04", "bob", "echo"),
        ("a-05", "alice", "other"),
        ("a-06", "alice", "echo"),
        ("a-07", "bob", "echo"),
        ("a-08", "carol", "echo"),
    ]
    .into_iter()
    .map(|(id, tenant, service)| {
        let release = if service == "echo" { &echo } else { &other };
        let mut value = deployment(id, tenant, release);
        value.service = ServiceId(service.to_owned());
        value
    })
    .collect();
    run(store.apply_many(values)).unwrap();
    (root, releases, store)
}

fn assert_ids(page: &DeploymentPage, expected: &[&str]) {
    let ids: Vec<_> = page
        .deployments
        .iter()
        .map(|record| record.manifest.id.0.as_str())
        .collect();
    assert_eq!(ids, expected);
}

fn assert_rejected_before_selection(
    store: &Store,
    request: DeploymentPageRequest,
    code: Code,
    reason: &str,
) {
    let probe = PageProbe::new();
    let failure = run(store.list_page(request)).expect_err("invalid page request");
    assert_eq!(failure.code, code);
    assert_eq!(failure.message, reason);
    assert_eq!(probe.stats().selected, 0);
    assert_eq!(probe.stats().cloned, 0);
}

#[test]
fn tenant_pages_follow_id_order_with_one_lookahead_and_only_selected_clones() {
    let (_root, releases, store) = seeded(Limits::default());
    let fetches = releases.fetches.load(Ordering::Relaxed);
    let mut token = None;
    for expected in [&["a-00", "a-02"][..], &["a-03", "a-05"], &["a-06"]] {
        let probe = PageProbe::new();
        let page = run(store.list_page(request("alice", None, 2, token.as_deref()))).unwrap();
        assert_ids(&page, expected);
        assert_eq!(page.catalog_generation, RouteGeneration(1));
        assert!(page.deployments.iter().all(|record| {
            record.generation == 1
                && record
                    .manifest
                    .metadata
                    .tenant
                    .as_ref()
                    .is_some_and(|tenant| tenant.0 == "alice")
        }));
        let lookahead = usize::from(page.next_page_token.is_some());
        assert_eq!(probe.stats().selected, expected.len() + lookahead);
        assert_eq!(probe.stats().cloned, expected.len());
        token = page.next_page_token;
    }
    assert!(token.is_none());
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
}

#[test]
fn service_pages_seek_the_scope_and_allow_a_different_continuation_size() {
    let (_root, releases, store) = seeded(Limits::default());
    let fetches = releases.fetches.load(Ordering::Relaxed);
    let first = {
        let probe = PageProbe::new();
        let page = store
            .list_deployment_page(&request("alice", Some("echo"), 1, None))
            .unwrap();
        assert_ids(&page, &["a-00"]);
        assert_eq!(probe.stats().selected, 2);
        assert_eq!(probe.stats().cloned, 1);
        page
    };
    let probe = PageProbe::new();
    let rest = run(store.list_page(request(
        "alice",
        Some("echo"),
        2,
        first.next_page_token.as_deref(),
    )))
    .unwrap();
    assert_ids(&rest, &["a-03", "a-06"]);
    assert!(rest.next_page_token.is_none());
    assert_eq!(probe.stats().selected, 2);
    assert_eq!(probe.stats().cloned, 2);
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
}

#[test]
fn missing_tenant_or_service_selects_and_clones_no_other_records() {
    let (_root, releases, store) = seeded(Limits::default());
    let fetches = releases.fetches.load(Ordering::Relaxed);
    for (tenant, service) in [("nobody", None), ("alice", Some("missing"))] {
        let probe = PageProbe::new();
        let page = run(store.list_page(request(tenant, service, 1, None))).unwrap();
        assert!(page.deployments.is_empty());
        assert!(page.next_page_token.is_none());
        assert_eq!(probe.stats().selected, 0);
        assert_eq!(probe.stats().cloned, 0);
    }
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
}

#[test]
fn invalid_sizes_and_scope_fail_before_selection_or_artifact_access() {
    let limits = Limits::default();
    let (_root, releases, store) = seeded(limits);
    let fetches = releases.fetches.load(Ordering::Relaxed);
    for size in [0, limits.max_page_size + 1] {
        assert_rejected_before_selection(
            &store,
            request("alice", None, size, None),
            Code::InvalidArgument,
            "invalid-deployment-page-size",
        );
    }
    let oversized = "x".repeat(limits.max_identifier_bytes + 1);
    for (tenant, service) in [
        ("", None),
        ("alice\n", None),
        (oversized.as_str(), None),
        ("alice", Some("")),
        ("alice", Some("echo\n")),
        ("alice", Some(oversized.as_str())),
    ] {
        assert_rejected_before_selection(
            &store,
            request(tenant, service, 1, None),
            Code::InvalidArgument,
            "invalid-deployment-page-scope",
        );
    }
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
}

#[test]
fn damaged_oversized_and_cross_scope_tokens_fail_before_selection() {
    let limits = Limits::default();
    let (_root, releases, store) = seeded(limits);
    let token = run(store.list_page(request("alice", Some("echo"), 1, None)))
        .unwrap()
        .next_page_token
        .unwrap();
    let mut damaged = token.clone().into_bytes();
    let last = damaged.last_mut().unwrap();
    *last = if *last == b'0' { b'1' } else { b'0' };
    let damaged = String::from_utf8(damaged).unwrap();
    let oversized = "x".repeat(64 + 6 * limits.max_identifier_bytes + 1);
    let fetches = releases.fetches.load(Ordering::Relaxed);
    for invalid in [
        "",
        "not-a-page",
        "d1:",
        damaged.as_str(),
        oversized.as_str(),
    ] {
        assert_rejected_before_selection(
            &store,
            request("alice", Some("echo"), 1, Some(invalid)),
            Code::InvalidArgument,
            "invalid-deployment-page-token",
        );
    }
    for (tenant, service) in [
        ("bob", Some("echo")),
        ("alice", Some("other")),
        ("alice", None),
    ] {
        assert_rejected_before_selection(
            &store,
            request(tenant, service, 1, Some(&token)),
            Code::InvalidArgument,
            "invalid-deployment-page-token",
        );
    }
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
}

#[test]
fn any_publication_expires_pages_without_changing_unrelated_object_versions() {
    let (_root, releases, store) = seeded(Limits::default());
    let first = run(store.list_page(request("alice", None, 1, None))).unwrap();
    let release = releases.add("two");
    run(store.apply(deployment("bob-new", "bob", &release))).unwrap();
    assert_rejected_before_selection(
        &store,
        request("alice", None, 1, first.next_page_token.as_deref()),
        Code::StateConflict,
        "expired-deployment-page-token",
    );
    let fresh = run(store.list_page(request("alice", None, 1, None))).unwrap();
    assert_eq!(fresh.catalog_generation, RouteGeneration(2));
    assert_eq!(fresh.deployments[0].generation, 1);
    let before = snapshot(&store);
    let next = run(RouteCompiler::compile(&store, Some(&before))).unwrap();
    run(RouteSnapshotPublisher::publish(&store, next)).unwrap();
    assert_rejected_before_selection(
        &store,
        request("alice", None, 1, fresh.next_page_token.as_deref()),
        Code::StateConflict,
        "expired-deployment-page-token",
    );
    let newest = run(store.list_page(request("alice", None, 1, None))).unwrap();
    assert_eq!(newest.catalog_generation, RouteGeneration(3));
    assert_eq!(newest.deployments[0].generation, 1);
}

#[test]
fn tokens_do_not_transfer_to_another_catalog_or_survive_reopen() {
    let (root, releases, store) = seeded(Limits::default());
    let token = run(store.list_page(request("alice", None, 1, None)))
        .unwrap()
        .next_page_token
        .unwrap();
    let (_other_root, _other_releases, other) = seeded(Limits::default());
    assert_rejected_before_selection(
        &other,
        request("alice", None, 1, Some(&token)),
        Code::InvalidArgument,
        "invalid-deployment-page-token",
    );
    drop(store);
    let reopened = open(&root, &releases);
    assert_rejected_before_selection(
        &reopened,
        request("alice", None, 1, Some(&token)),
        Code::InvalidArgument,
        "invalid-deployment-page-token",
    );
    let first = run(reopened.list_page(request("alice", None, 1, None))).unwrap();
    assert_ids(&first, &["a-00"]);
    assert_eq!(first.catalog_generation, RouteGeneration(1));
    assert_eq!(first.deployments[0].generation, 1);
}

#[test]
fn an_oversized_first_record_fails_before_cloning_instead_of_repeating_an_empty_page() {
    let limits = Limits {
        max_page_bytes: 1,
        ..Limits::default()
    };
    let (_root, releases, store) = seeded(limits);
    let fetches = releases.fetches.load(Ordering::Relaxed);
    let probe = PageProbe::new();
    let failure = run(store.list_page(request("alice", None, 1, None))).unwrap_err();
    assert_eq!(failure.code, Code::ResourceExhausted);
    assert_eq!(failure.message, "deployment-page-byte-limit");
    assert_eq!(probe.stats().selected, 1);
    assert_eq!(probe.stats().cloned, 0);
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
}

#[test]
fn exact_record_byte_budget_returns_a_cursor_before_the_uncloned_next_record() {
    let (root, releases, store) = seeded(Limits::default());
    let manifest = run(DeploymentStore::get(
        &store,
        &DeploymentId("a-00".to_owned()),
    ))
    .unwrap()
    .unwrap();
    let bytes = JsonManifestCodec::default()
        .encode_deployment(&manifest)
        .unwrap();
    // Construct the documented compact record independently of cached accounting.
    let encoded_record = format!(
        "{{\"manifest\":{},\"generation\":1}}",
        String::from_utf8(bytes).unwrap()
    );
    let limits = Limits {
        max_page_bytes: encoded_record.len(),
        ..Limits::default()
    };
    drop(store);
    let store = run(Store::open(root.0.clone(), releases.clone(), limits)).unwrap();
    let fetches = releases.fetches.load(Ordering::Relaxed);
    let mut token = None;
    for expected in ["a-00", "a-03", "a-06"] {
        let probe = PageProbe::new();
        let page =
            run(store.list_page(request("alice", Some("echo"), 10, token.as_deref()))).unwrap();
        assert_ids(&page, &[expected]);
        assert_eq!(probe.stats().cloned, 1);
        assert_eq!(
            probe.stats().selected,
            1 + usize::from(page.next_page_token.is_some())
        );
        token = page.next_page_token;
    }
    assert!(token.is_none());
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
    drop(store);
    let store = run(Store::open(
        root.0.clone(),
        releases.clone(),
        Limits {
            max_page_bytes: encoded_record.len() - 1,
            ..limits
        },
    ))
    .unwrap();
    let probe = PageProbe::new();
    let failure = run(store.list_page(request("alice", Some("echo"), 1, None))).unwrap_err();
    assert_eq!(failure.code, Code::ResourceExhausted);
    assert_eq!(failure.message, "deployment-page-byte-limit");
    assert_eq!(probe.stats().selected, 1);
    assert_eq!(probe.stats().cloned, 0);
}

#[test]
fn maximum_length_tenant_service_and_ids_produce_usable_bounded_tokens() {
    let limits = Limits {
        max_identifier_bytes: 32,
        ..Limits::default()
    };
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let tenant = "t".repeat(limits.max_identifier_bytes);
    let service = "s".repeat(limits.max_identifier_bytes);
    let release = release_for_service(&releases, &service);
    let store = run(Store::open(root.0.clone(), releases.clone(), limits)).unwrap();
    let ids = ["a", "b"].map(|prefix| prefix.repeat(limits.max_identifier_bytes));
    let values = ids
        .iter()
        .map(|id| {
            let mut value = deployment(id, &tenant, &release);
            value.service = ServiceId(service.clone());
            value
        })
        .collect();
    run(store.apply_many(values)).unwrap();
    let fetches = releases.fetches.load(Ordering::Relaxed);
    let first = run(store.list_page(request(&tenant, Some(&service), 1, None))).unwrap();
    assert_ids(&first, &[&ids[0]]);
    let token = first.next_page_token.unwrap();
    assert!(token.len() <= 64 + 6 * limits.max_identifier_bytes);
    let probe = PageProbe::new();
    let second = run(store.list_page(request(&tenant, Some(&service), 1, Some(&token)))).unwrap();
    assert_ids(&second, &[&ids[1]]);
    assert!(second.next_page_token.is_none());
    assert_eq!(probe.stats().selected, 1);
    assert_eq!(probe.stats().cloned, 1);
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
}
