mod lifecycle;
mod support;

use support::*;
use serde_json::json;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cross_origin_native_static_get_head_304_and_errors_share_exact_current_authority() {
    let mut h = start().await;
    let reference = publish(&h, "native-cors", b"globalThis.nativeCors = true;\n");
    for method in ["GET", "HEAD"] {
        apply(&h, &reference, method, 0);
    }
    restart(&mut h, json!([grant(&reference, "omit")])).await;
    let metadata = metadata(ORIGIN);
    for path in ["/app.js".to_owned(), immutable(&reference, "/app.js")] {
        let (status, headers, body) = call(&h, "GET", &path, &metadata).await;
        assert_eq!(status, 200);
        assert_eq!(body, b"globalThis.nativeCors = true;\n");
        authorized(&headers, false, false);
        let tag = field(&headers, "etag").unwrap();
        let (status, head, body) = call(&h, "HEAD", &path, &metadata).await;
        assert_eq!(status, 200);
        assert!(body.is_empty());
        assert_eq!(field(&head, "etag"), Some(tag));
        assert_eq!(field(&head, "content-length"), field(&headers, "content-length"));
        authorized(&head, false, false);
        for method in ["GET", "HEAD"] {
            let (status, headers, body) = call(
                &h, method, &path, &format!("{metadata}If-None-Match: {tag}\r\n"),
            ).await;
            assert_eq!(status, 304);
            assert!(body.is_empty());
            assert!(field(&headers, "content-length").is_none());
            authorized(&headers, false, false);
        }
        for condition in ["If-None-Match: invalid\r\n", "Accept-Encoding: identity;q=0\r\n"] {
            let (status, headers, body) = call(&h, "GET", &path, &format!("{metadata}{condition}")).await;
            assert!(matches!(status, 400 | 406));
            assert!(body.is_empty());
            authorized(&headers, false, true);
        }
    }
    for path in ["/missing.js".to_owned(), immutable(&reference, "/missing.js")] {
        for method in ["GET", "HEAD"] {
            let (status, headers, body) = call(&h, method, &path, &metadata).await;
            assert_eq!(status, 404);
            assert!(body.is_empty());
            authorized(&headers, false, true);
        }
    }
    assert!(h.store().snapshot().cache_hits > 0);
    no_execution(&h);
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cross_origin_native_preflight_selects_exact_method_and_never_html_or_fallback() {
    let mut h = start().await;
    let reference = publish(&h, "native-preflight", b"script");
    apply(&h, &reference, "GET", 0);
    restart(&mut h, json!([grant(&reference, "omit")])).await;
    let metadata = metadata(ORIGIN);
    let requested = format!("{metadata}Access-Control-Request-Method: GET\r\nAccess-Control-Request-Headers: if-modified-since, if-none-match\r\n");
    let (status, headers, body) = call(&h, "OPTIONS", "/app.js", &requested).await;
    assert_eq!(status, 204);
    assert!(body.is_empty());
    authorized(&headers, false, false);
    assert_eq!(field(&headers, "access-control-max-age"), Some("0"));
    assert_eq!(field(&headers, "access-control-allow-methods"), Some("GET, HEAD"));
    assert_eq!(field(&headers, "access-control-allow-headers"), Some("if-none-match, if-modified-since"));
    assert!(field(&headers, "content-length").is_none());
    // A missing HEAD route is not silently routed through GET.
    let (status, headers, _) = call(&h, "OPTIONS", "/app.js", &requested.replace(": GET\r\n", ": HEAD\r\n")).await;
    assert_eq!(status, 403);
    denied(&headers);
    apply(&h, &reference, "HEAD", 0);
    assert_eq!(call(&h, "OPTIONS", "/app.js", &requested.replace(": GET\r\n", ": HEAD\r\n")).await.0, 204);
    for path in ["/", "/index.html", "/exact.html", "/guide", "/guide/", "/orders/42"] {
        for method in ["GET", "HEAD", "OPTIONS"] {
            let fields = if method == "OPTIONS" { &requested } else { &metadata };
            let (status, headers, body) = call(&h, method, path, fields).await;
            assert!(matches!(status, 403 | 404), "{method} {path}: {status}");
            assert!(body.is_empty());
            if status == 403 { denied(&headers); }
        }
    }
    for extra in [
        "Access-Control-Request-Method: PUT\r\n",
        "Access-Control-Request-Method: GET\r\nAccess-Control-Request-Headers: authorization\r\n",
        "Access-Control-Request-Method: GET\r\nAccess-Control-Request-Headers: x-tenant\r\n",
        "Access-Control-Request-Method: GET\r\nCookie: __Host-lsf_demo=test-only\r\n",
    ] {
        let (status, headers, _) = call(&h, "OPTIONS", "/app.js", &format!("{metadata}{extra}")).await;
        assert_eq!(status, 403);
        denied(&headers);
    }
    no_execution(&h);
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cross_origin_native_credentials_origin_variants_and_strict_defaults_do_not_mix() {
    let mut h = start().await;
    let reference = publish(&h, "native-credentials", b"script");
    let path = immutable(&reference, "/app.js");
    let metadata = metadata(ORIGIN);
    // Default-empty config remains strict even though the static publication exists.
    assert_eq!(call(&h, "GET", &path, &metadata).await.0, 403);
    for mode in ["omit", "include"] {
        restart(&mut h, json!([grant(&reference, mode)])).await;
        let (status, headers, _) = call(&h, "GET", &path, &metadata).await;
        assert_eq!(status, 200);
        authorized(&headers, mode == "include", false);
        let (status, headers, _) = call(&h, "GET", &path, &format!("{metadata}{COOKIE}")).await;
        assert_eq!(status, if mode == "include" { 200 } else { 403 });
        if mode == "include" { authorized(&headers, true, false); } else { denied(&headers); }
        for fields in [
            metadata.replace(ORIGIN, "null"),
            metadata.replace(ORIGIN, "https://unrelated.example.test"),
            metadata.replace(ORIGIN, "https://portal.example.test, https://other.test"),
            metadata.replace("Mode: cors", "Mode: no-cors"),
            metadata.replace("Dest: empty", "Dest: document"),
            format!("{metadata}Origin: {ORIGIN}\r\n"),
            format!("{metadata}Authorization: Bearer forbidden\r\n"),
            format!("{metadata}X-Tenant: foreign\r\n"),
        ] {
            let (status, headers, body) = call(&h, "GET", &path, &fields).await;
            assert!(matches!(status, 400 | 401 | 403));
            assert!(body.is_empty());
            denied(&headers);
        }
        let same = "Origin: https://web.example.test\r\nSec-Fetch-Site: same-origin\r\nSec-Fetch-Mode: cors\r\nSec-Fetch-Dest: empty\r\n";
        let (status, headers, _) = call(&h, "GET", &path, same).await;
        assert_eq!(status, 200);
        assert!(field(&headers, "access-control-allow-origin").is_none());
        assert_eq!(field(&headers, "cross-origin-resource-policy"), Some("same-origin"));
    }
    no_execution(&h);
    h.finish().await;
}
