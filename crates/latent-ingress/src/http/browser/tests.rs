use super::*;
use crate::http::{headers, model::ResponseData};
use serde_json::json;

fn target() -> CanonicalTarget {
    CanonicalTarget::parse(Scheme::Https, "web.example.test", "/").unwrap()
}
fn fields<'value>(pairs: &'value [(&'value str, &'value str)]) -> Vec<HeaderView<'value>> {
    pairs
        .iter()
        .map(|(name, value)| HeaderView {
            name,
            value: value.as_bytes(),
        })
        .collect()
}
fn response(status: u16, fields: &[(&str, &str)]) -> ResponseData {
    serde_json::from_value(json!({"profile":"buffered-v1", "status":status,
        "headers":fields.iter().map(|(name, value)| json!({"name":name,"value":value.as_bytes()})).collect::<Vec<_>>(),
        "media-type":{"some":"text/html; charset=utf-8"},
        "representation-length":{"none":null},"body-base64":""})).unwrap()
}

#[test]
fn browser_origin_is_exact_and_never_accepts_null_lists_siblings_or_forwarding() {
    for origin in [
        "null",
        "*",
        "https://other.example.test",
        "http://web.example.test",
        "https://web.example.test:443",
        "https://web.example.test/",
        "https://web.example.test.evil.test",
        "https://web.example.test https://other.example.test",
    ] {
        assert_eq!(
            admit(
                &target(),
                Method::Get,
                &fields(&[("origin", origin)]),
                true,
                false
            ),
            Err(403)
        );
    }
    assert_eq!(
        admit(
            &target(),
            Method::Post,
            &fields(&[("origin", "https://web.example.test")]),
            true,
            false
        ),
        Ok(())
    );
    assert_eq!(
        admit(
            &target(),
            Method::Post,
            &fields(&[("forwarded", "proto=https;host=web.example.test")]),
            true,
            false
        ),
        Err(403)
    );
    assert_eq!(
        admit(
            &target(),
            Method::Get,
            &fields(&[
                ("origin", "https://web.example.test"),
                ("Origin", "https://web.example.test")
            ]),
            true,
            false
        ),
        Err(400)
    );
}

#[test]
fn fetch_metadata_and_mutation_rules_fail_closed_without_cors_or_cookie_authentication() {
    for site in ["cross-site", "same-site", "bogus", ""] {
        assert_eq!(
            admit(
                &target(),
                Method::Get,
                &fields(&[("sec-fetch-site", site)]),
                true,
                false
            ),
            Err(403)
        );
    }
    assert_eq!(
        admit(
            &target(),
            Method::Get,
            &fields(&[("sec-fetch-site", "none"), ("sec-fetch-mode", "navigate")]),
            true,
            false
        ),
        Ok(())
    );
    assert_eq!(
        admit(
            &target(),
            Method::Get,
            &fields(&[("sec-fetch-site", "same-origin")]),
            false,
            true
        ),
        Err(403)
    );
    for method in [Method::Post, Method::Put, Method::Patch, Method::Delete] {
        assert_eq!(admit(&target(), method, &[], true, false), Err(403));
        assert_eq!(
            admit(
                &target(),
                method,
                &fields(&[("cookie", "session=untrusted")]),
                true,
                false
            ),
            Err(403)
        );
        assert_eq!(admit(&target(), method, &[], false, true), Ok(()));
        assert_eq!(
            admit(
                &target(),
                method,
                &fields(&[("sec-fetch-site", "same-origin")]),
                true,
                true
            ),
            Err(403)
        );
    }
    for pair in [
        ("sec-fetch-mode", "websocket"),
        ("sec-fetch-dest", "iframe"),
        ("sec-fetch-user", "?0"),
        ("access-control-request-method", "POST"),
    ] {
        assert_eq!(
            admit(&target(), Method::Options, &fields(&[pair]), true, false),
            Err(403)
        );
    }
}

#[test]
fn cookie_count_bytes_duplicates_and_identity_encoding_are_bounded() {
    assert_eq!(
        validate_input(&fields(&[("cookie", "a=1; b=2"), ("Cookie", "c=3")])),
        Ok(())
    );
    for cookie in [
        "session=one; session=two",
        "a",
        "a=quoted\"",
        "a=comma,",
        "a=back\\slash",
        "a=space here",
    ] {
        assert_eq!(validate_input(&fields(&[("cookie", cookie)])), Err(400));
    }
    assert_eq!(
        validate_input(&fields(&[("cookie", "a=1"), ("cookie", "a=2")])),
        Err(400)
    );
    let cookies = (0..17)
        .map(|index| format!("name{index}=x"))
        .collect::<Vec<_>>()
        .join("; ");
    assert_eq!(validate_input(&fields(&[("cookie", &cookies)])), Err(431));
    let values = [
        format!("a={}", "x".repeat(1024)),
        format!("b={}", "x".repeat(1024)),
        format!("c={}", "x".repeat(1024)),
        format!("d={}", "x".repeat(1024)),
    ];
    let headers = values
        .iter()
        .map(|value| HeaderView {
            name: "cookie",
            value: value.as_bytes(),
        })
        .collect::<Vec<_>>();
    assert_eq!(validate_input(&headers), Err(431));
    for coding in ["gzip", "br", "deflate", "identity, gzip", ""] {
        assert_eq!(
            validate_input(&fields(&[("content-encoding", coding)])),
            Err(415)
        );
    }
    assert_eq!(
        validate_input(&fields(&[("content-encoding", "identity")])),
        Ok(())
    );
    assert_eq!(
        validate_input(&fields(&[
            ("content-encoding", "identity"),
            ("content-encoding", "identity")
        ])),
        Err(400)
    );
}

#[test]
fn guest_cannot_override_security_headers_enable_cors_or_supply_encoded_bodies() {
    for field in security_headers(Scheme::Https) {
        assert!(!validate_response(
            &response(200, &[(field.name, "unsafe")]),
            Scheme::Https
        ));
    }
    for field in [
        "access-control-allow-origin",
        "refresh",
        "link",
        "content-location",
        "clear-site-data",
        "report-to",
        "nel",
        "content-security-policy-report-only",
        "cross-origin-embedder-policy",
    ] {
        assert!(!validate_response(
            &response(200, &[(field, "unsafe")]),
            Scheme::Https
        ));
    }
    assert!(!validate_response(
        &response(200, &[("content-encoding", "gzip")]),
        Scheme::Https
    ));
    assert!(validate_response(
        &response(200, &[("content-encoding", "identity")]),
        Scheme::Https
    ));
    assert!(!validate_response(
        &response(
            200,
            &[
                ("content-encoding", "identity"),
                ("content-encoding", "identity")
            ]
        ),
        Scheme::Https
    ));
    assert!(validate_response(&response(200, &[]), Scheme::Https));
    assert!(security_headers(Scheme::Http).all(|field| field.name != "strict-transport-security"));
    assert!(!CSP.contains("unsafe-inline"));
    assert!(!CSP.contains("unsafe-eval"));
}

#[test]
fn only_canonical_origin_relative_redirects_survive_and_never_split_headers() {
    for location in [
        "https://web.example.test/",
        "https://evil.test/",
        "//evil.test/",
        "javascript:alert(1)",
        "/\\evil.test",
        "/%2f%2fevil.test",
        "/../next",
        "/%2e%2e/next",
        "/%252fnext",
        "/next#fragment",
        "/next\r\nX-Leak: token",
    ] {
        assert!(
            !validate_response(&response(302, &[("location", location)]), Scheme::Https),
            "{location}"
        );
    }
    for status in [201, 301, 302, 303, 307, 308] {
        assert!(validate_response(
            &response(status, &[("location", "/next?view=public")]),
            Scheme::Https
        ));
    }
    assert!(!validate_response(
        &response(200, &[("location", "/next")]),
        Scheme::Https
    ));
    assert!(!validate_response(&response(302, &[]), Scheme::Https));
    assert!(!validate_response(
        &response(302, &[("location", "/next"), ("location", "/other")]),
        Scheme::Https
    ));
    assert!(headers::response(
        &response(200, &[("x-output", "text\r\nSet-Cookie: leaked")]),
        Method::Get
    )
    .is_err());
}

#[test]
fn browser_cookies_are_host_only_secure_http_only_strict_and_never_cleartext() {
    let cookie = "__Host-view=one; Secure; HttpOnly; SameSite=Strict; Path=/";
    assert!(validate_response(
        &response(200, &[("set-cookie", cookie)]),
        Scheme::Https
    ));
    assert!(!validate_response(
        &response(200, &[("set-cookie", cookie)]),
        Scheme::Http
    ));
    assert!(validate_response(
        &response(200, &[("set-cookie", &format!("{cookie}; Max-Age=0"))]),
        Scheme::Https
    ));
    for cookie in [
        "session=token",
        "__Host-view=one; Secure; SameSite=Strict; Path=/",
        "__Host-view=one; Secure; HttpOnly; SameSite=None; Path=/",
        "__Host-view=one; Secure; HttpOnly; SameSite=Strict; Path=/; Domain=example.test",
        "__Host-view=one; Secure; Secure; HttpOnly; SameSite=Strict; Path=/",
    ] {
        assert!(!validate_response(
            &response(200, &[("set-cookie", cookie)]),
            Scheme::Https
        ));
    }
    assert!(!validate_response(
        &response(200, &[("set-cookie", cookie), ("set-cookie", cookie)]),
        Scheme::Https
    ));
}

#[test]
fn html_requires_explicit_utf8_and_does_not_claim_to_sanitize_application_html() {
    let mut value = response(200, &[]);
    value.body.0 = b"<script src='/malicious-but-same-origin.js'></script>".to_vec();
    assert!(validate_response(&value, Scheme::Https));
    value.body.0 = vec![255];
    assert!(!validate_response(&value, Scheme::Https));
    value.body.0.clear();
    value.media_type = crate::http::bounded::Optional::from_option(Some(
        crate::http::bounded::BoundedText("text/html".into()),
    ));
    assert!(!validate_response(&value, Scheme::Https));
}
