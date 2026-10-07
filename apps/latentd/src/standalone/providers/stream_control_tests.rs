use crate::config::{NodeConfig, NodeSettings, StreamReloadGuard};
use crate::standalone::{RuntimeThreads, StandaloneNode};
use latent_core::PlatformErrorCode;
use serde_json::{json, Value};
use std::{fs, os::unix::fs::PermissionsExt, path::PathBuf, time::Duration};
use tempfile::TempDir;
use tokio::runtime::{Builder, Runtime};

struct Fixture {
    _directory: TempDir,
    path: PathBuf,
    document: Value,
    listener: std::net::TcpListener,
    guard: StreamReloadGuard,
}

impl Fixture {
    fn new() -> Self {
        let directory = TempDir::new().unwrap();
        fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700)).unwrap();
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let path = directory.path().join("node.json");
        let document = json!({
            "formatVersion":1,"dataDirectory":directory.path().join("data"),
            "nodeId":"stream-control","bind":"127.0.0.1:0",
            "credentials":[{"token":"LSF-PUBLIC-STREAM-CONTROL-TEST-ONLY",
                "subject":"administrator","tenant":"tests","role":"admin"}],
            "budgetProfile":{"mode":"phase3","maximumOutboundRequests":8},
            "audit":{"mode":"durable"},"capabilityPolicies":{"formatVersion":1},
            "providers":{"formatVersion":1,
                "outboundStreams":{"identity":{"id":"streams","tenant":"tests","service":"stream-host","epoch":1},
                    "configuration":{"formatVersion":1,"profile":"lsf-outbound-streams-v1",
                        "destinations":[{"endpoint":{"host":"127.0.0.1","port":listener.local_addr().unwrap().port(),"transport":"tcp"},
                            "addresses":{"networks":["127.0.0.1/32"],"specialAddresses":["127.0.0.1"]},
                            "resolution":{"kind":"static","addresses":["127.0.0.1"]}}],
                        "limits":{"maximumTransferBytes":65536,"idleTimeoutMillis":1000,"absoluteTimeoutMillis":5000}}},
                "bindings":[{"name":"stream-binding","tenant":"tests","consumerService":"guest-stream",
                    "providerService":"stream-host","contract":"latent:network/streams@0.1.0","providerBinding":"streams-installed"}]}
        });
        fs::write(&path, serde_json::to_vec(&document).unwrap()).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        let (config, guard) = NodeConfig::load_with_stream_reload(&path).unwrap();
        config.derive().unwrap();
        Self {
            _directory: directory,
            path,
            document,
            listener,
            guard: guard.unwrap(),
        }
    }

    fn settings(&self) -> NodeSettings {
        NodeConfig::load_with_stream_reload(&self.path)
            .unwrap()
            .0
            .derive()
            .unwrap()
    }

    fn rewrite(&self, document: &Value) {
        fs::write(&self.path, serde_json::to_vec(document).unwrap()).unwrap();
    }

    fn rotate_input(&self, epoch: u64) {
        let mut document = self.document.clone();
        document["providers"]["outboundStreams"]["identity"]["epoch"] = json!(epoch);
        document["providers"]["outboundStreams"]["configuration"]["limits"]
            ["maximumTransferBytes"] = json!(32768);
        self.rewrite(&document);
    }

    fn untouched_peer(&self) {
        assert_eq!(
            self.listener.accept().err().unwrap().kind(),
            std::io::ErrorKind::WouldBlock
        );
    }
}

fn runtimes() -> (Runtime, Runtime) {
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
    (control, invocation)
}

fn clean(node: StandaloneNode, invocation: &Runtime) {
    let report = invocation.block_on(node.shutdown()).unwrap();
    assert!(report.clean);
    let providers = report.providers.unwrap();
    assert!(providers.clean);
    assert_eq!(providers.stream_maintenance_owners, 0);
    assert_eq!(providers.stream_owners, 0);
    assert_eq!(providers.stream_connections, 0);
    assert_eq!(providers.stream_pending_operations, 0);
    assert_eq!(providers.stream_retained_chunks, 0);
}

#[test]
fn protected_reload_publishes_actual_new_reference_and_never_repeats_an_epoch() {
    let fixture = Fixture::new();
    let (control, invocation) = runtimes();
    let mut node = invocation
        .block_on(StandaloneNode::start(
            fixture.settings(),
            control.handle().clone(),
            RuntimeThreads::default(),
        ))
        .unwrap();
    let old = node
        .providers
        .as_ref()
        .unwrap()
        .stream_binding_reference
        .as_ref()
        .unwrap()
        .clone();
    let catalog = node
        .providers
        .as_ref()
        .unwrap()
        .stream_catalog
        .as_ref()
        .unwrap()
        .clone();
    let before = catalog.binding_version().unwrap();
    fixture.rotate_input(2);
    let result = invocation
        .block_on(node.reload_outbound_streams(&fixture.guard))
        .unwrap();
    assert_eq!(result.configured_generation, 2);
    assert_eq!(result.installed_binding_generation, 2);
    assert!(!result.binding_publication_pending);
    assert!(!result.execution_permission);
    assert!(!result.stream.current_generation_retired);
    assert_eq!(result.provider.configuration_epoch, "2");
    assert_ne!(
        result.provider.configuration_digest,
        old.configuration_digest()
    );
    let replacement = node
        .providers
        .as_ref()
        .unwrap()
        .stream_binding_reference
        .as_ref()
        .unwrap();
    assert!(!old.same_installation(replacement));
    let published = catalog.binding_version().unwrap();
    assert_ne!(published, before);
    assert_eq!(
        invocation
            .block_on(node.reload_outbound_streams(&fixture.guard))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::StateConflict
    );
    assert_eq!(catalog.binding_version().unwrap(), published);
    fixture.untouched_peer();
    clean(node, &invocation);
    fixture.untouched_peer();
    control.shutdown_timeout(Duration::from_secs(5));
    invocation.shutdown_timeout(Duration::from_secs(5));
}

#[test]
fn catalog_contention_preserves_configured_and_confirmed_generations_until_explicit_publication() {
    let fixture = Fixture::new();
    let (control, invocation) = runtimes();
    let mut node = invocation
        .block_on(StandaloneNode::start(
            fixture.settings(),
            control.handle().clone(),
            RuntimeThreads::default(),
        ))
        .unwrap();
    let owner = node.providers.as_ref().unwrap();
    let catalog = owner.stream_catalog.as_ref().unwrap().clone();
    let old = owner.stream_binding_reference.as_ref().unwrap().clone();
    let pools = owner.pools.clone();
    let before = catalog.binding_version().unwrap();
    let held = invocation
        .block_on(
            catalog.prepare_provider_reference_update(&old, old.clone(), |bytes| {
                pools.reserve_protocol_metadata(bytes)
            }),
        )
        .unwrap();
    fixture.rotate_input(2);
    let failed = invocation
        .block_on(node.reload_outbound_streams(&fixture.guard))
        .unwrap();
    assert_eq!(
        failed.outcome,
        "installed-generation-binding-publication-unconfirmed"
    );
    assert_eq!(failed.configured_generation, 2);
    assert_eq!(failed.installed_binding_generation, 1);
    assert!(failed.binding_publication_pending);
    assert!(failed.failure_code.is_some());
    assert_eq!(catalog.binding_version().unwrap(), before);
    assert!(node
        .providers
        .as_ref()
        .unwrap()
        .stream_binding_reference
        .as_ref()
        .unwrap()
        .same_installation(&old));
    drop(held);
    // There was no automatic retry or old-generation restoration on Drop.
    assert_eq!(catalog.binding_version().unwrap(), before);
    let status = node.outbound_stream_control_status().unwrap();
    assert!(status.binding_publication_pending);
    let recovered = invocation
        .block_on(node.publish_outbound_stream_bindings(&fixture.guard))
        .unwrap();
    assert_eq!(recovered.configured_generation, 2);
    assert_eq!(recovered.installed_binding_generation, 2);
    assert!(!recovered.binding_publication_pending);
    assert_eq!(
        recovered.stream.retired_generations,
        failed.stream.retired_generations
    );
    assert!(!recovered.execution_permission);
    fixture.untouched_peer();
    clean(node, &invocation);
    control.shutdown_timeout(Duration::from_secs(5));
    invocation.shutdown_timeout(Duration::from_secs(5));
}

#[test]
fn foreign_protected_guard_and_static_owner_change_cannot_rotate_or_publish() {
    let fixture = Fixture::new();
    let (control, invocation) = runtimes();
    let mut node = invocation
        .block_on(StandaloneNode::start(
            fixture.settings(),
            control.handle().clone(),
            RuntimeThreads::default(),
        ))
        .unwrap();
    let alternate = fixture.path.with_file_name("foreign-node.json");
    fs::write(&alternate, serde_json::to_vec(&fixture.document).unwrap()).unwrap();
    fs::set_permissions(&alternate, fs::Permissions::from_mode(0o600)).unwrap();
    let foreign = NodeConfig::load_with_stream_reload(&alternate)
        .unwrap()
        .1
        .unwrap();
    let before = node.outbound_stream_control_status().unwrap();
    assert_eq!(
        invocation
            .block_on(node.reload_outbound_streams(&foreign))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::StateConflict
    );
    assert!(invocation
        .block_on(node.publish_outbound_stream_bindings(&foreign))
        .is_err());
    assert!(invocation
        .block_on(node.drain_outbound_streams(&foreign))
        .is_err());
    let mut changed = fixture.document.clone();
    changed["providers"]["outboundStreams"]["identity"]["epoch"] = json!(2);
    changed["credentials"][0]["tenant"] = json!("foreign");
    fixture.rewrite(&changed);
    assert!(invocation
        .block_on(node.reload_outbound_streams(&fixture.guard))
        .is_err());
    let after = node.outbound_stream_control_status().unwrap();
    assert_eq!(after.configured_generation, before.configured_generation);
    assert_eq!(
        after.installed_binding_generation,
        before.installed_binding_generation
    );
    assert!(!after.stream.current_generation_retired);
    assert!(!after.stream.stopped);
    fixture.untouched_peer();
    clean(node, &invocation);
    control.shutdown_timeout(Duration::from_secs(5));
    invocation.shutdown_timeout(Duration::from_secs(5));
}

#[test]
fn explicit_drain_retires_current_owner_and_requires_a_normal_restart_for_fresh_work() {
    let fixture = Fixture::new();
    let (control, invocation) = runtimes();
    let mut node = invocation
        .block_on(StandaloneNode::start(
            fixture.settings(),
            control.handle().clone(),
            RuntimeThreads::default(),
        ))
        .unwrap();
    let result = invocation
        .block_on(node.drain_outbound_streams(&fixture.guard))
        .unwrap();
    assert_eq!(result.outcome, "drained");
    assert!(result.stream.stopped);
    assert!(result.stream.current_generation_retired);
    assert_eq!(result.stream.usage.owners, 0);
    fixture.rotate_input(2);
    assert!(invocation
        .block_on(node.reload_outbound_streams(&fixture.guard))
        .is_err());
    assert!(invocation
        .block_on(node.publish_outbound_stream_bindings(&fixture.guard))
        .is_err());
    fixture.untouched_peer();
    clean(node, &invocation);
    control.shutdown_timeout(Duration::from_secs(5));
    invocation.shutdown_timeout(Duration::from_secs(5));
}

#[test]
fn catalog_rejects_equal_public_descriptor_from_another_actual_provider_owner() {
    let first = Fixture::new();
    let second = Fixture::new();
    // Make the two public stream descriptors equal despite distinct broker owners.
    let mut second_document = second.document.clone();
    second_document["providers"] = first.document["providers"].clone();
    second.rewrite(&second_document);
    let second_settings = NodeConfig::load_with_stream_reload(&second.path)
        .unwrap()
        .0
        .derive()
        .unwrap();
    let (control, invocation) = runtimes();
    let first_node = invocation
        .block_on(StandaloneNode::start(
            first.settings(),
            control.handle().clone(),
            RuntimeThreads::default(),
        ))
        .unwrap();
    let second_node = invocation
        .block_on(StandaloneNode::start(
            second_settings,
            control.handle().clone(),
            RuntimeThreads::default(),
        ))
        .unwrap();
    let first_owner = first_node.providers.as_ref().unwrap();
    let second_owner = second_node.providers.as_ref().unwrap();
    let catalog = first_owner.stream_catalog.as_ref().unwrap();
    let expected = first_owner.stream_binding_reference.as_ref().unwrap();
    let foreign = second_owner.stream_binding_reference.as_ref().unwrap();
    assert_eq!(
        expected.configuration_digest(),
        foreign.configuration_digest()
    );
    assert_eq!(
        expected.configuration_epoch(),
        foreign.configuration_epoch()
    );
    assert!(!expected.same_installation(foreign));
    let before = catalog.binding_version().unwrap();
    let result = invocation.block_on(catalog.prepare_provider_reference_update(
        expected,
        foreign.clone(),
        |bytes| first_owner.pools.reserve_protocol_metadata(bytes),
    ));
    assert!(result.is_err());
    assert_eq!(catalog.binding_version().unwrap(), before);
    // A larger foreign epoch passes descriptor epoch ordering, but cannot
    // pass the actual broker-owner comparison even with no consumer plans.
    let foreign_config = second
        .settings()
        .providers
        .unwrap()
        .outbound_streams
        .unwrap()
        .configuration;
    let foreign_new = second_owner
        .streams
        .as_ref()
        .unwrap()
        .rotate(1, 2, foreign_config)
        .unwrap();
    let result = invocation.block_on(catalog.prepare_provider_reference_update(
        expected,
        foreign_new,
        |bytes| first_owner.pools.reserve_protocol_metadata(bytes),
    ));
    assert!(result.is_err());
    assert_eq!(catalog.binding_version().unwrap(), before);
    first.untouched_peer();
    second.untouched_peer();
    clean(second_node, &invocation);
    clean(first_node, &invocation);
    control.shutdown_timeout(Duration::from_secs(5));
    invocation.shutdown_timeout(Duration::from_secs(5));
}
