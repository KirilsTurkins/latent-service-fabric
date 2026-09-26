use latent_nats::{NatsConfig, NatsEndpoint, TopicMapping};

pub fn config() -> NatsConfig {
    config_for(
        std::env::var("LSF_NATS_TEST_PORT")
            .unwrap()
            .parse()
            .unwrap(),
        std::fs::read(std::env::var("LSF_NATS_TEST_CA").unwrap()).unwrap(),
    )
}
pub fn config_for(port: u16, root: Vec<u8>) -> NatsConfig {
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
