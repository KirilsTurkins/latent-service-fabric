use crate::http_support::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_ingress::http::*;
use serde_json::json;

#[test]
fn malformed_authorities_and_ambiguous_targets_never_reach_routing() {
    for host in [
        "",
        "example.test.",
        "user@example.test",
        "127.1",
        "127.000.0.1",
        "example:0443",
        "example:0",
        "example:65536",
        "a..test",
        "-x.test",
        "x_.test",
        "[::1]evil",
        "[fe80::1%lo]",
        "a/b",
        "::1",
        "example.test\r\nadmin: yes",
    ] {
        assert!(
            CanonicalTarget::parse(Scheme::Https, host, "/").is_err(),
            "{host:?}"
        );
    }
    for target in [
        "",
        "*",
        "https://example.test/a",
        "//other/a",
        "/a//b",
        "/a/../b",
        "/./x",
        "/a/%2e%2e/b",
        "/%2fsecret",
        "/%5Csecret",
        "/%252e%252e",
        "/%00",
        "/%0d%0a",
        "/a\\b",
        "/#fragment",
        "/%",
        "/%G0",
        "/caf\u{e9}",
        "/a b",
    ] {
        assert!(
            CanonicalTarget::parse(Scheme::Https, "example.test", target).is_err(),
            "{target:?}"
        );
    }
    assert!(CanonicalTarget::parse(
        Scheme::Https,
        "example.test",
        &format!("/{}", "a".repeat(MAX_TARGET_BYTES))
    )
    .is_err());
}

#[test]
fn head_validation_rejects_smuggling_fields_duplicates_controls_and_size_before_copy() {
    let pool = pool();
    for extra in [
        HeaderView {
            name: "Host",
            value: b"example.test",
        },
        HeaderView {
            name: "host",
            value: b"other.test",
        },
        HeaderView {
            name: "content-length",
            value: b"03",
        },
        HeaderView {
            name: "content-length",
            value: b"3,3",
        },
        HeaderView {
            name: "content-length",
            value: b"+3",
        },
        HeaderView {
            name: "transfer-encoding",
            value: b"chunked",
        },
        HeaderView {
            name: "te",
            value: b"trailers",
        },
        HeaderView {
            name: "connection",
            value: b"x-auth",
        },
        HeaderView {
            name: "upgrade",
            value: b"websocket",
        },
        HeaderView {
            name: "trailer",
            value: b"digest",
        },
        HeaderView {
            name: "x-lsf-principal",
            value: b"admin",
        },
        HeaderView {
            name: "bad name",
            value: b"x",
        },
        HeaderView {
            name: "x-test",
            value: b"ok\r\nadmin: yes",
        },
        HeaderView {
            name: "x-test",
            value: b"\tvalue",
        },
        HeaderView {
            name: "x-test",
            value: &[127],
        },
        HeaderView {
            name: "x-test",
            value: b" trailing ",
        },
    ] {
        assert!(
            pool.begin(head("POST", &[HOST, extra]), deadline())
                .is_err(),
            "{}",
            extra.name
        );
        assert_eq!(pool.snapshot().active_exchanges, 0);
    }
}

#[test]
fn repeated_singletons_and_excess_headers_are_rejected_before_copy() {
    let pool = pool();
    for name in ["content-length", "authorization", "content-type"] {
        let value: &[u8] = match name {
            "content-length" => b"0",
            "content-type" => b"text/plain",
            _ => b"Bearer token",
        };
        let repeated = HeaderView { name, value };
        assert!(pool
            .begin(head("POST", &[HOST, repeated, repeated]), deadline())
            .is_err());
    }
    assert!(pool.begin(head("GET", &[]), deadline()).is_err());
    let mut h2 = head("GET", &[]);
    h2.version = HttpVersion::Http2;
    drop(pool.begin(h2, deadline()).unwrap());
    let fields = vec![
        HeaderView {
            name: "cookie",
            value: b"x=1"
        };
        MAX_HEADERS + 1
    ];
    assert_eq!(
        pool.begin(head("GET", &fields), deadline()).err(),
        Some(HttpError::HeadersTooLarge)
    );
    let large = vec![b'a'; 4096];
    let fields = vec![
        HeaderView {
            name: "x-head",
            value: &large
        };
        5
    ];
    assert_eq!(
        pool.begin(head("GET", &fields), deadline()).err(),
        Some(HttpError::HeadersTooLarge)
    );
    for method in ["get", "TRACE", "CONNECT", "GET\r\n"] {
        assert_eq!(
            pool.begin(head(method, &[HOST]), deadline()).err(),
            Some(HttpError::UnsupportedMethod)
        );
    }
}

#[test]
fn incomplete_excess_and_failed_body_collection_cannot_be_reinterpreted_as_a_request() {
    let pool = pool();
    let headers = [
        HOST,
        HeaderView {
            name: "content-length",
            value: b"3",
        },
    ];
    let mut collector = pool.begin(head("POST", &headers), deadline()).unwrap();
    collector.append(b"ab").unwrap();
    assert_eq!(
        collector.finish(context()).err(),
        Some(HttpError::InvalidFraming)
    );
    let mut collector = pool.begin(head("POST", &headers), deadline()).unwrap();
    assert_eq!(collector.append(b"abcd"), Err(HttpError::InvalidFraming));
    assert_eq!(collector.append(b"abc"), Err(HttpError::InvalidFraming));
    assert!(collector.finish(context()).is_err());
    let mut raw = head("POST", &[HOST]);
    raw.version = HttpVersion::Http2;
    let mut collector = pool.begin(raw, deadline()).unwrap();
    collector.append(&vec![0; MAX_REQUEST_BODY]).unwrap();
    assert_eq!(collector.append(&[1]), Err(HttpError::BodyTooLarge));
    assert!(collector.finish(context()).is_err());
    assert_eq!(pool.snapshot().reserved_bytes, 0);
    assert!(pool.begin(head("GET", &headers), deadline()).is_err());
}

#[test]
fn closed_response_codec_rejects_unknowns_duplicates_shape_versions_and_numeric_coercion() {
    let pool = pool();
    let base = RESPONSE.trim();
    for encoded in ["QQD", "QQD_", "AB==", "AA=", "A===", "AA==\n", "AA== "] {
        let mut value = response();
        value[0]["body-base64"] = json!(encoded);
        assert_eq!(
            deliver(&pool, "POST", &serde_json::to_vec(&value).unwrap()).cause(),
            DeliveryCause::InvalidGuestResponse
        );
    }
    for value in [
        base.replace("buffered-v1", "buffered-v2"),
        base.replace("\"status\":201", "\"status\":99"),
        base.replace("\"status\":201", "\"status\":600"),
        base.replace("\"status\":201", "\"status\":201.0"),
        base.replace("\"status\":201", "\"status\":\"201\""),
        base.replace("\"status\":201", "\"status\":201,\"sta\\u0074us\":200"),
        base.replace("\"profile\":", "\"principal\":\"admin\",\"profile\":"),
        base.replace("\"body-base64\":\"QQD/\"", "\"body-base64\":[65,0,255]"),
        base.replace("\"body-base64\":\"QQD/\"", "\"body-base64\":[256]"),
        base.replace("\"body-base64\":\"QQD/\"", "\"body-base64\":[1e0]"),
        base.replace("\"body-base64\":\"QQD/\"", "\"body-base64\":[-1]"),
        base.replace("{\"none\":null}", "{\"none\":false}"),
        base.replace("{\"none\":null}", "{\"some\":\"01\"}"),
        format!("[{base}]"),
        format!("{base}[]"),
        "[]".into(),
    ] {
        let result = deliver(&pool, "POST", value.as_bytes());
        assert_eq!(
            result.cause(),
            DeliveryCause::InvalidGuestResponse,
            "{value}"
        );
        assert_eq!(result.status(), 502);
        assert_eq!(result.remaining_body().unwrap(), b"Bad gateway\n");
    }
    let value = vec![b' '; MAX_WIRE_BYTES + 1];
    assert_eq!(deliver(&pool, "POST", &value).status(), 502);
    assert_eq!(deliver(&pool, "POST", &[255]).status(), 502);
    let nested = format!("{}0{}", "[".repeat(64), "]".repeat(64));
    assert_eq!(deliver(&pool, "POST", nested.as_bytes()).status(), 502);
}

#[test]
fn response_semantics_reject_framing_injection_excess_bytes_and_invalid_body_statuses() {
    let pool = pool();
    for name in [
        "content-length",
        "content-type",
        "host",
        "connection",
        "transfer-encoding",
        "x-lsf-tenant",
        "server",
        "date",
        "authorization",
        "x-forwarded-host",
        "Cookie",
    ] {
        let mut value = response();
        value[0]["headers"] = json!([{"name":name,"value":[49]}]);
        assert_eq!(
            deliver(&pool, "POST", &serde_json::to_vec(&value).unwrap()).status(),
            502
        );
    }
    for media in [
        "text/plain\r\nX: a",
        "text/plain; charset=a; CHARSET=b",
        "text/plain, application/json",
        "text/plain; charset=\"x\\y\"",
    ] {
        let mut value = response();
        value[0]["media-type"] = json!({"some":media});
        assert_eq!(
            deliver(&pool, "POST", &serde_json::to_vec(&value).unwrap()).status(),
            502
        );
    }
    for status in [204, 205, 304] {
        let mut value = response();
        value[0]["status"] = json!(status);
        assert_eq!(
            deliver(&pool, "POST", &serde_json::to_vec(&value).unwrap()).status(),
            502
        );
    }
    assert_eq!(deliver(&pool, "HEAD", RESPONSE.as_bytes()).status(), 502);
    let mut value = response();
    value[0]["body-base64"] = json!(STANDARD.encode(vec![255u8; MAX_RESPONSE_BODY]));
    let bytes = serde_json::to_vec(&value).unwrap();
    assert_eq!(
        deliver(&pool, "POST", &bytes).content_length(),
        Some(MAX_RESPONSE_BODY as u64)
    );
    value[0]["body-base64"] = json!(STANDARD.encode(vec![255u8; MAX_RESPONSE_BODY + 1]));
    assert_eq!(
        deliver(&pool, "POST", &serde_json::to_vec(&value).unwrap()).status(),
        502
    );
    value = response();
    value[0]["headers"][0]["value"] = json!([13, 10]);
    assert_eq!(
        deliver(&pool, "POST", &serde_json::to_vec(&value).unwrap()).status(),
        502
    );
}

#[test]
fn trusted_context_rejects_retained_capacity_controls_and_excess_claims() {
    let valid = context();
    let original = valid.principal();
    let trace = valid.trace();
    let mut oversized = original.clone();
    oversized.subject = String::with_capacity(MAX_CONTEXT_BYTES + 1);
    oversized.subject.push_str("user");
    assert!(matches!(
        TrustedContext::new(oversized, trace.clone()),
        Err(HttpError::InvalidContext)
    ));
    let mut controlled = original.clone();
    controlled.subject.push('\n');
    assert!(matches!(
        TrustedContext::new(controlled, trace.clone()),
        Err(HttpError::InvalidContext)
    ));
    let mut crowded = original.clone();
    crowded.claims = (0..33)
        .map(|i| (format!("claim{i}"), "value".into()))
        .collect();
    assert!(matches!(
        TrustedContext::new(crowded, trace.clone()),
        Err(HttpError::InvalidContext)
    ));
    let mut empty = original.clone();
    empty.subject.clear();
    assert!(matches!(
        TrustedContext::new(empty, trace.clone()),
        Err(HttpError::InvalidContext)
    ));
    let mut large_trace = trace.clone();
    large_trace.baggage.insert("item".into(), "x".repeat(513));
    assert!(matches!(
        TrustedContext::new(original.clone(), large_trace),
        Err(HttpError::InvalidContext)
    ));
}
