//! Every actual owned ResourceRequest variant, including nested text copies.
use super::*;
use latent_policy::capability::{HttpOrigin, RecoveryScopeKind, StreamEndpoint, StreamTransport};

#[test]
fn original_handle_native_all_shipping_owned_text_shapes_include_nested_copies() {
    let origin = HttpOrigin {
        scheme: "https".into(),
        host: "api.test".into(),
        port: 443,
    };
    let endpoint = StreamEndpoint {
        host: "opaque.test".into(),
        port: 443,
        transport: StreamTransport::HostTls,
    };
    let cases: Vec<(ResourceTarget<'_>, &[&str])> = vec![
        (ResourceTarget::Context, &[]),
        (ResourceTarget::Clock, &[]),
        (ResourceTarget::Random, &[]),
        (ResourceTarget::Log { level: "info" }, &["info"]),
        (
            ResourceTarget::Http {
                origin: &origin,
                method: "GET",
                path: "/closed",
            },
            &["https", "api.test", "GET", "/closed"],
        ),
        (
            ResourceTarget::Stream {
                endpoint: &endpoint,
            },
            &["opaque.test"],
        ),
        (
            ResourceTarget::Blob {
                namespace: "objects",
            },
            &["objects"],
        ),
        (
            ResourceTarget::Secrets {
                reference: "test-key",
            },
            &["test-key"],
        ),
        (ResourceTarget::Events { subject: "events" }, &["events"]),
        (ResourceTarget::Telemetry { name: "count" }, &["count"]),
        (
            ResourceTarget::Service {
                service: "worker",
                publication: "published",
            },
            &["worker", "published"],
        ),
        (
            ResourceTarget::State {
                namespace: "state",
                incarnation: 1,
                entity: Some("record"),
                recovery_kind: RecoveryScopeKind::OriginalCaller,
                recovery_scope: "scope",
                result_policy: "reply",
            },
            &["state", "record", "scope", "reply"],
        ),
        (
            ResourceTarget::State {
                namespace: "state",
                incarnation: 1,
                entity: None,
                recovery_kind: RecoveryScopeKind::OriginalCaller,
                recovery_scope: "scope",
                result_policy: "reply",
            },
            &["state", "scope", "reply"],
        ),
    ];
    for (resource, text) in cases {
        let owned = super::super::own_resource(resource);
        assert_eq!(owned.target(), resource);
        // Independent enumeration of the actual copied buffers. Fixed enum,
        // integer and transport fields are already in the original Arc layout.
        let expected = 4
            + 64
            + text
                .iter()
                .map(|value| value.len() as u64 + 64)
                .sum::<u64>();
        assert_eq!(payload_bytes("read", resource).unwrap(), expected);
    }
    assert!(payload_bytes("invalid operation", ResourceTarget::Clock).is_err());
}
