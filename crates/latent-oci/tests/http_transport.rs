use latent_artifacts::package::artifact_blob_digest;
use latent_core::PlatformErrorCode;
use latent_oci::{
    HttpOciRegistry, OciDescriptor, OciReference, OciRegistry, RegistryConfig, RegistryCredentials,
    RegistryLimits,
};
use std::{collections::BTreeMap, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    time::{timeout, Instant},
};

fn configuration(address: std::net::SocketAddr) -> RegistryConfig {
    RegistryConfig {
        origin: format!("http://{address}"),
        repository: "tests/package".into(),
        credentials: RegistryCredentials::Basic {
            username: "fixture".into(),
            password: "test-only-secret".into(),
        },
        addresses: vec![],
        additional_root_certificates: vec![],
        allow_insecure_loopback: true,
        limits: RegistryLimits::default(),
    }
}
fn reference(address: std::net::SocketAddr) -> OciReference {
    OciReference {
        registry: address.to_string(),
        repository: "tests/package".into(),
        reference: "latest".into(),
    }
}
fn descriptor(bytes: &[u8]) -> OciDescriptor {
    OciDescriptor {
        media_type: "application/wasm".into(),
        artifact_type: None,
        digest: artifact_blob_digest(bytes).to_string(),
        size_bytes: bytes.len() as u64,
        annotations: BTreeMap::default(),
    }
}
async fn request(stream: &mut tokio::net::TcpStream) -> Vec<u8> {
    let mut bytes = Vec::new();
    loop {
        let mut byte = [0; 1];
        stream.read_exact(&mut byte).await.unwrap();
        bytes.push(byte[0]);
        assert!(bytes.len() <= 8192);
        if bytes.ends_with(b"\r\n\r\n") {
            return bytes;
        }
    }
}

#[tokio::test]
async fn basic_auth_is_scoped_and_generic_blob_mime_preserves_exact_bytes() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let headers = String::from_utf8(request(&mut stream).await).unwrap();
        assert!(headers.starts_with("GET /v2/tests/package/blobs/sha256:"));
        assert!(headers
            .to_ascii_lowercase()
            .contains("authorization: basic "));
        stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: 3\r\nConnection: close\r\n\r\nabc").await.unwrap();
    });
    let client = HttpOciRegistry::new(configuration(address)).unwrap();
    assert_eq!(
        client
            .pull_blob(&reference(address), &descriptor(b"abc"), 3)
            .await
            .unwrap(),
        b"abc"
    );
    server.await.unwrap();
    assert_eq!(client.usage().retained_bytes, 0);
    client
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
}

#[tokio::test]
async fn response_limits_hashes_and_ambiguous_headers_fail_closed() {
    for (response, code) in [
        (b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\nabcd".as_slice(), PlatformErrorCode::ResourceExhausted),
        (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n2\r\nab\r\n2\r\ncd\r\n0\r\n\r\n", PlatformErrorCode::ResourceExhausted),
        (b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nConnection: close\r\n\r\nxyz", PlatformErrorCode::CorruptArtifact),
        (b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nContent-Encoding: gzip\r\nConnection: close\r\n\r\nabc", PlatformErrorCode::InvalidArgument),
        (b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nContent-Type: application/wasm\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nabc", PlatformErrorCode::CorruptArtifact),
    ] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap(); request(&mut stream).await;
            let _ = stream.write_all(response).await;
        });
        let client = HttpOciRegistry::new(configuration(address)).unwrap();
        assert_eq!(client.pull_blob(&reference(address), &descriptor(b"abc"), 3).await.unwrap_err().code, code);
        server.await.unwrap();
        assert_eq!(client.usage().in_flight, 0);
        assert_eq!(client.usage().retained_bytes, 0);
        client.shutdown(Instant::now() + Duration::from_secs(1)).await.unwrap();
    }
}

#[tokio::test]
async fn redirects_do_not_forward_credentials_to_another_origin() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let other = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let other_address = other.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        request(&mut stream).await;
        let response = format!("HTTP/1.1 302 Found\r\nLocation: http://{other_address}/steal\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
        stream.write_all(response.as_bytes()).await.unwrap();
    });
    let client = HttpOciRegistry::new(configuration(address)).unwrap();
    assert!(client
        .pull_blob(&reference(address), &descriptor(b"abc"), 3)
        .await
        .is_err());
    server.await.unwrap();
    assert!(timeout(Duration::from_millis(30), other.accept())
        .await
        .is_err());
    client
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
}

#[tokio::test]
async fn stalled_reads_time_out_and_release_admission_and_bytes() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        request(&mut stream).await;
        tokio::time::sleep(Duration::from_secs(2)).await;
    });
    let mut config = configuration(address);
    config.limits.request_timeout = Duration::from_millis(30);
    let client = HttpOciRegistry::new(config).unwrap();
    assert_eq!(
        client
            .pull_blob(&reference(address), &descriptor(b"abc"), 3)
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(client.usage().in_flight, 0);
    assert_eq!(client.usage().retained_bytes, 0);
    server.abort();
    let _ = server.await;
    client
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
}

#[tokio::test]
async fn invalid_authority_and_oversized_materialization_never_reach_the_socket() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let mut config = configuration(address);
    config.limits.max_retained_bytes = 2;
    let client = HttpOciRegistry::new(config).unwrap();
    assert_eq!(
        client
            .pull_blob(&reference(address), &descriptor(b"abc"), 3)
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    let mut wrong = reference(address);
    wrong.repository = "another/repository".into();
    assert_eq!(
        client
            .pull_blob(&wrong, &descriptor(b"a"), 1)
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::InvalidArgument
    );
    assert!(timeout(Duration::from_millis(30), listener.accept())
        .await
        .is_err());
    client
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
}

#[tokio::test]
async fn configuration_rejects_unscoped_dns_and_keeps_debug_private() {
    let address = "127.0.0.1:5000".parse().unwrap();
    let config = configuration(address);
    assert!(!format!("{config:?}").contains("test-only-secret"));
    for origin in [
        "http://example.com",
        "https://user:secret@example.com",
        "https://example.com/path",
        "https://example.com",
    ] {
        let mut config = configuration(address);
        config.origin = origin.into();
        assert!(HttpOciRegistry::new(config).is_err());
    }
    let mut config = configuration(address);
    config.repository = "bad/../repo".into();
    assert!(HttpOciRegistry::new(config).is_err());
}
