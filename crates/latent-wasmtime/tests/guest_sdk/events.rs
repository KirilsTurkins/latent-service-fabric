use super::{input, package, run, support};
#[path = "../nats_events/component.rs"]
#[allow(dead_code, unused_imports)]
mod component;
#[path = "../nats_events/fixture.rs"]
#[allow(dead_code, unused_imports)]
mod fixture;
#[path = "../nats_events/packages.rs"]
#[allow(dead_code, unused_imports)]
mod packages;
use fixture::*;

use latent_nats::{NatsConfig, NatsEndpoint, TopicMapping};
#[path = "../nats_events/proxy.rs"]
#[allow(dead_code)]
mod proxy;
#[path = "../nats_events/stub.rs"]
#[allow(dead_code)]
mod stub;
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

#[tokio::test]
#[ignore = "Requires compiled guest SDK fixtures"]
async fn typed_event_receipt_denial_and_uncertainty_do_not_retry() {
    for language in ["rust", "c"] {
        for mode in [stub::Mode::Healthy, stub::Mode::Malformed] {
            let root = tempfile::tempdir().unwrap();
            let publication = package::publish(root.path(), &format!("{language}-events")).await;
            let peer = stub::Stub::new(mode).await;
            let f = Fixture::with_publication(
                peer.config.clone(),
                None,
                Default::default(),
                Some(publication),
            )
            .await;
            let (mut request, control) = f.request("sdk-event", 0);
            input(&mut request, 0, "allowed", 1);
            assert_eq!(
                run(&f.backend, request, &control).await,
                if matches!(mode, stub::Mode::Healthy) {
                    1
                } else {
                    11
                }
            );
            f.idle();
            assert_eq!(peer.publishes.load(Ordering::Acquire), 1);
            let (mut request, control) = f.request("sdk-event-denied", 0);
            input(&mut request, 0, "denied", 2);
            assert_eq!(run(&f.backend, request, &control).await, 10);
            f.idle();
            assert_eq!(peer.publishes.load(Ordering::Acquire), 1);
            assert!(f
                .pools
                .shutdown(Instant::now() + Duration::from_secs(2))
                .await
                .unwrap()
                .is_clean());
            peer.close().await;
        }
    }
}
