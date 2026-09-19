use super::{fixture, Request, Store};
use crate::{
    config::NodeConfig,
    standalone::http::{tests::fixture as node_fixture, HttpOwner, HttpServices},
};
use latent_artifacts::{
    AdmissionStorageLimits, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
    ReleaseLifecycleAction, ReleaseLifecycleReason,
};
use latent_core::TenantId;
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};
use tempfile::TempDir;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpStream,
    time::Instant,
};

pub(super) struct Harness {
    pub(super) owner: HttpOwner,
    pub(super) node: node_fixture::Fixture,
    pub(super) repository: Arc<DirectoryArtifactRepository>,
    current: Arc<AtomicBool>,
    storage: TempDir,
}
impl Harness {
    async fn new() -> Self {
        Self::configured(|_| {}).await
    }
    pub(super) async fn configured(configure: impl FnOnce(&mut serde_json::Value)) -> Self {
        let root = TempDir::new().unwrap();
        let mut value = node_fixture::config(&root);
        configure(&mut value);
        let settings = serde_json::from_value::<NodeConfig>(value.clone())
            .unwrap()
            .derive()
            .unwrap();
        // No capsule, renderer, deployment or HTTP trigger exists in this node.
        value["httpIngress"]["bind"] = serde_json::json!("127.0.0.1:0");
        let node = node_fixture::Fixture::start(root, value, None).await;
        assert!(
            node.node.http_snapshot().unwrap().assets.is_some(),
            "production startup installs one shared asset owner"
        );
        let storage = TempDir::new().unwrap();
        let current = Arc::new(AtomicBool::new(true));
        let repository = Arc::new(
            DirectoryArtifactRepository::open_enforced(
                storage.path().join("catalog"),
                DirectoryArtifactRepositoryConfig::default(),
                AdmissionStorageLimits::default(),
                Arc::new(fixture::Authority(Arc::clone(&current))),
            )
            .unwrap(),
        );
        let owner = HttpOwner::start(
            settings.http.unwrap(),
            HttpServices {
                manager: node.node.manager.clone(),
                deployments: node.deployments.clone(),
                cleanup: node.node.cleanup.as_ref().unwrap().handle(),
                clock: node.node.clock.clone(),
                budget: settings.admission.budget_ceiling.clone(),
            },
        )
        .unwrap();
        owner.install_assets(Arc::clone(&repository)).unwrap();
        owner.handle().start_accepting().unwrap();
        Self {
            owner,
            node,
            repository,
            current,
            storage,
        }
    }
    fn store(&self) -> Arc<Store> {
        Arc::clone(self.owner.handle().0.assets.get().unwrap())
    }
    pub(super) fn publish(&self, operation: &str, bytes: &[u8]) -> String {
        let reference = fixture::publish(&self.repository, operation, bytes);
        self.repository
            .select_web_publication(&reference)
            .unwrap()
            .asset_url("/index.html")
            .unwrap()
    }
    async fn call(
        &self,
        method: &str,
        path: &str,
        extra: &str,
        token: &str,
    ) -> (u16, String, Vec<u8>) {
        let mut socket = TcpStream::connect(self.owner.local_addr()).await.unwrap();
        let request = node_fixture::request(method, path, token, 0, true)
            .replace("\r\n\r\n", &format!("\r\n{extra}\r\n"));
        socket.write_all(request.as_bytes()).await.unwrap();
        let mut bytes = Vec::new();
        tokio::time::timeout(
            Duration::from_secs(8),
            socket.take(9 * 1024 * 1024).read_to_end(&mut bytes),
        )
        .await
        .unwrap()
        .unwrap();
        let end = bytes
            .windows(4)
            .position(|window| window == b"\r\n\r\n")
            .expect("response headers")
            + 4;
        let headers = String::from_utf8(bytes[..end].to_vec()).unwrap();
        let status = headers.split_whitespace().nth(1).unwrap().parse().unwrap();
        (status, headers, bytes[end..].to_vec())
    }
    pub(super) async fn finish(self) {
        node_fixture::wait(|| {
            let snapshot = self.owner.handle().snapshot();
            snapshot.connections == 0
                && snapshot.exchanges == 0
                && self.store().snapshot().active_reads == 0
        })
        .await;
        assert_eq!(self.node.node.manager.journal().snapshot().active, 0);
        assert_eq!(self.node.node.quotas.usage().unwrap().active_activations, 0);
        assert_eq!(self.node.node.backend.resource_snapshot().live_stores, 0);
        assert_eq!(self.repository.web_read_snapshot().unwrap().active_reads, 0);
        let handle = self.owner.handle();
        self.owner
            .shutdown(Instant::now() + Duration::from_secs(5))
            .await
            .unwrap();
        assert!(handle.snapshot().clean());
        self.node.shutdown().await;
    }
}
fn etag(headers: &str) -> &str {
    headers
        .lines()
        .find_map(|line| line.strip_prefix("ETag: "))
        .unwrap()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn real_get_head_conditionals_and_atomic_release_replacement_never_need_a_renderer() {
    let h = Harness::new().await;
    let first = h.publish("first", b"<h1>one</h1>");
    let (code, headers, bytes) = h.call("GET", &first, "", node_fixture::TOKEN).await;
    assert_eq!(code, 200);
    assert_eq!(bytes, b"<h1>one</h1>");
    assert!(headers.contains("Content-Type: text/html\r\n"));
    assert!(headers.contains("Cache-Control: private, max-age=31536000, immutable"));
    assert!(headers
        .to_ascii_lowercase()
        .contains("x-content-type-options: nosniff"));
    let first_tag = etag(&headers).to_owned();
    let (_, head, body) = h.call("HEAD", &first, "", node_fixture::TOKEN).await;
    assert!(head.contains("Content-Length: 12\r\n"));
    assert_eq!(etag(&head), first_tag);
    assert!(body.is_empty());
    let condition = format!("If-None-Match: W/{first_tag}\r\n");
    for method in ["GET", "HEAD"] {
        let (status, header, body) = h
            .call(method, &first, &condition, node_fixture::TOKEN)
            .await;
        assert_eq!(status, 304);
        assert!(!header.contains("Content-Length:"));
        assert!(body.is_empty());
    }
    let second = h.publish("replacement", b"<h1>two</h1>");
    assert_ne!(first, second);
    let (code, header, body) = h
        .call("GET", &second, &condition, node_fixture::TOKEN)
        .await;
    assert_eq!(code, 200);
    assert_ne!(etag(&header), first_tag);
    assert_eq!(body, b"<h1>two</h1>");
    assert_eq!(
        h.call("GET", &first, "", node_fixture::TOKEN).await.2,
        b"<h1>one</h1>"
    );
    let (code, _, body) = h
        .call(
            "GET",
            &second,
            &format!("If-Match: {first_tag}\r\nIf-None-Match: *\r\n"),
            node_fixture::TOKEN,
        )
        .await;
    assert_eq!(code, 412);
    assert!(body.is_empty());
    assert!(h.store().snapshot().cache_hits >= 4);
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn errors_private_layers_methods_ranges_compression_and_tenants_remain_fail_closed() {
    let h = Harness::new().await;
    let path = h.publish("first", b"hello");
    let base = path.strip_suffix("/index.html").unwrap();
    for suffix in [
        "/metadata/private.json",
        "/metadata/web-application.json",
        "/server/renderer.wasm",
        "/public/index.html",
        "/missing.js",
    ] {
        let (code, headers, body) = h
            .call("HEAD", &format!("{base}{suffix}"), "", node_fixture::TOKEN)
            .await;
        assert_eq!(code, 404);
        assert!(headers.contains("Cache-Control: no-store"));
        assert!(body.is_empty());
    }
    let (code, headers, _) = h.call("POST", &path, "", node_fixture::TOKEN).await;
    assert_eq!(code, 405);
    assert!(headers.contains("Allow: GET, HEAD"));
    assert_eq!(
        h.call(
            "GET",
            &path,
            "Accept-Encoding: gzip, identity;q=0\r\n",
            node_fixture::TOKEN
        )
        .await
        .0,
        406
    );
    let (code, headers, body) = h
        .call(
            "GET",
            &path,
            "Range: bytes=0-0,2-3\r\nAccept-Encoding: gzip, br\r\n",
            node_fixture::TOKEN,
        )
        .await;
    assert_eq!(code, 200);
    assert_eq!(body, b"hello");
    assert!(headers.contains("Accept-Ranges: none"));
    assert!(!headers.contains("Content-Encoding:"));
    assert!(matches!(
        h.call("GET", &path, "", node_fixture::OTHER).await.0,
        403 | 404
    ));
    for suffix in [
        "/%2findex.html",
        "/%2e%2e/index.html",
        "/../index.html",
        "/%69ndex.html",
        "/index.html?other=1",
    ] {
        assert_eq!(
            h.call("GET", &format!("{base}{suffix}"), "", node_fixture::TOKEN)
                .await
                .0,
            400
        );
    }
    let (_, script_headers, _) = h
        .call("GET", &format!("{base}/app.js"), "", node_fixture::TOKEN)
        .await;
    assert!(script_headers.contains("Content-Type: text/javascript"));
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cached_bytes_and_prepared_304_are_not_authority_after_policy_change_or_revocation() {
    let h = Harness::new().await;
    let path = h.publish("first", b"hello");
    let (_, headers, _) = h.call("GET", &path, "", node_fixture::TOKEN).await;
    let raw = node_fixture::request("GET", &path, node_fixture::TOKEN, 0, true).replace(
        "\r\n\r\n",
        &format!("\r\nIf-None-Match: {}\r\n\r\n", etag(&headers)),
    );
    let request = Request::parse(raw.as_bytes(), &TenantId("tests".into())).unwrap();
    let store = h.store();
    let reference = request.reference.clone();
    let prepared = store.begin(request).unwrap().await.unwrap().unwrap();
    assert_eq!(prepared.code, 304);
    h.current.store(false, Ordering::Release);
    assert_eq!(prepared.accept(&TenantId("tests".into())), Err(403));
    drop(prepared);
    assert_eq!(
        h.call("HEAD", &path, "If-None-Match: *\r\n", node_fixture::TOKEN)
            .await
            .0,
        403
    );
    h.current.store(true, Ordering::Release);
    h.repository
        .transition_web_publication(
            fixture::context("revoke", 1),
            &reference,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    assert_eq!(
        h.call("GET", &path, "If-None-Match: *\r\n", node_fixture::TOKEN)
            .await
            .0,
        403
    );
    assert!(
        store.snapshot().retained_buffer_bytes > 0,
        "cache bytes do not imply permission"
    );
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn physical_corruption_symlinks_and_atomic_directory_substitution_cannot_change_served_bytes()
{
    use std::os::unix::fs::symlink;
    let h = Harness::new().await;
    let path = h.publish("first", b"hello");
    let digest = latent_artifacts::package::artifact_blob_digest(b"hello");
    let name = digest.as_str().strip_prefix("sha256:").unwrap();
    let file = h.repository.root().join("blobs").join(name);
    std::fs::write(&file, b"wrong").unwrap();
    assert_eq!(
        h.call("HEAD", &path, "If-None-Match: *\r\n", node_fixture::TOKEN)
            .await
            .0,
        502
    );
    assert_eq!(h.store().snapshot().cache_entries, 0);
    std::fs::write(&file, b"hello").unwrap();
    let outside = h.storage.path().join("outside");
    std::fs::write(&outside, b"hello").unwrap();
    std::fs::remove_file(&file).unwrap();
    symlink(&outside, &file).unwrap();
    assert_eq!(h.call("GET", &path, "", node_fixture::TOKEN).await.0, 502);
    std::fs::remove_file(&file).unwrap();
    std::fs::write(&file, b"hello").unwrap();
    let blobs = h.repository.root().join("blobs");
    let moved = h.repository.root().join("saved-blobs");
    std::fs::rename(&blobs, &moved).unwrap();
    symlink(&moved, &blobs).unwrap();
    assert_eq!(h.call("GET", &path, "", node_fixture::TOKEN).await.0, 502);
    std::fs::remove_file(&blobs).unwrap();
    std::fs::rename(&moved, &blobs).unwrap();
    let root = h.repository.root().to_path_buf();
    std::fs::rename(&root, h.storage.path().join("original-catalog")).unwrap();
    std::fs::create_dir_all(root.join("blobs")).unwrap();
    std::fs::write(root.join("blobs").join(name), b"wrong").unwrap();
    // The source holds the original catalog directory, not a re-resolved pathname.
    assert_eq!(
        h.call("GET", &path, "", node_fixture::TOKEN).await.2,
        b"hello"
    );
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn disconnected_blocking_read_keeps_its_slot_until_actual_completion() {
    let h = Harness::new().await;
    let path = h.publish("first", b"hello");
    let store = h.store();
    let (entered, started) = std::sync::mpsc::channel();
    let (resume, blocked) = std::sync::mpsc::channel();
    *store.pause.lock().unwrap() = Some((entered, blocked));
    let mut socket = TcpStream::connect(h.owner.local_addr()).await.unwrap();
    socket
        .write_all(node_fixture::request("GET", &path, node_fixture::TOKEN, 0, true).as_bytes())
        .await
        .unwrap();
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    assert_eq!(store.snapshot().active_reads, 1);
    drop(socket);
    node_fixture::wait(|| h.owner.handle().snapshot().connections == 0).await;
    assert!(
        !store
            .shutdown(Instant::now() + Duration::from_millis(10))
            .await
    );
    assert_eq!(store.snapshot().active_reads, 1);
    resume.send(()).unwrap();
    node_fixture::wait(|| store.snapshot().active_reads == 0).await;
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn read_capacity_rejection_has_no_queue_or_renderer_fallback() {
    let h = Harness::new().await;
    let path = h.publish("first", b"hello");
    let store = h.store();
    let held = Arc::clone(&store.work).try_acquire_many_owned(4).unwrap();
    assert_eq!(h.call("GET", &path, "", node_fixture::TOKEN).await.0, 503);
    assert_eq!(store.snapshot().cache_misses, 0);
    assert_eq!(store.snapshot().capacity_rejections, 1);
    drop(held);
    assert_eq!(h.call("GET", &path, "", node_fixture::TOKEN).await.0, 200);
    h.finish().await;
}
