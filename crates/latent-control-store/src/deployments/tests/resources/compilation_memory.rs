//! Small ownership correctness and an independently selected physical qualification.

mod correctness;
mod supervision;

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
use latent_manifest::DeploymentManifest;
use latent_routing::RouteResolver;
use serde_json::{json, Value};

use super::super::fixtures::*;
use crate::DeploymentStore;

const MODE_ENV: &str = "LSF_DEPLOYMENT_MEMORY_MODE";
const ROOT_ENV: &str = "LSF_DEPLOYMENT_MEMORY_ROOT";
const TEST_NAME: &str = "deployments::tests::resources::compilation_memory::large_release_metadata_has_a_bounded_compilation_working_set";
const RELEASES: usize = 32;
const DOCUMENTATION_BYTES: usize = 3 * 1024 * 1024;
const MAX_GROWTH_KIB: u64 = 64 * 1024;
const MAX_STATE_BYTES: usize = 512 * 1024;
const CHILD_PREFIX: &str = "LSF_METADATA_CHILD ";
const SCENARIOS: [&str; 2] = ["distinct-releases", "shared-release-distinct-scopes"];

#[test]
#[ignore = "physical qualification: select catalog-metadata-working-set explicitly"]
fn large_release_metadata_has_a_bounded_compilation_working_set() {
    match std::env::var(MODE_ENV) {
        Ok(mode) => {
            let root = std::env::var_os(ROOT_ENV).expect("parent-owned test root");
            child_probe(&mode, Path::new(&root));
            return;
        }
        Err(std::env::VarError::NotPresent) => {}
        Err(error) => panic!("invalid child mode: {error}"),
    }
    let total = Instant::now();
    let root = TempRoot::new();
    let mut phases = Vec::new();
    // Publication, application and restart cannot reuse one another's allocator
    // arenas or retained artifacts. Only the production repository transfers data.
    for mode in ["publish", "apply", "reopen"] {
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--exact",
                TEST_NAME,
                "--ignored",
                "--nocapture",
                "--test-threads=1",
            ])
            .env(MODE_ENV, mode)
            .env(ROOT_ENV, &root.0);
        let (evidence, seconds) = supervision::run(&mut command, Duration::from_secs(300))
            .unwrap_or_else(|error| panic!("{mode}: {error}"));
        let observation = validate_child(&evidence, mode)
            .unwrap_or_else(|error| panic!("{mode}: {error}: {evidence}"));
        println!("{evidence}");
        phases.push(json!({"mode": mode, "seconds": seconds, "observation": observation}));
    }
    drop(root);
    println!(
        "\nLSF_METADATA_PHYSICAL {}",
        json!({
            "schemaVersion": "latent.catalog.metadata-working-set.v1",
            "releases": RELEASES,
            "documentation_bytes_per_release": DOCUMENTATION_BYTES,
            "max_growth_kib": MAX_GROWTH_KIB,
            "total_seconds": total.elapsed().as_secs_f64(),
            "phases": phases,
        })
    );
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

fn parse_high_water(status: &str) -> Option<u64> {
    let mut lines = status
        .lines()
        .filter_map(|line| line.strip_prefix("VmHWM:"));
    let mut fields = lines.next()?.split_whitespace();
    let value = fields.next()?.parse().ok()?;
    (value > 0 && fields.next() == Some("kB") && fields.next().is_none() && lines.next().is_none())
        .then_some(value)
}

fn high_water_kib() -> u64 {
    let status = fs::read_to_string("/proc/self/status").expect("read Linux peak resident memory");
    parse_high_water(&status).expect("Linux must report a positive, well-formed VmHWM in kB")
}

fn child_probe(mode: &str, root: &Path) {
    assert!(matches!(mode, "publish" | "apply" | "reopen"));
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
        emit_child(mode, Vec::new());
        return;
    }
    let baseline = high_water_kib();
    let limits = Limits {
        max_state_bytes: MAX_STATE_BYTES,
        ..Limits::default()
    };
    let mut observations = Vec::new();
    for distinct_releases in [true, false] {
        let started = Instant::now();
        let scenario = SCENARIOS[usize::from(!distinct_releases)];
        let path = root.join(scenario);
        let previous = (mode == "reopen").then(|| fs::read(path.join("catalog.json")).unwrap());
        let before = releases.verification_snapshot();
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
        let after = releases.verification_snapshot();
        let fetches = after.metadata_fetch_attempts - before.metadata_fetch_attempts;
        assert_eq!(
            fetches,
            if distinct_releases {
                RELEASES as u64
            } else {
                1
            }
        );
        assert_eq!(after.full_fetch_attempts, before.full_fetch_attempts);
        let peak = high_water_kib();
        let growth = peak.checked_sub(baseline).expect("VmHWM cannot decrease");
        println!(
            "memory-mode={mode} scenario={scenario} releases={RELEASES} baseline_kib={baseline} peak_kib={peak} growth_kib={growth} state_bytes={}",
            state.len()
        );
        // Keep the original 32 x 3 MiB inputs and 64 MiB allowance. Neither full
        // release documentation nor scoped canonical trees may accumulate. This
        // is not a claim that max_state_bytes is a total-process heap limit.
        assert!(
            growth <= MAX_GROWTH_KIB,
            "compiler retained aggregate full release/contract metadata: {growth} KiB"
        );
        observations.push(json!({
            "scenario": scenario,
            "generation": 1,
            "routes_verified": RELEASES,
            "metadata_fetches": fetches,
            "baseline_kib": baseline,
            "peak_kib": peak,
            "growth_kib": growth,
            "state_bytes": state.len(),
            "state_unchanged": (mode == "reopen").then_some(true),
            "seconds": started.elapsed().as_secs_f64(),
        }));
    }
    emit_child(mode, observations);
}

fn emit_child(mode: &str, scenarios: Vec<Value>) {
    // Printed only after all assertions, on its own line even under libtest.
    println!(
        "\n{CHILD_PREFIX}{}",
        json!({
            "mode": mode,
            "releases": RELEASES,
            "documentation_bytes_per_release": DOCUMENTATION_BYTES,
            "scenarios": scenarios,
        })
    );
}

fn validate_child(evidence: &str, mode: &str) -> Result<Value, String> {
    let mut records = evidence
        .lines()
        .filter_map(|line| line.strip_prefix(CHILD_PREFIX));
    let record = records.next().ok_or("missing-child-observation")?;
    let record: Value = serde_json::from_str(record).map_err(|_| "invalid-child-observation")?;
    if records.next().is_some()
        || evidence
            .lines()
            .filter(|line| line.starts_with("test result: ok. 1 passed; 0 failed; 0 ignored;"))
            .count()
            != 1
        || record["mode"] != mode
        || record["releases"] != RELEASES
        || record["documentation_bytes_per_release"] != DOCUMENTATION_BYTES
    {
        return Err("child-observation-identity".to_owned());
    }
    let scenarios = record["scenarios"].as_array().ok_or("missing-scenarios")?;
    if mode == "publish" {
        if !scenarios.is_empty() {
            return Err("unexpected-publish-measurement".to_owned());
        }
    } else {
        if !matches!(mode, "apply" | "reopen") || scenarios.len() != SCENARIOS.len() {
            return Err("missing-physical-scenario".to_owned());
        }
        for (index, scenario) in scenarios.iter().enumerate() {
            let baseline = scenario["baseline_kib"]
                .as_u64()
                .ok_or("missing-baseline")?;
            let peak = scenario["peak_kib"].as_u64().ok_or("missing-peak")?;
            let growth = scenario["growth_kib"].as_u64().ok_or("missing-growth")?;
            let state = scenario["state_bytes"].as_u64().ok_or("missing-state")?;
            if scenario["scenario"] != SCENARIOS[index]
                || scenario["generation"] != 1
                || scenario["routes_verified"] != RELEASES
                || scenario["metadata_fetches"] != if index == 0 { RELEASES } else { 1 }
                || baseline == 0
                || peak.checked_sub(baseline) != Some(growth)
                || growth > MAX_GROWTH_KIB
                || state == 0
                || state >= MAX_STATE_BYTES as u64
                || (mode == "reopen" && scenario["state_unchanged"] != true)
            {
                return Err("invalid-physical-observation".to_owned());
            }
        }
    }
    Ok(record)
}

#[test]
fn missing_or_malformed_proc_measurement_never_becomes_zero() {
    assert_eq!(parse_high_water("Name: test\nVmHWM:\t123 kB\n"), Some(123));
    for status in [
        "",
        "VmRSS: 123 kB",
        "VmHWM: 0 kB",
        "VmHWM: -1 kB",
        "VmHWM: x kB",
        "VmHWM: 1",
        "VmHWM: 1 MB",
        "VmHWM: 1 kB extra",
        "VmHWM: 1 kB\nVmHWM: 2 kB",
    ] {
        assert_eq!(parse_high_water(status), None, "{status}");
    }
}

#[test]
fn success_without_complete_child_observations_is_rejected() {
    let result = "test result: ok. 1 passed; 0 failed; 0 ignored;\n";
    assert!(validate_child(result, "publish").is_err());
    let record = json!({
        "mode": "apply", "releases": RELEASES,
        "documentation_bytes_per_release": DOCUMENTATION_BYTES,
        "scenarios": [],
    });
    assert!(validate_child(&format!("{CHILD_PREFIX}{record}\n{result}"), "apply").is_err());
    let record = json!({
        "mode": "publish", "releases": RELEASES,
        "documentation_bytes_per_release": DOCUMENTATION_BYTES,
        "scenarios": [],
    });
    let evidence = format!("{CHILD_PREFIX}{record}\n{result}");
    assert!(validate_child(&evidence, "publish").is_ok());
    assert!(validate_child(&evidence, "reopen").is_err());
    assert!(validate_child(&evidence.repeat(2), "publish").is_err());
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
