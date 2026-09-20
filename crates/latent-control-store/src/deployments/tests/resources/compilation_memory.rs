//! Real persisted metadata, measured in fresh processes rather than allocator-tainted fixtures.

use std::fs;
use std::path::Path;
use std::process::Command;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_artifacts::{
    content_digest, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig,
};
use latent_core::{ReleaseDigest, RouteGeneration};
use latent_manifest::{__serde_json as json, DeploymentManifest};
use latent_routing::RouteResolver;

use super::super::fixtures::*;
use crate::DeploymentStore;

mod process;

const MODE_ENV: &str = "LSF_DEPLOYMENT_MEMORY_MODE";
const ROOT_ENV: &str = "LSF_DEPLOYMENT_MEMORY_ROOT";
const TEST_NAME: &str = "deployments::tests::resources::compilation_memory::large_release_metadata_has_a_bounded_compilation_working_set";
const RELEASES: usize = 32;
const DOCUMENTATION_BYTES: usize = 3 * 1024 * 1024;
const MAX_GROWTH_KIB: u64 = 64 * 1024;

#[test]
#[ignore = "physical-resource suite: ci_rust_artifacts.py --suite metadata-working-set"]
fn large_release_metadata_has_a_bounded_compilation_working_set() {
    match std::env::var(MODE_ENV) {
        Ok(mode) => {
            let root = std::env::var_os(ROOT_ENV).expect("parent-owned test root");
            child_probe(&mode, Path::new(&root));
            return;
        }
        Err(std::env::VarError::NotPresent) => {}
        Err(error) => panic!("invalid probe mode: {error}"),
    }
    let root = TempRoot::new();
    // Preserve separate allocator histories and the real on-disk handoff.
    for mode in ["publish", "apply", "reopen"] {
        let started = Instant::now();
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--exact",
                TEST_NAME,
                "--ignored",
                "--show-output",
                "--test-threads=1",
            ])
            .env(MODE_ENV, mode)
            .env(ROOT_ENV, &root.0);
        let evidence = process::run(command, Duration::from_secs(300))
            .unwrap_or_else(|error| panic!("{mode}: {error}"));
        let observation = validate_observation(&evidence, mode)
            .unwrap_or_else(|error| panic!("{mode}: {error}: {evidence}"));
        println!(
            "LSF_METADATA_MEASUREMENT {}",
            json::json!({
                "schema": "latent.metadata-working-set.v1",
                "mode": mode,
                "releases": RELEASES,
                "documentation_bytes_per_release": DOCUMENTATION_BYTES,
                "max_growth_kib": MAX_GROWTH_KIB,
                "max_state_bytes": 512 * 1024,
                "wall_ns": started.elapsed().as_nanos(),
                "os": std::env::consts::OS,
                "arch": std::env::consts::ARCH,
                "observation": observation,
            })
        );
    }
}

fn validate_observation(evidence: &str, mode: &str) -> Result<json::Value, &'static str> {
    let observations = evidence
        .lines()
        .filter_map(|line| line.strip_prefix("LSF_METADATA_CHILD "))
        .collect::<Vec<_>>();
    if observations.len() != 1 {
        return Err("expected-one-completed-observation");
    }
    let summaries = evidence
        .lines()
        .filter(|line| line.starts_with("test result:"))
        .collect::<Vec<_>>();
    if summaries.len() != 1
        || !summaries[0].starts_with("test result: ok. 1 passed; 0 failed; 0 ignored;")
    {
        return Err("child-did-not-execute-exactly-one-test");
    }
    let value: json::Value =
        json::from_str(observations[0]).map_err(|_| "invalid-observation-json")?;
    if value["mode"].as_str() != Some(mode) || value["complete"].as_bool() != Some(true) {
        return Err("incomplete-or-wrong-mode-observation");
    }
    if mode == "publish" {
        if value["verified_releases"].as_u64() != Some(RELEASES as u64)
            || value["documentation_bytes"].as_u64()
                != Some((RELEASES * DOCUMENTATION_BYTES) as u64)
        {
            return Err("incomplete-publication-observation");
        }
    } else {
        if !matches!(mode, "apply" | "reopen") {
            return Err("unknown-observation-mode");
        }
        let scenarios = value["scenarios"].as_array().ok_or("missing-scenarios")?;
        if scenarios.len() != 2 {
            return Err("incomplete-scenario-observations");
        }
        for (scenario, name) in scenarios
            .iter()
            .zip(["distinct-releases", "shared-release-distinct-scopes"])
        {
            let baseline = scenario["baseline_kib"].as_u64().ok_or("missing-baseline")?;
            let peak = scenario["peak_kib"].as_u64().ok_or("missing-peak")?;
            let growth = peak.checked_sub(baseline).ok_or("nonmonotonic-peak")?;
            let state = scenario["state_bytes"].as_u64().ok_or("missing-state-bytes")?;
            if scenario["name"].as_str() != Some(name)
                || scenario["routes"].as_u64() != Some(RELEASES as u64)
                || scenario["generation"].as_u64() != Some(1)
                || scenario["state_unchanged"].as_bool() != Some(mode == "reopen")
                || baseline == 0
                || growth > MAX_GROWTH_KIB
                || scenario["growth_kib"].as_u64() != Some(growth)
                || state == 0
                || state >= 512 * 1024
            {
                return Err("invalid-scenario-observation");
            }
        }
    }
    Ok(value)
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

fn parse_high_water_kib(status: &str) -> Result<u64, &'static str> {
    let mut lines = status.lines().filter(|line| line.starts_with("VmHWM:"));
    let fields = lines
        .next()
        .ok_or("missing-VmHWM")?
        .split_whitespace()
        .collect::<Vec<_>>();
    if lines.next().is_some() || fields.len() != 3 || fields[2] != "kB" {
        return Err("invalid-VmHWM");
    }
    let value: u64 = fields[1].parse().map_err(|_| "invalid-VmHWM-value")?;
    if value == 0 {
        return Err("zero-VmHWM");
    }
    Ok(value)
}

fn high_water_kib() -> u64 {
    let status = fs::read_to_string("/proc/self/status")
        .expect("Linux /proc memory measurement is required");
    parse_high_water_kib(&status).expect("Linux must report positive peak resident memory in kB")
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
            "LSF_METADATA_CHILD {}",
            json::json!({
                "mode": mode,
                "complete": true,
                "verified_releases": RELEASES,
                "documentation_bytes": RELEASES * DOCUMENTATION_BYTES,
            })
        );
        return;
    }
    assert!(matches!(mode, "apply" | "reopen"));
    // Optional diagnostic mutation retains the very same real owned values. It
    // must fail the unchanged physical threshold; CI qualification rejects this
    // environment input. Normal qualification does not install an observer.
    use crate::deployments::compiler::ownership::{Fault, Kind, Session};
    let _negative_control = std::env::var_os("LSF_METADATA_RETAIN").map(|value| {
        let kind = match value.to_str() {
            Some("release") => Kind::Release,
            Some("canonical") => Kind::Canonical,
            _ => panic!("invalid metadata retention negative control"),
        };
        Session::start(Fault::Retain(kind))
    });
    let baseline = high_water_kib();
    let mut scenarios = Vec::with_capacity(2);
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
        let growth = peak.checked_sub(baseline).expect("VmHWM must be monotonic");
        // One bounded release plus temporary canonicalization is allowed. Neither
        // 96 MiB of release documentation nor 96 MiB of scoped canonical trees may
        // accumulate behind a sub-512-KiB route snapshot. This is an RSS regression
        // allowance, not a claim that max_state_bytes is a total-process heap limit.
        assert!(
            growth <= MAX_GROWTH_KIB,
            "compiler retained aggregate full release/contract metadata: {growth} KiB"
        );
        scenarios.push(json::json!({
            "name": scenario,
            "routes": RELEASES,
            "generation": 1,
            "baseline_kib": baseline,
            "peak_kib": peak,
            "growth_kib": growth,
            "state_bytes": state.len(),
            "state_unchanged": mode == "reopen",
        }));
    }
    // A completion observation is emitted only after BOTH scenarios passed.
    println!(
        "LSF_METADATA_CHILD {}",
        json::json!({
            "mode": mode,
            "complete": true,
            "scenarios": scenarios,
        })
    );
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

#[test]
fn missing_or_invalid_proc_measurements_fail_closed() {
    assert_eq!(parse_high_water_kib("Name: test\nVmHWM: 42 kB\n"), Ok(42));
    for invalid in [
        "",
        "VmRSS: 42 kB",
        "VmHWM: 0 kB",
        "VmHWM: 42",
        "VmHWM: 42 MB",
        "VmHWM: no kB",
        "VmHWM: 1 kB\nVmHWM: 2 kB",
    ] {
        assert!(parse_high_water_kib(invalid).is_err(), "{invalid}");
    }
}

#[test]
fn successful_child_without_a_complete_observation_is_not_a_measurement() {
    let summary = "test result: ok. 1 passed; 0 failed; 0 ignored; 0 filtered out; finished in 0.00s\n";
    assert!(validate_observation(summary, "publish").is_err());
    let complete = format!(
        "LSF_METADATA_CHILD {}\n",
        json::json!({
            "mode": "publish", "complete": true, "verified_releases": RELEASES,
            "documentation_bytes": RELEASES * DOCUMENTATION_BYTES,
        })
    );
    assert!(validate_observation(&format!("{complete}{summary}"), "publish").is_ok());
    assert!(validate_observation(&format!("{complete}{summary}"), "apply").is_err());
    assert!(validate_observation(&format!("{complete}{complete}{summary}"), "publish").is_err());
    assert!(validate_observation(&complete, "publish").is_err());
    let skipped = summary.replace("1 passed", "0 passed");
    assert!(validate_observation(&format!("{complete}{skipped}"), "publish").is_err());
    let partial = format!(
        "LSF_METADATA_CHILD {}\n{summary}",
        json::json!({
            "mode": "apply", "complete": true, "scenarios": [],
        })
    );
    assert!(validate_observation(&partial, "apply").is_err());
}
