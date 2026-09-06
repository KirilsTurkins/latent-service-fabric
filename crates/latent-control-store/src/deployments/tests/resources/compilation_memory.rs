//! Real persisted metadata, measured in fresh processes rather than allocator-tainted fixtures.

use std::fs;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_artifacts::{
    content_digest, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig,
};
use latent_core::{ReleaseDigest, RouteGeneration};
use latent_manifest::DeploymentManifest;
use latent_routing::RouteResolver;

use super::super::fixtures::*;
use super::ReapedChild;
use crate::DeploymentStore;

const MODE_ENV: &str = "LSF_DEPLOYMENT_MEMORY_MODE";
const ROOT_ENV: &str = "LSF_DEPLOYMENT_MEMORY_ROOT";
const TEST_NAME: &str = "deployments::tests::resources::compilation_memory::large_release_metadata_has_a_bounded_compilation_working_set";
const RELEASES: usize = 32;
const DOCUMENTATION_BYTES: usize = 3 * 1024 * 1024;
const MAX_GROWTH_KIB: u64 = 64 * 1024;

#[test]
fn large_release_metadata_has_a_bounded_compilation_working_set() {
    if let Ok(mode) = std::env::var(MODE_ENV) {
        let root = std::env::var_os(ROOT_ENV).expect("parent-owned test root");
        child_probe(&mode, Path::new(&root));
        return;
    }
    let root = TempRoot::new();
    // Publication, application and restart cannot reuse one another's allocator arenas
    // or retained artifacts. The production release repository is the only data source.
    for mode in ["publish", "apply", "reopen"] {
        let path = root.0.join(format!("{mode}.log"));
        let output = fs::File::create(&path).unwrap();
        let mut child = ReapedChild(
            Command::new(std::env::current_exe().unwrap())
                .args(["--exact", TEST_NAME, "--nocapture", "--test-threads=1"])
                .env(MODE_ENV, mode)
                .env(ROOT_ENV, &root.0)
                .stdin(Stdio::null())
                .stdout(output.try_clone().unwrap())
                .stderr(output)
                .spawn()
                .unwrap(),
        );
        let deadline = Instant::now() + Duration::from_secs(300);
        loop {
            if let Some(status) = child.0.try_wait().unwrap() {
                let evidence = fs::read_to_string(&path).unwrap();
                assert!(status.success(), "{mode} child failed: {evidence}");
                assert!(
                    evidence.contains(&format!("memory-mode={mode}")),
                    "{evidence}"
                );
                println!("{evidence}");
                break;
            }
            assert!(
                Instant::now() < deadline,
                "{mode} child exceeded its deadline"
            );
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}

fn marker(index: usize) -> String {
    format!("large-metadata-{index:02}")
}

fn digest(index: usize) -> ReleaseDigest {
    content_digest(marker(index).as_bytes())
}

fn desired(distinct_releases: bool) -> Vec<DeploymentManifest> {
    (0..RELEASES)
        .map(|index| {
            let tenant = if distinct_releases {
                "alice".to_owned()
            } else {
                format!("tenant-{index:02}")
            };
            deployment(
                &format!("route-{index:02}"),
                &tenant,
                &digest(if distinct_releases { index } else { 0 }),
            )
        })
        .collect()
}

fn high_water_kib() -> u64 {
    fs::read_to_string("/proc/self/status")
        .unwrap()
        .lines()
        .find_map(|line| {
            line.strip_prefix("VmHWM:")
                .map(|value| value.split_whitespace().next().unwrap().parse().unwrap())
        })
        .expect("Linux must report peak resident memory")
}

fn child_probe(mode: &str, root: &Path) {
    let releases = Arc::new(
        DirectoryArtifactRepository::open(
            root.join("releases"),
            DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap(),
    );
    if mode == "publish" {
        for index in 0..RELEASES {
            let mut value = artifact(&marker(index));
            value.contracts[0].interfaces[0].documentation = Some("d".repeat(DOCUMENTATION_BYTES));
            let descriptor = run(releases.publish(value)).unwrap();
            assert_eq!(descriptor.release_digest, digest(index));
            let restored = run(releases.fetch(&descriptor.release_digest)).unwrap();
            assert_eq!(
                restored.contracts[0].interfaces[0]
                    .documentation
                    .as_ref()
                    .unwrap()
                    .len(),
                DOCUMENTATION_BYTES
            );
        }
        println!(
            "memory-mode=publish releases={RELEASES} documentation_bytes={}",
            RELEASES * DOCUMENTATION_BYTES
        );
        return;
    }
    assert!(matches!(mode, "apply" | "reopen"));
    let baseline = high_water_kib();
    let limits = Limits {
        max_state_bytes: 512 * 1024,
        ..Limits::default()
    };
    for distinct_releases in [true, false] {
        let scenario = if distinct_releases {
            "distinct-releases"
        } else {
            "shared-release-distinct-scopes"
        };
        let path = root.join(scenario);
        let previous = (mode == "reopen").then(|| fs::read(path.join("catalog.json")).unwrap());
        let store = run(Store::open(path.clone(), releases.clone(), limits)).unwrap();
        let deployments = desired(distinct_releases);
        if mode == "apply" {
            run(store.apply_many(deployments.clone())).unwrap();
        }
        assert_eq!(store.generation(), RouteGeneration(1));
        assert_eq!(run(store.list()).unwrap().len(), RELEASES);
        for deployment in &deployments {
            let resolved = store
                .resolve(
                    &target(
                        &deployment.metadata.tenant.as_ref().unwrap().0,
                        Some(&deployment.id.0),
                    ),
                    Some("stable"),
                )
                .unwrap();
            assert_eq!(resolved.release, deployment.release);
            assert_eq!(resolved.route_generation, RouteGeneration(1));
        }
        let state = fs::read(path.join("catalog.json")).unwrap();
        assert!(state.len() < limits.max_state_bytes);
        if let Some(previous) = previous {
            assert_eq!(state, previous, "restart must not rewrite routing state");
        }
        let peak = high_water_kib();
        let growth = peak.saturating_sub(baseline);
        println!(
            "memory-mode={mode} scenario={scenario} releases={RELEASES} baseline_kib={baseline} peak_kib={peak} growth_kib={growth} state_bytes={}",
            state.len()
        );
        // One bounded release plus temporary canonicalization is allowed. Neither
        // 96 MiB of release documentation nor 96 MiB of scoped canonical trees may
        // accumulate behind a sub-512-KiB route snapshot. This is an RSS regression
        // allowance, not a claim that max_state_bytes is a total-process heap limit.
        assert!(
            growth <= MAX_GROWTH_KIB,
            "compiler retained aggregate full release/contract metadata: {growth} KiB"
        );
    }
}

#[test]
fn release_grouping_fetches_each_digest_once_even_with_interleaved_ids() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let store = open(&root, &releases);
    run(store.apply_many(vec![
        deployment("a", "alice", &one),
        deployment("b", "alice", &two),
        deployment("c", "alice", &one),
        deployment("d", "alice", &two),
    ]))
    .unwrap();
    assert_eq!(releases.fetches.load(Ordering::Relaxed), 2);
    let expected = snapshot(&store);
    drop(store);
    let store = open(&root, &releases);
    assert_eq!(releases.fetches.load(Ordering::Relaxed), 4);
    assert_eq!(snapshot(&store), expected);
}
