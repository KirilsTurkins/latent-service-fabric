use super::{NodeConfig, TempDir};
use crate::standalone::{RuntimeThreads, StandaloneNode};
use std::{
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    time::Duration,
};
use tokio::runtime::Builder;

#[test]
#[ignore = "requires an explicit protected synthetic provider configuration"]
fn configured_provider_startup_and_shutdown_remain_repeatable() {
    let source = PathBuf::from(std::env::var_os("LSF_PROVIDER_STARTUP_CONFIG").unwrap());
    repeat_startup(&source);
}

#[test]
fn protected_local_blob_provider_starts_and_reaps_thirty_two_times() {
    let source = TempDir::new().unwrap();
    let path = source.path().join("node.json");
    let document = serde_json::json!({
        "formatVersion": 1, "dataDirectory": source.path().join("unselected-data"),
        "nodeId": "provider-startup", "bind": "127.0.0.1:0",
        "credentials": [{"token": "LSF-PUBLIC-PROVIDER-STARTUP-TEST-ONLY",
            "subject": "operator", "tenant": "tests", "role": "operator"}],
        "budgetProfile": {"mode": "phase3", "maximumOutboundRequests": 8,
            "maximumBlobReadBytes": 65536, "maximumBlobWriteBytes": 65536},
        "audit": {"mode": "durable"}, "capabilityPolicies": {"formatVersion": 1},
        "providers": {"formatVersion": 1,
            "blob": {"identity": {"id": "blob", "tenant": "tests",
                "service": "blob-host", "epoch": 1}, "namespace": "workflow"},
            "bindings": [{"name": "blob-binding", "tenant": "tests",
                "consumerService": "guest-blob", "providerService": "blob-host",
                "contract": "latent:blob/blob@0.2.0", "providerBinding": "blob-installed"}]}
    });
    std::fs::write(&path, serde_json::to_vec(&document).unwrap()).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    repeat_startup(&path);
}

fn repeat_startup(source: &Path) {
    let directory = TempDir::new().unwrap();
    let control = Builder::new_multi_thread()
        .worker_threads(1)
        .max_blocking_threads(4)
        .enable_all()
        .build()
        .unwrap();
    let invocation = Builder::new_multi_thread()
        .worker_threads(1)
        .max_blocking_threads(1)
        .enable_all()
        .build()
        .unwrap();
    for ordinal in 0..32 {
        let mut settings = NodeConfig::load(source).unwrap().derive().unwrap();
        settings.data_directory = directory.path().join(format!("node-{ordinal}"));
        let node = invocation
            .block_on(StandaloneNode::start(
                settings,
                control.handle().clone(),
                RuntimeThreads::default(),
            ))
            .unwrap_or_else(|failure| panic!("startup {ordinal}: {failure:?}"));
        assert!(invocation.block_on(node.shutdown()).unwrap().clean);
    }
    control.shutdown_timeout(Duration::from_secs(5));
    invocation.shutdown_timeout(Duration::from_secs(5));
}
