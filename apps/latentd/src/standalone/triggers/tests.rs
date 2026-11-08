//! Actual owner/pools/credential tests; these do not qualify TLS inbox delivery.
use super::*;
use crate::{
    config::NodeConfig,
    standalone::{RuntimeThreads, StandaloneNode},
};
use latent_nats::triggers::TriggerConfig;
use std::{fs, os::unix::fs::PermissionsExt, time::Duration};

const WATCHDOG: Duration = Duration::from_secs(5);

async fn owner() -> (
    tempfile::TempDir,
    StandaloneNode,
    latent_secrets::LocalSecretStore,
) {
    let root = tempfile::tempdir().unwrap();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let secrets = root.path().join("input-secrets");
    fs::create_dir(&secrets).unwrap();
    fs::set_permissions(&secrets, fs::Permissions::from_mode(0o700)).unwrap();
    fs::write(
        secrets.join("credential"),
        b"LSF-PUBLIC-INPUT-CONTROL-TEST-ONLY",
    )
    .unwrap();
    fs::set_permissions(
        secrets.join("credential"),
        fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    let document = serde_json::json!({
        "formatVersion":1,"dataDirectory":root.path().join("node"),"nodeId":"input-control",
        "bind":"127.0.0.1:0","credentials":[{"token":"LSF-PUBLIC-INPUT-CONTROL-TEST-ONLY",
            "subject":"operator","tenant":"tests","role":"operator"}],
        "budgetProfile":{"mode":"phase3","maximumOutboundRequests":8,
            "maximumBlobReadBytes":65536,"maximumBlobWriteBytes":65536},
        "audit":{"mode":"durable"},"capabilityPolicies":{"formatVersion":1},
        "providers":{"formatVersion":1,
            "context":{"identity":{"id":"context","tenant":"tests",
                "service":"runtime-host","epoch":1}},
            "bindings":[{"name":"context-binding","tenant":"tests",
                "consumerService":"server","providerService":"runtime-host",
                "contract":"latent:context/context@0.1.0","providerBinding":"context-installed"}]}
    });
    let config_path = root.path().join("node.json");
    fs::write(&config_path, serde_json::to_vec(&document).unwrap()).unwrap();
    fs::set_permissions(&config_path, fs::Permissions::from_mode(0o600)).unwrap();
    let config = NodeConfig::load(&config_path).unwrap();
    let mut node = StandaloneNode::start(
        config.derive().unwrap(),
        tokio::runtime::Handle::current(),
        RuntimeThreads::default(),
    )
    .await
    .unwrap();
    let configuration = TriggerConfig::from_json(&serde_json::to_vec(&serde_json::json!({
        "formatVersion":1,"endpoint":{"peer":"127.0.0.1:4222","serverName":"localhost","allowNonPublicPeer":true},
        "publicRoots":true,"extraRoots":[],"bindings":[{
            "id":"input-control","tenant":"tests","principalSubject":"input-control",
            "service":"absent-controlled-test","contract":"tests:control/api@1.0.0","function":"run",
            "route":null,"stream":"CONTROL","consumer":"PROCESS","filterSubject":"control.input",
            "budget":{"cpuFuel":1000,"memoryBytes":65536,"wallTimeMillis":1000,
                "childCalls":0,"outboundRequests":0,"blobReadBytes":0,"blobWriteBytes":0,"logBytes":0}
        }],"maximumPayloadBytes":1024,"operationTimeoutMillis":1000,"pollIntervalMillis":10,
        "maximumDeliveries":3,"ackWaitMillis":3000,"redeliveryDelayMillis":100
    })).unwrap()).unwrap();
    let (poller, secret_owner) = node
        .providers
        .as_ref()
        .unwrap()
        .install_control_test_poller(secrets, configuration)
        .await;
    node.triggers = Some(TriggerOwner::start(poller, node.manager.clone()));
    (root, node, secret_owner)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_incoming_owner_pauses_before_pull_and_resumes_without_replacing_scope_or_task() {
    let (_root, node, secret) = owner().await;
    let original = node.transactional_trigger_status().unwrap();
    assert!(!original.accepting);
    assert_eq!(
        (
            original.active_deliveries,
            original.pulls,
            original.executions
        ),
        (0, 0, 0)
    );
    let paused = node.pause_transactional_triggers().unwrap();
    assert!(!paused.accepting);
    tokio::task::yield_now().await;
    assert_eq!(node.transactional_trigger_status().unwrap().pulls, 0);
    let task = node.triggers.as_ref().unwrap().task.as_ref().unwrap().id();
    let resumed = node.resume_transactional_triggers().unwrap();
    assert!(resumed.accepting);
    assert_eq!(resumed.configuration_epoch, original.configuration_epoch);
    assert_eq!(resumed.triggers, original.triggers);
    assert_eq!(
        node.triggers.as_ref().unwrap().task.as_ref().unwrap().id(),
        task
    );
    // The same task can observe readiness on another worker. This case makes
    // no claim about an accepted broker delivery; its absent target refuses
    // node admission before any pull, under the ordinary manager's own policy.
    assert!(!node.pause_transactional_triggers().unwrap().accepting);
    secret.close();
    let stopped = tokio::time::timeout(WATCHDOG, node.shutdown())
        .await
        .unwrap()
        .unwrap();
    assert!(stopped.clean && stopped.triggers.unwrap().joined);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn permanent_original_stop_refuses_resume_and_joins_real_poller_without_new_owners() {
    let (_root, node, secret) = owner().await;
    let original = node.triggers.as_ref().unwrap();
    original.stop.send_replace(true);
    assert!(node.resume_transactional_triggers().is_err());
    assert!(!node.transactional_trigger_status().unwrap().accepting);
    secret.close();
    let stopped = tokio::time::timeout(WATCHDOG, node.shutdown())
        .await
        .unwrap()
        .unwrap();
    let input = stopped.triggers.unwrap();
    assert!(input.clean && input.joined && !input.status.accepting);
    assert_eq!(
        (
            input.status.active_deliveries,
            input.status.pulls,
            input.status.executions
        ),
        (0, 0, 0)
    );
    assert!(stopped.clean);
}
