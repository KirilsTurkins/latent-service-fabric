use super::*;
use latent_audit::*;
use latent_core::TenantId;
use std::time::Instant;
struct Journal {
    handle: AuditHandle,
    worker: AuditWorker,
    _dir: tempfile::TempDir,
}
impl Journal {
    fn new(maximum_records: usize) -> Self {
        let dir = tempfile::tempdir().unwrap();
        let (handle, worker) = DirectoryPhase2AuditJournal::open(
            dir.path().join("audit"),
            AuditLimits {
                maximum_records,
                ..Default::default()
            },
        )
        .unwrap();
        Self {
            handle,
            worker,
            _dir: dir,
        }
    }
    #[allow(dead_code)]
    fn stop(&mut self) {
        self.handle.close();
        assert!(self
            .worker
            .join_until(Instant::now() + Duration::from_secs(2))
            .unwrap());
    }
    async fn query(&self, tenant: &str) -> AuditPage {
        let request = AuditQueryRequest {
            scope: AuditScope::Tenant(TenantId(tenant.into())),
            filter: AuditFilter::default(),
            cursor: None,
            limit: 32,
            maximum_bytes: 32768,
        };
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            match self.handle.query(request.clone(), deadline) {
                Err(error) if error.message == "audit-busy" && Instant::now() < deadline => {
                    tokio::task::yield_now().await;
                }
                result => return result.unwrap().wait().await.unwrap(),
            }
        }
    }
    async fn drained(&self) {
        let deadline = Instant::now() + Duration::from_secs(2);
        while self.handle.snapshot().reserved_records != 0 && Instant::now() < deadline {
            tokio::task::yield_now().await;
        }
        assert_eq!(self.handle.snapshot().reserved_records, 0);
    }
}
impl Drop for Journal {
    fn drop(&mut self) {
        self.handle.close();
        let joined = self
            .worker
            .join_until(Instant::now() + Duration::from_secs(3));
        if !std::thread::panicking() {
            assert!(matches!(joined, Ok(true)));
        }
    }
}

#[tokio::test]
async fn required_audit_keeps_provider_receipts_and_redacts_secrets() {
    for known in [true, false] {
        let journal = Journal::new(16);
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            read_request(&mut stream).await;
            if known {
                stream
                    .write_all(
                        b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                    )
                    .await
                    .unwrap();
            }
        });
        let f = Fixture::configured(
            config(port),
            &[HttpCredential {
                destination: 0,
                name: "authorization",
                value: "configured-private-token",
            }],
            latent_capabilities::broker::pools::ProviderPoolLimits::default(),
            Some(journal.handle.clone()),
        );
        let (session, _) = f.session(5000);
        let mut input = request(port, HttpMethod::Post);
        input.url.push_str("?token=secret-query");
        input.body = Some(b"private-payload".to_vec());
        input.idempotency_key = Some("private-idempotency".into());
        let done = f.provider.start(&session, input).unwrap().await.unwrap();
        if known {
            assert_eq!(done.response.as_ref().ok().unwrap().status(), 403);
        } else {
            assert!(matches!(done.response, Err(HttpError::Uncertain)));
        }
        drop(done);
        drop(session);
        server.await.unwrap();
        journal.drained().await;
        let page = journal.query("a").await;
        assert_eq!(page.records().len(), 2);
        let encoded = serde_json::to_string(page.records()).unwrap();
        for secret in [
            "configured-private-token",
            "private-payload",
            "private-idempotency",
            "secret-query",
        ] {
            assert!(!encoded.contains(secret));
        }
        let AuditRecordData::Outcome {
            conclusion: terminal,
            ..
        } = &page.records()[1].data
        else {
            panic!("terminal attempt")
        };
        assert_eq!(
            terminal
                .identities
                .capability
                .as_ref()
                .unwrap()
                .provider_outcome,
            Some(if known {
                AuditProviderOutcome::HttpResponseReceived
            } else {
                AuditProviderOutcome::Unknown
            })
        );
        drop(page);
        f.clean().await;
    }
}

#[tokio::test]
async fn streamed_required_audit_commits_metadata_and_known_header_without_claiming_body_completion(
) {
    use latent_capabilities::broker::streaming_http::{StreamingHttpInvoker, StreamingHttpRequest};
    let journal = Journal::new(16);
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let wire = read_request(&mut stream).await;
        assert!(wire.ends_with(b"private-payload"));
        stream
            .write_all(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 8\r\n\r\nshort")
            .await
            .unwrap();
    });
    let mut config = config(port);
    config.destinations[0].redirect_destinations.clear();
    let f = Fixture::configured_inner(
        config,
        &[HttpCredential {
            destination: 0,
            name: "authorization",
            value: "private-credential",
        }],
        latent_capabilities::broker::pools::ProviderPoolLimits::default(),
        Some(journal.handle.clone()),
        Some(HttpStreamLimits {
            maximum_input_bytes: 1024,
            maximum_output_bytes: 1024,
            maximum_chunk_bytes: 16,
            maximum_outstanding_chunks: 1,
        }),
    );
    let (session, _) = f.session(5000);
    let mut metadata = request(port, HttpMethod::Post);
    metadata.url.push_str("?private=query");
    metadata.idempotency_key = Some("private-key".into());
    let mut upload = f
        .streaming
        .as_ref()
        .unwrap()
        .start(
            &session,
            StreamingHttpRequest {
                metadata,
                body_length: Some(15),
            },
        )
        .unwrap()
        .await
        .unwrap();
    upload.write(b"private-payload".to_vec()).await.unwrap();
    let mut body = upload.finish().await.unwrap();
    assert_eq!(body.head().status(), 403);
    loop {
        match body.read(16).await {
            Ok(Some(chunk)) => drop(chunk),
            Ok(None) => panic!("truncated response must fail"),
            Err(_) => break,
        }
    }
    drop(body);
    drop(session);
    server.await.unwrap();
    journal.drained().await;
    let page = journal.query("a").await;
    assert_eq!(page.records().len(), 2);
    let encoded = serde_json::to_string(page.records()).unwrap();
    for secret in [
        "private-payload",
        "private-credential",
        "private=query",
        "private-key",
    ] {
        assert!(!encoded.contains(secret));
    }
    let AuditRecordData::Outcome { conclusion, .. } = &page.records()[1].data else {
        panic!("outcome")
    };
    let record = conclusion.identities.capability.as_ref().unwrap();
    assert_eq!(
        record.capability,
        latent_capabilities::broker::streaming_http::STREAMING_HTTP_CAPABILITY
    );
    assert_eq!(
        record.provider_outcome,
        Some(AuditProviderOutcome::HttpResponseReceived)
    );
    drop(page);
    f.clean().await;
}
