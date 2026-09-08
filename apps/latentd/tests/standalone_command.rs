//! Tiny real-process command checks, supervised outside the node's runtimes.
#![cfg(target_os = "linux")]

#[path = "standalone_command/mod.rs"]
mod support;

use std::fs;
use std::net::SocketAddr;

use serde_json::{json, Value};

use support::{configuration, Process, TOKEN};

#[test]
fn invalid_configuration_and_corrupt_catalog_fail_before_started() {
    let invalid = tempfile::tempdir().unwrap();
    let path = configuration(invalid.path());
    let mut document: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    document["formatVersion"] = json!(2);
    fs::write(&path, serde_json::to_vec(&document).unwrap()).unwrap();
    let mut process = Process::node(&path);
    assert_eq!(process.wait().code(), Some(2));
    assert!(process.records().is_empty());
    assert!(process
        .error_text()
        .contains("configuration: invalid-argument"));
    assert!(!process.error_text().contains(TOKEN));
    assert!(!invalid.path().join("data").exists());

    let corrupt = tempfile::tempdir().unwrap();
    let path = configuration(corrupt.path());
    let deployments = corrupt.path().join("data/deployments");
    fs::create_dir_all(&deployments).unwrap();
    let original = b"damaged catalog containing private operator information";
    fs::write(deployments.join("catalog.json"), original).unwrap();
    let mut process = Process::node(&path);
    assert!(!process.wait().success());
    assert!(process.records().is_empty());
    assert!(process.error_text().contains("startup:"));
    assert!(!process.error_text().contains("private operator"));
    assert!(!process.error_text().contains(TOKEN));
    assert_eq!(
        fs::read(deployments.join("catalog.json")).unwrap(),
        original
    );
    assert!(!deployments.join("INITIALIZED").exists());
}

#[test]
fn signals_stop_cleanly_and_repeated_restart_reuses_the_owned_catalogs() {
    let directory = tempfile::tempdir().unwrap();
    let config = configuration(directory.path());
    let mut prior_catalog = None;
    for signal in ["-TERM", "-TERM", "-INT"] {
        let mut process = Process::node(&config);
        let started = process.started();
        assert_eq!(started["schemaVersion"], "latent.standalone.status.v1");
        assert_eq!(started["nodeId"], "command-test");
        let ready = started["ready"].as_bool().unwrap();
        assert_eq!(started["event"], if ready { "ready" } else { "started" });
        let endpoint: SocketAddr = started["endpoint"].as_str().unwrap().parse().unwrap();
        assert!(endpoint.ip().is_loopback());
        assert_ne!(endpoint.port(), 0);
        process.signal(signal);
        assert!(process.wait().success(), "{}", process.error_text());
        let records = process.records();
        assert_eq!(records.len(), 2);
        assert_clean(&records[1]);
        assert!(process.error_text().is_empty());
        assert!(!format!("{records:?}").contains(TOKEN));
        let state = fs::read(directory.path().join("data/deployments/catalog.json")).unwrap();
        let marker = fs::read(directory.path().join("data/deployments/INITIALIZED")).unwrap();
        if let Some(prior) = &prior_catalog {
            assert_eq!(&(state.clone(), marker.clone()), prior);
        }
        prior_catalog = Some((state, marker));
    }
}

fn assert_clean(stopped: &Value) {
    assert_eq!(stopped["schemaVersion"], "latent.standalone.status.v1");
    assert_eq!(stopped["event"], "stopped");
    assert_eq!(stopped["clean"], true);
    let report = &stopped["report"];
    assert_eq!(report["clean"], true);
    assert_eq!(report["telemetryFlushed"], true);
    assert_eq!(report["epochHelperJoined"], true);
    for field in [
        "activeConnections",
        "activeRpcs",
        "activeControlJobs",
        "activeActivations",
        "cancellationRegistrations",
        "observerCorrelations",
        "quotaReservations",
        "queuedReservations",
        "reservedCpuFuel",
        "reservedMemoryBytes",
        "activeLeases",
        "queuedActivations",
        "activeBackendInvocations",
        "instanceReservations",
        "preparingComponents",
        "preparingSourceBytes",
        "preparingMetadataBytes",
        "liveStores",
        "liveHostStates",
        "liveInstances",
        "liveTemporaryBuffers",
        "liveCancellationProbes",
    ] {
        assert_eq!(report[field].as_u64(), Some(0), "{field}");
    }
}
