use std::collections::BTreeMap;
use std::future::Future;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::task::{Context, Poll, Waker};

use latent_core::{PlatformError, RouteGeneration};
use latent_manifest::DeploymentManifest;

use super::super::{
    compile_versioned, index::IndexBudget, reuse, CompiledCatalog,
    DirectoryDeploymentRepositoryConfig,
};
use super::fixtures::*;
use crate::deployments::{observation::Work, persistence::EncodedCatalog};

fn sealed(
    releases: &Releases,
    desired: &[DeploymentManifest],
    generation: u64,
    previous: Option<&CompiledCatalog>,
    config: DirectoryDeploymentRepositoryConfig,
) -> Result<EncodedCatalog, PlatformError> {
    let deployments = desired
        .iter()
        .cloned()
        .map(|manifest| (manifest.id.clone(), Arc::new(manifest)))
        .collect::<BTreeMap<_, _>>();
    let versions = deployments
        .keys()
        .map(|id| (id.clone(), generation))
        .collect();
    let mut work = Work::default();
    let future = compile_versioned(
        deployments,
        versions,
        RouteGeneration(generation),
        generation * 10,
        releases,
        config,
        previous,
        &mut work,
    );
    let mut future = std::pin::pin!(future);
    match future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
    {
        Poll::Ready(result) => result,
        Poll::Pending => panic!("finite fixture must be ready"),
    }
}

fn parity(
    releases: &Releases,
    desired: &[DeploymentManifest],
    generation: u64,
    previous: &CompiledCatalog,
) -> CompiledCatalog {
    let config = DirectoryDeploymentRepositoryConfig::default();
    let incremental = sealed(releases, desired, generation, Some(previous), config).unwrap();
    let reference = sealed(releases, desired, generation, None, config).unwrap();
    assert_eq!(
        incremental.bytes(),
        reference.bytes(),
        "canonical file and checksum"
    );
    for manifest in desired {
        for route in [None, Some(manifest.id.0.as_str())] {
            let mut request = target(&manifest.metadata.tenant.as_ref().unwrap().0, route);
            request.service = manifest.service.clone();
            for key in ["", "zero", "one", "two", "three", "weighted-key"] {
                assert_eq!(
                    incremental.catalog().resolve(&request, Some(key), config),
                    reference.catalog().resolve(&request, Some(key), config)
                );
            }
        }
    }
    incremental.into_catalog()
}

#[test]
fn earlier_id_insert_delete_weight_and_recreate_match_fresh_bytes_and_route_positions() {
    let releases = Releases::default();
    let digest = releases.add("one");
    let blue = deployment("middle", "alice", &digest);
    let green = deployment("z-last", "bob", &digest);
    let peer = deployment("peer", "alice", &digest);
    let mut desired = vec![blue.clone(), peer, green];
    let original = sealed(
        &releases,
        &desired,
        1,
        None,
        DirectoryDeploymentRepositoryConfig::default(),
    )
    .unwrap()
    .into_catalog();
    assert!(original.reuse.is_some());
    let request = target("bob", Some("z-last"));
    let pinned = original
        .resolve(
            &request,
            Some("one"),
            DirectoryDeploymentRepositoryConfig::default(),
        )
        .unwrap();
    desired.push(deployment("a-first", "charlie", &digest));
    let inserted = parity(&releases, &desired, 2, &original);
    assert!(Arc::ptr_eq(
        original
            .record_by_id(&latent_core::DeploymentId("z-last".to_owned()))
            .unwrap(),
        inserted
            .record_by_id(&latent_core::DeploymentId("z-last".to_owned()))
            .unwrap()
    ));
    desired[0].route_weight = 7;
    let weighted = parity(&releases, &desired, 3, &inserted);
    desired.retain(|manifest| manifest.id != blue.id);
    let deleted = parity(&releases, &desired, 4, &weighted);
    desired.push(blue);
    let recreated = parity(&releases, &desired, 5, &deleted);
    assert_eq!(recreated.records.len(), 4);
    assert_eq!(
        original
            .resolve(
                &request,
                Some("one"),
                DirectoryDeploymentRepositoryConfig::default()
            )
            .unwrap(),
        pinned
    );
}

#[test]
fn reused_default_scope_keeps_endpoint_subsets_separate_from_all_route_members() {
    let releases = Releases::default();
    let first = releases.add("first");
    let second = releases.add("second");
    let extra = latent_core::ContractId("example:extra/api@1.0.0".to_owned());
    {
        let mut values = releases.values.write().unwrap();
        let artifact = values.get_mut(&second).unwrap();
        artifact.manifest.exports[0].contract = extra.clone();
        artifact.contracts[0].id = extra.clone();
        artifact.contracts[0].package_name = "example:extra".to_owned();
    }
    let mut desired = vec![
        deployment("blue", "alice", &first),
        deployment("green", "alice", &second),
    ];
    let old = compile(&releases, desired.clone(), 1, None).unwrap();
    desired.push(deployment("a-first", "bob", &first));
    let current = parity(&releases, &desired, 2, &old);
    let config = DirectoryDeploymentRepositoryConfig::default();
    let mut request = target("alice", None);
    request.contract = extra;
    assert_eq!(
        current
            .resolve(&request, Some("key"), config)
            .unwrap()
            .release,
        second
    );
    request.route = Some("blue".to_owned());
    assert_eq!(
        current.resolve(&request, None, config).unwrap_err().message,
        "contract-or-function-not-exported"
    );
    assert_eq!(
        current
            .tenant_routes(&latent_core::TenantId("alice".to_owned()))
            .find(|route| route.id() == "default")
            .unwrap()
            .revisions()
            .len(),
        2
    );
}

#[test]
fn irrelevant_verified_metadata_refreshes_generation_stamp_without_owning_it_in_record() {
    let releases = Releases::default();
    let digest = releases.add("one");
    let desired = vec![deployment("blue", "alice", &digest)];
    let old = compile(&releases, desired.clone(), 1, None).unwrap();
    releases
        .values
        .write()
        .unwrap()
        .get_mut(&digest)
        .unwrap()
        .descriptor
        .annotations
        .insert("note".to_owned(), "fresh".to_owned());
    let new = parity(&releases, &desired, 2, &old);
    assert!(Arc::ptr_eq(&old.records[0], &new.records[0]));
    let fresh = releases.values.read().unwrap()[&digest].clone();
    let stamp = latent_artifacts::preparation_metadata_fingerprint(
        &fresh.descriptor,
        &fresh.manifest,
        &fresh.contracts,
        512 * 1024,
        64,
    )
    .unwrap();
    assert!(reuse::prior_release(Some(&old), &digest, Some(stamp)).is_none());
    assert!(reuse::prior_release(Some(&new), &digest, Some(stamp)).is_some());
    assert_eq!(releases.fetches.load(Ordering::Relaxed), 3);
}

#[test]
fn absent_memo_and_changed_limits_preserve_the_full_reference_contract() {
    let releases = Releases::default();
    let digest = releases.add("one");
    let desired = vec![deployment("blue", "alice", &digest)];
    let mut old = compile(&releases, desired.clone(), 9, None).unwrap();
    old.reuse = None;
    let current = parity(&releases, &desired, 10, &old);
    assert_eq!(current.versions[&desired[0].id], 10);
    let mut config = DirectoryDeploymentRepositoryConfig::default();
    config.max_routing_key_bytes -= 1;
    assert!(reuse::compatible(Some(&current), config).is_none());
    let changed = sealed(&releases, &desired, 11, Some(&current), config).unwrap();
    let reference = sealed(&releases, &desired, 11, None, config).unwrap();
    assert_eq!(changed.bytes(), reference.bytes());
}

#[test]
fn optional_stamp_retention_cannot_exhaust_the_acceptance_budget() {
    let releases = Releases::default();
    let digest = releases.add("one");
    let catalog = compile(
        &releases,
        vec![deployment("blue", "alice", &digest)],
        1,
        None,
    )
    .unwrap();
    let artifact = releases.values.read().unwrap()[&digest].clone();
    let fingerprint = latent_artifacts::preparation_metadata_fingerprint(
        &artifact.descriptor,
        &artifact.manifest,
        &artifact.contracts,
        512 * 1024,
        64,
    )
    .unwrap();
    for available in [0, 1, 32] {
        let mut memo = reuse::MemoBuilder::new(1, DirectoryDeploymentRepositoryConfig::default());
        memo.push(super::super::RecordIndex(0), Some(fingerprint));
        let mut remaining = available;
        assert!(memo
            .finish(
                DirectoryDeploymentRepositoryConfig::default(),
                &mut remaining
            )
            .is_none());
        assert_eq!(remaining, available);
    }
    assert_eq!(catalog.records.len(), 1);
}

#[test]
fn index_charge_preserves_default_then_named_byte_and_entry_error_precedence() {
    let releases = Releases::default();
    let digest = releases.add("one");
    let catalog = compile(
        &releases,
        vec![deployment("blue", "alice", &digest)],
        1,
        None,
    )
    .unwrap();
    let record = &catalog.records[0];
    let attributes = record.attributes.values().map(String::len).sum::<usize>();
    for (bytes, entries, message) in [
        (attributes - 1, 0, "catalog-state-byte-limit"),
        (attributes, 0, "route-index-limit"),
        (attributes, 1, "catalog-state-byte-limit"),
        (2 * attributes, 1, "route-index-limit"),
    ] {
        let mut config = DirectoryDeploymentRepositoryConfig::default();
        config.max_route_entries = entries;
        let mut remaining = bytes;
        assert_eq!(
            IndexBudget::default()
                .charge_record(record, 1, config, &mut remaining)
                .unwrap_err()
                .message,
            message
        );
    }
    let mut config = DirectoryDeploymentRepositoryConfig::default();
    config.max_route_entries = 2;
    let mut remaining = attributes * 2;
    IndexBudget::default()
        .charge_record(record, 1, config, &mut remaining)
        .unwrap();
    assert_eq!(remaining, 0);
}

#[test]
fn missing_clean_mapping_rebuilds_before_appending_any_partial_scope() {
    let releases = Releases::default();
    let digest = releases.add("one");
    let desired = vec![
        deployment("blue", "alice", &digest),
        deployment("green", "alice", &digest),
    ];
    let old = compile(&releases, desired.clone(), 1, None).unwrap();
    let mut current = compile(&releases, desired, 2, Some(&old)).unwrap();
    let before = current.snapshot();
    let packed = super::super::packing::missing_mapping(&old, &current.records).unwrap();
    current.routes = packed.routes;
    current.route_revisions = packed.route_revisions;
    current.endpoints = packed.endpoints;
    current.candidates = packed.candidates;
    assert_eq!(current.snapshot(), before);
}

#[cfg(feature = "catalog-observation")]
#[test]
fn equal_records_bypass_derivations_but_still_fetch_and_remap_each_membership() {
    use crate::deployments::observation::{CatalogWorkObserver, CatalogWorkOperation, Source};
    let releases = Releases::default();
    let digest = releases.add("one");
    let desired = vec![
        deployment("blue", "alice", &digest),
        deployment("green", "alice", &digest),
    ];
    let old = compile(&releases, desired.clone(), 1, None).unwrap();
    let observer = CatalogWorkObserver::new();
    let mut work = Source::observed(observer.clone()).begin(CatalogWorkOperation::ApplyVersioned);
    let deployments = desired
        .into_iter()
        .map(|manifest| (manifest.id.clone(), Arc::new(manifest)))
        .collect::<BTreeMap<_, _>>();
    let versions = deployments.keys().map(|id| (id.clone(), 2)).collect();
    let future = compile_versioned(
        deployments,
        versions,
        RouteGeneration(2),
        20,
        &releases,
        DirectoryDeploymentRepositoryConfig::default(),
        Some(&old),
        &mut work,
    );
    let result = {
        let mut future = std::pin::pin!(future);
        match future
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
        {
            Poll::Ready(result) => result,
            Poll::Pending => panic!("ready fixture"),
        }
    };
    work.finish(&result);
    drop(work);
    let current = result.unwrap();
    let counts = observer.snapshot().last.unwrap().counts;
    assert_eq!(
        (
            counts.compiler_calls,
            counts.compiler_deployment_encodes,
            counts.revision_identity_encodes,
            counts.contract_schema_encodes
        ),
        (1, 0, 0, 0)
    );
    assert_eq!(
        (
            counts.record_derivations,
            counts.record_payload_reuses,
            counts.record_derivation_reuses
        ),
        (0, 2, 2)
    );
    assert_eq!(
        (
            counts.scopes_staged,
            counts.scope_content_reuses,
            counts.route_memberships_staged,
            counts.route_memberships_remapped
        ),
        (0, 1, 0, 4)
    );
    assert_eq!(releases.fetches.load(Ordering::Relaxed), 2);
    assert!(Arc::ptr_eq(&old.records[0], &current.catalog().records[0]));
}
