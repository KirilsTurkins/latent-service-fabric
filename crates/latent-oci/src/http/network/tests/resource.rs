//! Manual bounded costs on real owned TLS/DNS futures; never a throughput claim.
mod observe;
mod phases;
mod probe;

use serde_json::json;
use std::{io::Write, os::unix::fs::OpenOptionsExt, path::PathBuf};

#[tokio::test]
#[ignore = "manual OCI pool resource campaign with an explicit fresh report"]
async fn bounded_oci_pool_resource_checkpoint() {
    let output =
        PathBuf::from(std::env::var_os("LSF_PHASE3_OCI_RESOURCE_REPORT").expect("report path"));
    assert!(output.is_absolute() && output.parent().unwrap().is_dir() && !output.exists());
    let fixed = probe::capture();
    let mut rows = Vec::new();
    for ceiling in [1, 2] {
        phases::tokens(ceiling, &mut rows).await;
        phases::dns(ceiling, &mut rows).await;
        phases::redirects(ceiling, &mut rows).await;
    }
    assert_eq!(rows.len(), 48);
    let retired = probe::capture();
    for key in [
        "processId",
        "threadCount",
        "socketCount",
        "openFileDescriptors",
    ] {
        assert_eq!(retired[key], fixed[key]);
    }
    let report = json!({"schemaVersion": "latent.phase3.oci-resource.v1", "status": "checkpoint-passed",
        "ceilings": [1, 2], "cyclesPerPool": 4, "fixed": fixed, "retired": retired,
        "ownership": "one-current-thread-runtime-with-owned-local-TLS-and-DNS-peers",
        "observations": rows, "universalPerformanceClaim": false});
    let bytes = serde_json::to_vec(&report).unwrap();
    assert!(bytes.len() <= 1024 * 1024);
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(output)
        .unwrap();
    file.write_all(&bytes).unwrap();
    file.sync_all().unwrap();
}
