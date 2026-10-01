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

#[test]
fn protected_http_credential_bootstrap_starts_and_reaps_thirty_two_times() {
    let source = TempDir::new().unwrap();
    let credentials = source.path().join("credentials");
    std::fs::create_dir(&credentials).unwrap();
    std::fs::set_permissions(&credentials, std::fs::Permissions::from_mode(0o700)).unwrap();
    let credential = credentials.join("authorization");
    std::fs::write(&credential, b"LSF-PUBLIC-PROVIDER-STARTUP-TEST-ONLY").unwrap();
    std::fs::set_permissions(&credential, std::fs::Permissions::from_mode(0o600)).unwrap();
    let path = source.path().join("node.json");
    let document = serde_json::json!({
        "formatVersion": 1, "dataDirectory": source.path().join("unselected-data"),
        "nodeId": "http-startup", "bind": "127.0.0.1:0",
        "credentials": [{"token": "LSF-PUBLIC-PROVIDER-STARTUP-TEST-ONLY",
            "subject": "operator", "tenant": "tests", "role": "operator"}],
        "budgetProfile": {"mode": "phase3", "maximumOutboundRequests": 8,
            "maximumBlobReadBytes": 65536, "maximumBlobWriteBytes": 65536},
        "audit": {"mode": "durable"}, "capabilityPolicies": {"formatVersion": 1},
        "providers": {"formatVersion": 1,
            "http": {
                "identity": {"id": "http", "tenant": "tests", "service": "http-host", "epoch": 1},
                "credentialDirectory": "credentials",
                "credentials": [{"reference": "startup", "file": "authorization",
                    "destination": 0, "header": "authorization"}],
                "configuration": {
                    "formatVersion": 1,
                    "destinations": [{
                        "origin": {"scheme": "http", "host": "localhost", "port": 9},
                        "addresses": {"networks": ["127.0.0.0/8"], "specialAddresses": ["127.0.0.1"]},
                        "resolution": {"kind": "static", "addresses": ["127.0.0.1"]},
                        "allowedRequestHeaders": [], "redirectDestinations": []}],
                    "limits": {"maximumRequestBodyBytes": 4096, "maximumResponseBodyBytes": 4096,
                        "maximumEncodedResponseBytes": 8192, "maximumHeaderBytes": 4096,
                        "maximumHeaders": 16, "maximumRedirects": 0},
                    "extraRoots": [], "publicRoots": false}},
            "bindings": [{"name": "http-binding", "tenant": "tests",
                "consumerService": "guest-http", "providerService": "http-host",
                "contract": "latent:http/client@0.2.0", "providerBinding": "http-installed"}]}
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

#[test]
fn protected_activation_runtime_starts_without_work_and_reaps_thirty_two_times() {
    let source = TempDir::new().unwrap();
    let path = source.path().join("node.json");
    let document = serde_json::json!({
        "formatVersion":1, "dataDirectory":source.path().join("unselected-data"),
        "nodeId":"activation-runtime-startup", "bind":"127.0.0.1:0",
        "credentials":[{"token":"LSF-PUBLIC-RUNTIME-STARTUP-TEST-ONLY",
            "subject":"operator","tenant":"tests","role":"operator"}],
        "budgetProfile":{"mode":"phase3","maximumOutboundRequests":8,
            "maximumBlobReadBytes":65536,"maximumBlobWriteBytes":65536},
        "audit":{"mode":"durable"}, "capabilityPolicies":{"formatVersion":1},
        "providers":{"formatVersion":1,
            "activationRuntime":{
                "identity":{"id":"activation","tenant":"tests","service":"runtime-host","epoch":7},
                "limits":{"tasks":8,"executors":2,"queuedWork":8,"waits":16,
                    "timers":8,"results":8,"nativeOwners":8}},
            "bindings":[{"name":"activation-binding","tenant":"tests","consumerService":"guest-runtime",
                "providerService":"runtime-host","contract":"latent:runtime/activation@0.1.0",
                "providerBinding":"activation-installed"}]}
    });
    std::fs::write(&path, serde_json::to_vec(&document).unwrap()).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
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
        let mut settings = NodeConfig::load(&path).unwrap().derive().unwrap();
        let installed = settings
            .providers
            .as_ref()
            .unwrap()
            .activation_runtime
            .as_ref()
            .unwrap();
        let expected_digest = installed.configuration_digest().unwrap();
        assert_eq!(
            settings.wasmtime.activation_runtime,
            Some(installed.runtime_limits())
        );
        settings.data_directory = source.path().join(format!("runtime-node-{ordinal}"));
        let node = invocation
            .block_on(StandaloneNode::start(
                settings,
                control.handle().clone(),
                RuntimeThreads::default(),
            ))
            .unwrap();
        let descriptors = serde_json::to_value(node.configured_providers()).unwrap();
        let actual = descriptors.as_array().unwrap();
        assert_eq!(actual.len(), 1);
        assert_eq!(
            actual[0]["capability"],
            latent_core::activation_runtime::CAPABILITY
        );
        assert_eq!(
            actual[0]["profile"],
            latent_core::activation_runtime::PROFILE
        );
        assert_eq!(actual[0]["configurationEpoch"], "7");
        assert_eq!(actual[0]["configurationDigest"], expected_digest.as_str());
        let stopped = invocation.block_on(node.shutdown()).unwrap();
        assert!(stopped.clean);
        let providers = stopped.providers.unwrap();
        assert!(providers.clean);
        assert_eq!(providers.secret_generations, 0);
        assert_eq!(providers.secret_references, 0);
        assert_eq!(providers.control_owners, 0);
        assert_eq!(providers.connections, 0);
        assert_eq!(providers.pending_requests, 0);
        assert_eq!(providers.running_requests, 0);
        assert_eq!(providers.workers, 0);
        assert_eq!(providers.cleanup_jobs, 0);
        assert_eq!(providers.failed_cleanup, 0);
        assert_eq!(providers.sessions, 0);
        assert_eq!(providers.handles, 0);
        assert_eq!(providers.calls, 0);
        assert_eq!(providers.results, 0);
        assert_eq!(providers.io_calls, 0);
        assert_eq!(providers.io_retained_bytes, 0);
    }
    control.shutdown_timeout(Duration::from_secs(5));
    invocation.shutdown_timeout(Duration::from_secs(5));
}

#[test]
fn protected_streaming_http_installation_retires_credentials_without_contact_thirty_two_times() {
    let source = TempDir::new().unwrap();
    let credentials = source.path().join("credentials");
    std::fs::create_dir(&credentials).unwrap();
    std::fs::set_permissions(&credentials, std::fs::Permissions::from_mode(0o700)).unwrap();
    let secret = credentials.join("authorization");
    std::fs::write(&secret, b"LSF-PUBLIC-STREAMING-STARTUP-TEST-ONLY").unwrap();
    std::fs::set_permissions(&secret, std::fs::Permissions::from_mode(0o600)).unwrap();
    let peer = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    peer.set_nonblocking(true).unwrap();
    let path = source.path().join("node.json");
    let document = serde_json::json!({
        "formatVersion":1, "dataDirectory":source.path().join("unselected-data"),
        "nodeId":"streaming-http-startup", "bind":"127.0.0.1:0",
        "credentials":[{"token":"LSF-PUBLIC-STREAMING-STARTUP-TEST-ONLY",
            "subject":"operator","tenant":"tests","role":"operator"}],
        "budgetProfile":{"mode":"phase3","maximumOutboundRequests":8,
            "maximumBlobReadBytes":65536,"maximumBlobWriteBytes":65536},
        "audit":{"mode":"durable"}, "capabilityPolicies":{"formatVersion":1},
        "providers":{"formatVersion":1,
            "httpStreaming":{
                "identity":{"id":"http-v3","tenant":"tests","service":"http-stream-host","epoch":5},
                "credentialDirectory":"credentials",
                "credentials":[{"reference":"startup","file":"authorization","destination":0,"header":"authorization"}],
                "configuration":{"formatVersion":1,
                    "destinations":[{"origin":{"scheme":"http","host":"127.0.0.1","port":peer.local_addr().unwrap().port()},
                        "addresses":{"networks":["127.0.0.1/32"],"specialAddresses":["127.0.0.1"]},
                        "resolution":{"kind":"static","addresses":["127.0.0.1"]},
                        "allowedRequestHeaders":[],"redirectDestinations":[]}],
                    "limits":{"maximumRequestBodyBytes":4096,"maximumResponseBodyBytes":4096,
                        "maximumEncodedResponseBytes":8192,"maximumHeaderBytes":1024,"maximumHeaders":8,"maximumRedirects":0},
                    "extraRoots":[],"publicRoots":false},
                "limits":{"maximumInputBytes":4096,"maximumOutputBytes":4096,
                    "maximumChunkBytes":1024,"maximumOutstandingChunks":2}},
            "bindings":[{"name":"stream-http-binding","tenant":"tests","consumerService":"guest-http",
                "providerService":"http-stream-host","contract":"latent:http/streaming@0.3.0","providerBinding":"stream-http-installed"}]}
    });
    std::fs::write(&path, serde_json::to_vec(&document).unwrap()).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
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
        let mut settings = NodeConfig::load(&path).unwrap().derive().unwrap();
        settings.data_directory = source.path().join(format!("node-{ordinal}"));
        let node = invocation
            .block_on(StandaloneNode::start(
                settings,
                control.handle().clone(),
                RuntimeThreads::default(),
            ))
            .unwrap();
        let descriptors = serde_json::to_value(node.configured_providers()).unwrap();
        let actual = descriptors.as_array().unwrap();
        assert_eq!(actual.len(), 1);
        assert_eq!(actual[0]["capability"], "latent:http/streaming@0.3.0");
        assert_eq!(actual[0]["profile"], "bounded-streaming-http-identity-v1");
        assert_eq!(actual[0]["configurationEpoch"], "5");
        let stopped = invocation.block_on(node.shutdown()).unwrap();
        assert!(stopped.clean);
        let providers = stopped.providers.unwrap();
        assert!(providers.clean);
        assert_eq!(providers.secret_generations, 0);
        assert_eq!(providers.secret_references, 0);
        assert_eq!(providers.io_retained_bytes, 0);
        assert_eq!(
            peer.accept().unwrap_err().kind(),
            std::io::ErrorKind::WouldBlock
        );
    }
    control.shutdown_timeout(Duration::from_secs(5));
    invocation.shutdown_timeout(Duration::from_secs(5));
}
