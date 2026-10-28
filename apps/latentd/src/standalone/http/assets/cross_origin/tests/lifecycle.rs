use super::support::*;
use crate::standalone::http::{assets::{fixture, Request}, tests::fixture as node};
use latent_artifacts::{ReleaseLifecycleAction, ReleaseLifecycleReason};
use latent_core::TenantId;
use latent_ingress::http::Scheme;
use serde_json::json;
use std::time::Duration;
use tokio::{io::{AsyncReadExt, AsyncWriteExt}, net::TcpStream};

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cross_origin_native_grant_removal_restart_and_new_publication_never_inherit_permission() {
    let mut h = start().await;
    let first = publish(&h, "cross-first", b"same bytes");
    let second = publish(&h, "cross-second", b"same bytes");
    assert_ne!(first, second, "a new publication needs a distinct explicit grant");
    let get = apply(&h, &first, "GET", 0);
    let head = apply(&h, &first, "HEAD", 0);
    restart(&mut h, json!([grant(&first, "omit")])).await;
    let metadata = metadata(ORIGIN);
    let (_, headers, _) = call(&h, "GET", "/app.js", &metadata).await;
    let conditional = format!("{metadata}If-None-Match: {}\r\n", field(&headers, "etag").unwrap());
    let preflight = format!("{metadata}Access-Control-Request-Method: GET\r\nAccess-Control-Request-Headers: if-none-match\r\n");
    assert_eq!(call(&h, "OPTIONS", "/app.js", &preflight).await.0, 204);
    assert_eq!(call(&h, "GET", "/app.js", &conditional).await.0, 304);
    let (status, headers, _) = call(&h, "GET", &immutable(&second, "/app.js"), &metadata).await;
    assert_eq!(status, 403);
    denied(&headers);
    apply(&h, &second, "GET", get);
    // A successful old preflight and identical bytes/ETag grant no new authority.
    for (method, fields) in [("GET", &conditional), ("OPTIONS", &preflight)] {
        let (status, headers, body) = call(&h, method, "/app.js", fields).await;
        assert_eq!(status, 403);
        assert!(body.is_empty());
        denied(&headers);
    }
    assert_eq!(call(&h, "HEAD", "/app.js", &metadata).await.0, 200);
    restart(&mut h, json!([grant(&second, "omit")])).await;
    assert_eq!(call(&h, "GET", "/app.js", &metadata).await.0, 200);
    assert_eq!(call(&h, "HEAD", "/app.js", &metadata).await.0, 403);
    apply(&h, &second, "HEAD", head);
    assert_eq!(call(&h, "HEAD", "/app.js", &metadata).await.0, 200);
    restart(&mut h, json!([])).await;
    for (method, fields) in [("GET", &conditional), ("HEAD", &conditional), ("OPTIONS", &preflight)] {
        let (status, headers, body) = call(&h, method, "/app.js", fields).await;
        assert_eq!(status, 403);
        assert!(body.is_empty());
        denied(&headers);
    }
    assert_eq!(call(&h, "GET", "/app.js", "").await.0, 200);
    no_execution(&h);
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cross_origin_native_revocation_denies_cached_bodies_conditionals_and_preflights() {
    let mut h = start().await;
    let reference = publish(&h, "cross-revocation", b"cache is not authority");
    for method in ["GET", "HEAD"] { apply(&h, &reference, method, 0); }
    restart(&mut h, json!([grant(&reference, "include")])).await;
    let metadata = metadata(ORIGIN);
    let (_, headers, _) = call(&h, "GET", "/app.js", &metadata).await;
    let conditional = format!("{metadata}If-None-Match: {}\r\n", field(&headers, "etag").unwrap());
    h.repository.transition_web_publication(
        fixture::context("cross-revoke", 1), &reference,
        ReleaseLifecycleAction::Revoke, ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    ).unwrap();
    let preflight = format!("{metadata}Access-Control-Request-Method: GET\r\n");
    for path in ["/app.js".to_owned(), immutable(&reference, "/app.js")] {
        for (method, fields) in [("GET", &conditional), ("HEAD", &conditional), ("OPTIONS", &preflight)] {
            let (status, headers, body) = call(&h, method, &path, fields).await;
            assert_eq!(status, 403);
            assert!(body.is_empty());
            denied(&headers);
        }
    }
    assert!(h.store().snapshot().retained_buffer_bytes > 0);
    no_execution(&h);
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cross_origin_native_read_capacity_has_no_queue_or_activation_fallback() {
    let mut h = start().await;
    let reference = publish(&h, "cross-capacity", b"bounded");
    restart(&mut h, json!([grant(&reference, "omit")])).await;
    let path = immutable(&reference, "/app.js");
    let store = h.store();
    let raw = node::request("GET", &path, "", 0, true);
    let mut held = Vec::new();
    for _ in 0..8 {
        let request = Request::parse(raw.as_bytes(), &TenantId("tests".into())).unwrap();
        held.push(store.begin(request).unwrap().await.unwrap().unwrap());
    }
    let before = store.snapshot();
    assert_eq!(before.active_reads, 8);
    let (status, headers, body) = call(&h, "GET", &path, &metadata(ORIGIN)).await;
    assert_eq!(status, 503);
    assert!(body.is_empty());
    authorized(&headers, false, true);
    assert_eq!(store.snapshot().cache_misses, before.cache_misses);
    assert_eq!(store.snapshot().capacity_rejections, before.capacity_rejections + 1);
    no_execution(&h);
    drop(held);
    assert_eq!(call(&h, "GET", &path, &metadata(ORIGIN)).await.0, 200);
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cross_origin_native_disconnect_retains_the_actual_blocking_read_owner_until_completion() {
    let mut h = start().await;
    let reference = publish(&h, "cross-disconnect", b"bounded");
    apply(&h, &reference, "GET", 0);
    restart(&mut h, json!([grant(&reference, "omit")])).await;
    let store = h.store();
    let (entered, started) = std::sync::mpsc::channel();
    let (resume, blocked) = std::sync::mpsc::channel();
    *store.pause.lock().unwrap() = Some((entered, blocked));
    let mut socket = TcpStream::connect(h.owner.local_addr()).await.unwrap();
    socket.write_all(format!(
        "GET /app.js HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n{}\r\n",
        node::AUTHORITY, metadata(ORIGIN),
    ).as_bytes()).await.unwrap();
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    assert_eq!(store.snapshot().active_reads, 1);
    drop(socket);
    node::wait(|| h.owner.handle().snapshot().connections == 0).await;
    assert_eq!(store.snapshot().active_reads, 1);
    assert!(h.repository.web_read_snapshot().unwrap().active_reads > 0);
    resume.send(()).unwrap();
    node::wait(|| store.snapshot().active_reads == 0).await;
    no_execution(&h);
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cross_origin_preflight_output_rechecks_revocation_on_every_write_poll() {
    let h = start().await;
    let reference = publish(&h, "cross-preflight-write", b"bounded");
    let selection = h.repository.select_web_publication(&reference).unwrap();
    let (mut writer, mut reader) = tokio::io::duplex(16);
    let task = tokio::spawn(async move {
        let policy = super::super::response::Policy {
            origin: ORIGIN.into(), credentials: false, preflight: Some("if-none-match".into()),
        };
        super::super::response::empty(
            &mut writer, 204, Scheme::Https, true, Some(&policy), Some(&selection),
        ).await
    });
    let mut first = [0; 16];
    tokio::time::timeout(Duration::from_secs(5), reader.read_exact(&mut first)).await.unwrap().unwrap();
    h.repository.transition_web_publication(
        fixture::context("cross-preflight-revoke", 1), &reference,
        ReleaseLifecycleAction::Revoke, ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    ).unwrap();
    let mut remaining = Vec::new();
    tokio::time::timeout(Duration::from_secs(5), reader.read_to_end(&mut remaining)).await.unwrap().unwrap();
    let error = task.await.unwrap().unwrap_err();
    assert_eq!(error.kind(), std::io::ErrorKind::PermissionDenied);
    assert!(remaining.len() <= 16, "no write can resume after authority is revoked");
    assert!(!String::from_utf8_lossy(&remaining).contains("Access-Control-Allow-Origin"));
    no_execution(&h);
    h.finish().await;
}
