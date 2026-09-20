//! Bounded production-path correctness. This fixture makes no RSS qualification.

use std::fs;
use std::sync::Arc;
use std::time::Instant;

use latent_artifacts::{
    content_digest, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig,
};
use latent_core::{ReleaseDigest, RouteGeneration};
use latent_manifest::DeploymentManifest;
use latent_routing::RouteResolver;
use serde_json::json;

use super::super::super::fixtures::*;
use crate::deployments::compiler::metadata_ownership::{Counts, Session};
use crate::DeploymentStore;

const RELEASES: usize = 4;
const ROUTES: usize = 8;
const DOCUMENTATION_BYTES: usize = 8 * 1024;

fn marker(index: usize) -> String {
    format!("small-metadata-{index:02}")
}

fn digest(index: usize) -> ReleaseDigest {
    content_digest(marker(index).as_bytes())
}

fn desired(distinct: bool) -> Vec<DeploymentManifest> {
    (0..ROUTES)
        .map(|index| {
            let tenant = if distinct {
                "alice".to_owned()
            } else {
                format!("tenant-{index:02}")
            };
            deployment(
                &format!("route-{index:02}"),
                &tenant,
                &digest(if distinct { index % RELEASES } else { 0 }),
            )
        })
        .collect()
}

fn assert_ownership(counts: Counts, expected: usize) {
    assert_eq!(counts.fetched, expected, "one owner per grouped release");
    assert_eq!(
        counts.peak_live, 1,
        "compiler metadata ownership accumulated: {counts:?}"
    );
    assert_eq!(counts.peak_documentation_bytes, DOCUMENTATION_BYTES);
    assert_eq!(counts.created, expected);
    assert_eq!(counts.dropped, expected);
    assert_eq!(counts.live, 0, "route snapshots must not retain metadata");
    assert_eq!(counts.documentation_bytes, 0);
}

fn assert_routes(store: &Store, expected: &[DeploymentManifest]) {
    assert_eq!(store.generation(), RouteGeneration(1));
    assert_eq!(run(store.list()).unwrap().len(), ROUTES);
    for deployment in expected {
        let route = store
            .resolve(
                &target(
                    &deployment.metadata.tenant.as_ref().unwrap().0,
                    Some(&deployment.id.0),
                ),
                Some("stable"),
            )
            .unwrap();
        assert_eq!(route.release, deployment.release);
        assert_eq!(route.route_generation, RouteGeneration(1));
        assert!(store
            .resolve(
                &target("absent-tenant", Some(&deployment.id.0)),
                Some("stable"),
            )
            .is_err());
    }
}

fn fixture(retain: bool) {
    let total = Instant::now();
    let root = TempRoot::new();
    let started = Instant::now();
    let releases = Arc::new(
        DirectoryArtifactRepository::open(
            root.0.join("releases"),
            DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap(),
    );
    for index in 0..RELEASES {
        let mut value = artifact(&marker(index));
        value.contracts[0].interfaces[0].documentation = Some("d".repeat(DOCUMENTATION_BYTES));
        let published = run(releases.publish(value)).unwrap();
        assert_eq!(published.release_digest, digest(index));
        let restored = run(releases.fetch(&published.release_digest)).unwrap();
        assert_eq!(
            restored.contracts[0].interfaces[0]
                .documentation
                .as_deref()
                .unwrap(),
            "d".repeat(DOCUMENTATION_BYTES)
        );
    }
    let publish_seconds = started.elapsed().as_secs_f64();
    let limits = Limits {
        max_state_bytes: 512 * 1024,
        ..Limits::default()
    };
    let mut observations = Vec::new();
    for distinct in [true, false] {
        let scenario = if distinct {
            "interleaved-distinct-releases"
        } else {
            "shared-release-distinct-scopes"
        };
        let expected_fetches = if distinct { RELEASES } else { 1 };
        let desired = desired(distinct);
        let path = root.0.join(scenario);
        let store = run(Store::open(path.clone(), releases.clone(), limits)).unwrap();
        let before = releases.verification_snapshot();
        let session = Session::begin(retain);
        let started = Instant::now();
        run(store.apply_many(desired.clone())).unwrap();
        let apply_seconds = started.elapsed().as_secs_f64();
        let applied = session.snapshot();
        drop(session);
        assert_ownership(applied, expected_fetches);
        let after = releases.verification_snapshot();
        assert_eq!(
            after.metadata_fetch_attempts - before.metadata_fetch_attempts,
            expected_fetches as u64
        );
        assert_eq!(after.full_fetch_attempts, before.full_fetch_attempts);
        assert_routes(&store, &desired);
        let expected_snapshot = snapshot(&store);
        let state = fs::read(path.join("catalog.json")).unwrap();
        assert!(state.len() < limits.max_state_bytes);
        assert!(
            !state.windows(128).any(|bytes| bytes == [b'd'; 128]),
            "persisted routing state must not contain release documentation"
        );
        drop(store);

        let before = releases.verification_snapshot();
        let session = Session::begin(false);
        let started = Instant::now();
        let store = run(Store::open(path.clone(), releases.clone(), limits)).unwrap();
        let reopen_seconds = started.elapsed().as_secs_f64();
        let reopened = session.snapshot();
        drop(session);
        assert_ownership(reopened, expected_fetches);
        let after = releases.verification_snapshot();
        assert_eq!(
            after.metadata_fetch_attempts - before.metadata_fetch_attempts,
            expected_fetches as u64
        );
        assert_eq!(after.full_fetch_attempts, before.full_fetch_attempts);
        assert_routes(&store, &desired);
        assert_eq!(snapshot(&store), expected_snapshot);
        assert_eq!(fs::read(path.join("catalog.json")).unwrap(), state);
        observations.push(json!({
            "scenario": scenario,
            "routes": ROUTES,
            "generation": 1,
            "fetches_per_compilation": expected_fetches,
            "peak_metadata_owners": applied.peak_live,
            "peak_documentation_bytes": applied.peak_documentation_bytes,
            "owners_after_apply": applied.live,
            "owners_after_reopen": reopened.live,
            "drops_per_compilation": applied.dropped,
            "state_bytes": state.len(),
            "apply_seconds": apply_seconds,
            "reopen_seconds": reopen_seconds,
        }));
    }
    // Teardown belongs to the measured fixture lifetime, not to later test work.
    drop(releases);
    drop(root);
    println!(
        "\nLSF_METADATA_CORRECTNESS {}",
        json!({
            "schemaVersion": "latent.catalog.metadata-correctness.v1",
            "releases": RELEASES,
            "documentation_bytes_per_release": DOCUMENTATION_BYTES,
            "publish_seconds": publish_seconds,
            "total_seconds": total.elapsed().as_secs_f64(),
            "scenarios": observations,
        })
    );
}

#[test]
fn small_metadata_preserves_routes_grouping_and_bounded_ownership() {
    fixture(false);
}

#[test]
#[should_panic(expected = "compiler metadata ownership accumulated")]
fn small_metadata_retention_negative_control() {
    // The very same production compilation retains each actual payload in the
    // test-only Retainer. A passing positive fixture alone is not this control.
    fixture(true);
}
