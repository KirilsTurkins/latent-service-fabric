use crate::http_support::*;
use latent_ingress::http::*;
use serde_json::{json, Value};

#[test]
fn exact_request_codec_keeps_repetitions_octets_and_separate_trusted_authority() {
    let pool = pool();
    let headers = [
        HeaderView {
            name: "Host",
            value: b"EXAMPLE.TEST:443",
        },
        HeaderView {
            name: "Content-Length",
            value: b"3",
        },
        HeaderView {
            name: "Content-Type",
            value: b"application/octet-stream",
        },
        HeaderView {
            name: "Cookie",
            value: b"a=1",
        },
        HeaderView {
            name: "Cookie",
            value: b"b=2",
        },
        HeaderView {
            name: "X-Octets",
            value: &[128, 255],
        },
        HeaderView {
            name: "Authorization",
            value: b"Bearer caller-secret",
        },
        HeaderView {
            name: "Forwarded",
            value: b"host=attacker;proto=http",
        },
        HeaderView {
            name: "X-Forwarded-User",
            value: b"administrator",
        },
        HeaderView {
            name: "Traceparent",
            value: b"caller-trace",
        },
        HeaderView {
            name: "Baggage",
            value: b"role=administrator",
        },
    ];
    let mut raw = head("POST", &headers);
    raw.target = "/api/%7euser?a=1&a=2+3";
    let mut collector = pool.begin(raw, deadline()).unwrap();
    assert_eq!(collector.target().path(), "/api/~user");
    collector.append(&[0, 255]).unwrap();
    collector.append(b"A").unwrap();
    let invocation = collector
        .finish(context())
        .unwrap()
        .into_invocation()
        .unwrap();
    assert_eq!(
        invocation.input(),
        include_str!("../fixtures/http-request-v1.json")
            .trim()
            .as_bytes()
    );
    assert_eq!(invocation.context().principal().subject, "user-a");
    assert_eq!(
        invocation.context().principal().tenant.as_ref().unwrap().0,
        "tenant-a"
    );
    assert_eq!(
        invocation.context().trace().trace_id.0,
        "0123456789abcdef0123456789abcdef"
    );
    let value: Value = serde_json::from_slice(invocation.input()).unwrap();
    assert!(value[0].get("principal").is_none());
    assert!(value[0].get("context").is_none());
    assert_eq!(pool.snapshot().reserved_bytes, EXCHANGE_RESERVATION_BYTES);
    drop(invocation);
    assert_eq!(pool.snapshot().reserved_bytes, 0);
}

#[test]
fn exact_response_codec_preserves_cookies_media_octets_and_partial_writes() {
    let pool = pool();
    let mut delivery = deliver(&pool, "POST", RESPONSE.as_bytes());
    assert_eq!(delivery.cause(), DeliveryCause::Application);
    assert_eq!(delivery.status(), 201);
    assert_eq!(delivery.content_length(), Some(3));
    assert_eq!(delivery.media_type(), Some("text/html; charset=utf-8"));
    let fields: Vec<_> = delivery.headers().map(|h| (h.name, h.value)).collect();
    assert_eq!(
        fields,
        [
            ("set-cookie", b"a=1; HttpOnly".as_slice()),
            ("set-cookie", b"b=2".as_slice())
        ]
    );
    assert_eq!(delivery.advance(1), Err(HttpError::IncompleteDelivery));
    delivery.mark_headers_written().unwrap();
    assert_eq!(delivery.remaining_body().unwrap(), &[65, 0, 255]);
    delivery.advance(1).unwrap();
    assert_eq!(delivery.remaining_body().unwrap(), &[0, 255]);
    delivery.advance(2).unwrap();
    assert_eq!(delivery.finish().unwrap().body_bytes, 3);
    assert_eq!(pool.snapshot().active_exchanges, 0);
}

#[test]
fn no_body_statuses_head_and_representation_length_have_explicit_framing() {
    let pool = pool();
    for (method, status, length, expected) in [
        ("HEAD", 200, json!({"some":"1234"}), Some(1234)),
        ("GET", 304, json!({"some":"1234"}), Some(1234)),
        ("GET", 204, json!({"none":null}), None),
        ("GET", 205, json!({"none":null}), Some(0)),
    ] {
        let mut value = response();
        value[0]["status"] = json!(status);
        value[0]["body-base64"] = json!("");
        value[0]["representation-length"] = length;
        let mut result = deliver(&pool, method, &serde_json::to_vec(&value).unwrap());
        assert_eq!(result.cause(), DeliveryCause::Application);
        assert_eq!(result.content_length(), expected);
        result.mark_headers_written().unwrap();
        result.finish().unwrap();
    }
}

#[test]
fn application_error_status_and_platform_errors_remain_distinct() {
    use latent_core::PlatformErrorCode as Code;
    let pool = pool();
    let mut value = response();
    value[0]["status"] = json!(404);
    let app = deliver(&pool, "GET", &serde_json::to_vec(&value).unwrap());
    assert_eq!(app.status(), 404);
    assert_eq!(app.cause(), DeliveryCause::Application);
    drop(app);
    for (code, status) in [
        (Code::NotFound, 404),
        (Code::PermissionDenied, 403),
        (Code::Unauthenticated, 401),
        (Code::GuestTrap, 502),
        (Code::ResourceExhausted, 503),
        (Code::DeadlineExceeded, 504),
        (Code::Internal, 500),
        (Code::StateConflict, 409),
    ] {
        let result = invocation(&pool, "GET")
            .complete(Outcome::Platform(code))
            .unwrap();
        assert_eq!(result.status(), status);
        assert_eq!(result.cause(), DeliveryCause::Platform(code));
    }
    assert_eq!(
        invocation(&pool, "GET")
            .complete(Outcome::Platform(Code::Cancelled))
            .err(),
        Some(HttpError::Disconnected)
    );
    let result = invocation(&pool, "GET")
        .complete(Outcome::DeclaredError)
        .unwrap();
    assert_eq!(result.status(), 502);
    assert_eq!(result.cause(), DeliveryCause::InvalidGuestResponse);
}

#[test]
fn canonical_targets_preserve_query_semantics_and_normalize_only_once() {
    for (host, target, authority, path, query) in [
        (
            "EXAMPLE.TEST:443",
            "/a/%7e?q=1&q=2+3",
            "example.test",
            "/a/~",
            Some("q=1&q=2+3"),
        ),
        (
            "[2001:0db8::1]:443",
            "/%c3%a4?",
            "[2001:db8::1]",
            "/%C3%A4",
            Some(""),
        ),
        (
            "example.test",
            "/search?next=%2fa%5cb%25&q=%7e+%26%3d",
            "example.test",
            "/search",
            Some("next=%2Fa%5Cb%25&q=~+%26%3D"),
        ),
        ("127.0.0.1:8443", "/", "127.0.0.1:8443", "/", None),
    ] {
        let canonical = CanonicalTarget::parse(Scheme::Https, host, target).unwrap();
        assert_eq!(canonical.authority(), authority);
        assert_eq!(canonical.path(), path);
        assert_eq!(canonical.query(), query);
        let full = query.map_or_else(|| path.to_owned(), |q| format!("{path}?{q}"));
        assert_eq!(
            CanonicalTarget::parse(Scheme::Https, authority, &full).unwrap(),
            canonical
        );
    }
    assert_eq!(
        CanonicalTarget::parse(Scheme::Http, "example.test:80", "/")
            .unwrap()
            .authority(),
        "example.test"
    );
}
