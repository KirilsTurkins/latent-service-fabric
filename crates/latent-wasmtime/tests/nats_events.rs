//! Actual guest publication through bounded authenticated TLS JetStream.
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "nats_events/component.rs"]
mod component;
#[path = "nats_events/fixture.rs"]
mod fixture;
#[path = "nats_events/packages.rs"]
mod packages;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;
use fixture::*;
#[path = "nats_events/audit.rs"]
mod audit;
#[path = "nats_events/bounds.rs"]
mod bounds;
#[path = "nats_events/faults.rs"]
mod faults;
#[path = "nats_events/proxy.rs"]
mod proxy;
#[path = "nats_events/stub.rs"]
mod stub;
use latent_capabilities::broker::{
    events::{Event, EventError, EventPublisher},
    pools::ProviderPoolLimits,
};
use latent_nats::{NatsConfig, NatsEndpoint, TopicMapping};
fn config() -> NatsConfig {
    config_for(
        std::env::var("LSF_NATS_TEST_PORT")
            .unwrap()
            .parse()
            .unwrap(),
        std::fs::read(std::env::var("LSF_NATS_TEST_CA").unwrap()).unwrap(),
    )
}
fn config_for(port: u16, root: Vec<u8>) -> NatsConfig {
    NatsConfig {
        format_version: 1,
        endpoint: NatsEndpoint {
            server_name: "127.0.0.1".into(),
            peer: std::net::SocketAddr::from(([127, 0, 0, 1], port)),
            allow_non_public_peer: true,
        },
        public_roots: false,
        extra_roots: vec![root],
        topics: vec![
            mapping("tests", "allowed", "lsf.tests.allowed", "ORDERS"),
            mapping("tests", "broker-denied", "lsf.tests.denied", "ORDERS"),
            mapping("tests", "denied", "lsf.tests.allowed", "ORDERS"),
            mapping("other", "tenant-only", "lsf.other.allowed", "OTHER"),
        ],
        idempotency_namespace: "lsf-public-test".into(),
        maximum_payload_bytes: 32768,
        timeout_millis: 2000,
    }
}
fn mapping(tenant: &str, topic: &str, subject: &str, stream: &str) -> TopicMapping {
    TopicMapping {
        tenant: tenant.into(),
        topic: topic.into(),
        subject: subject.into(),
        stream: stream.into(),
        duplicate_window_millis: 1000,
    }
}
fn control(operation: &str) -> serde_json::Value {
    let result = std::process::Command::new("python3")
        .args([
            std::env::var("LSF_NATS_TEST_CONTROL").unwrap(),
            std::env::var("LSF_NATS_TEST_PORT").unwrap(),
            std::env::var("LSF_NATS_TEST_PEM").unwrap(),
            operation.into(),
        ])
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "bounded NATS fixture control failed"
    );
    if result.stdout.is_empty() {
        serde_json::Value::Null
    } else {
        serde_json::from_slice(&result.stdout).unwrap()
    }
}
async fn invoke(f: &Fixture, mode: u32) -> u64 {
    let (request, control) = f.request("same-public-id", mode);
    let report = f.backend.invoke_contained(request, &control).await;
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    let GuestOutcome::Returned {
        output,
        consumption,
        ..
    } = report.outcome.unwrap()
    else {
        panic!("guest result");
    };
    assert!(control
        .budget
        .finalize_at(Some(&consumption), Instant::now())
        .violation()
        .is_none());
    f.idle();
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    serde_json::from_slice::<Vec<String>>(&output).unwrap()[0]
        .parse()
        .unwrap()
}
fn event(key: &str) -> Event {
    Event {
        topic: "allowed".into(),
        key: None,
        payload: b"synthetic-event".to_vec(),
        media_type: "text/plain".into(),
        attributes: vec![],
        idempotency_key: key.into(),
    }
}
async fn shutdown(f: &Fixture) {
    f.secrets.close();
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}
#[tokio::test]
#[ignore = "requires tools/run_nats_event_tests.py owned pinned TLS JetStream"]
async fn real_nats_guest_ack_denial_duplicates_and_connection_reuse() {
    control("reset-fixture");
    let f = Fixture::new(config(), None, ProviderPoolLimits::default()).await;
    assert_eq!(invoke(&f, 0).await, 2);
    assert_eq!(invoke(&f, 0).await, 3);
    assert_eq!(f.pools.snapshot().unwrap().connections, 1);
    assert_eq!(f.provider.snapshot().connection_attempts, 1);
    assert!(f.provider.snapshot().connection_reuses >= 1);
    assert_eq!(invoke(&f, 1).await, 1002);
    assert_eq!(invoke(&f, 2).await, 1002);
    assert_eq!(invoke(&f, 3).await, 1002);
    assert_eq!(control("info")["messages"], 1);
    // The broker's actual configured duplicate window, not a local provider cache.
    tokio::time::sleep(Duration::from_millis(1200)).await;
    assert_eq!(invoke(&f, 0).await, 4);
    assert_eq!(invoke(&f, 5).await, 5);
    assert_eq!(control("info")["messages"], 2);
    f.dormant_deployments().await;
    shutdown(&f).await;
}
#[tokio::test]
#[ignore = "requires tools/run_nats_event_tests.py owned pinned TLS JetStream"]
async fn real_nats_credentials_tls_budget_and_retained_receipt_ownership() {
    control("reset-fixture");
    let f = Fixture::new(config(), None, ProviderPoolLimits::default()).await;
    let (session, control) = f.session("retained");
    let completed = f
        .provider
        .publish(&session, event("retained"))
        .unwrap()
        .await
        .unwrap();
    assert_eq!(completed.receipt.sequence, 1);
    drop(session);
    assert!(f.io.snapshot().occupied_running_slots > 0);
    drop(completed);
    drop(control);
    f.idle();
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    fixture::write(
        &f.directory.path().join("secrets/password"),
        b"wrong-public-password",
    );
    f.secrets
        .reload(1, fixture::specs(&f.config))
        .unwrap()
        .await
        .unwrap();
    assert_eq!(invoke(&f, 0).await, 1002);
    fixture::write(
        &f.directory.path().join("secrets/password"),
        b"lsf-public-nats-password",
    );
    f.secrets
        .reload(2, fixture::specs(&f.config))
        .unwrap()
        .await
        .unwrap();
    tokio::time::sleep(Duration::from_millis(120)).await;
    assert!(invoke(&f, 0).await < 1000);
    let attempts = f.provider.snapshot().connection_attempts;
    let (session, budget_owner) = f.session("zero-requests");
    budget_owner
        .budget
        .consume(latent_core::BudgetDimension::OutboundRequests, 8)
        .unwrap();
    assert_eq!(
        f.provider
            .publish(&session, event("no-budget"))
            .unwrap()
            .await
            .err(),
        Some(EventError::BudgetExhausted)
    );
    drop(session);
    drop(budget_owner);
    assert_eq!(f.provider.snapshot().connection_attempts, attempts);
    let (session, budget_owner) = f.session("revoked");
    f.revoke();
    let failure = match f.provider.publish(&session, event("revoked")) {
        Ok(future) => future.await.err(),
        Err(error) => Some(error),
    };
    assert_eq!(failure, Some(EventError::PermissionDenied));
    drop(session);
    drop(budget_owner);
    f.idle();
    shutdown(&f).await;
    let mut wrong = config();
    wrong.endpoint.server_name = "wrong.invalid".into();
    let f = Fixture::new(wrong, None, ProviderPoolLimits::default()).await;
    assert_eq!(invoke(&f, 0).await, 1006);
    assert_eq!(f.pools.snapshot().unwrap().connections, 0);
    shutdown(&f).await;
}
