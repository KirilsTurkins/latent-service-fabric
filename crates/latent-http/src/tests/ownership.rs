use super::*;
#[tokio::test]
async fn shared_idle_connection_owns_no_activation_and_reuses_the_real_socket() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        for _ in 0..2 {
            read_request(&mut stream).await;
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
                .await
                .unwrap();
        }
        let mut byte = [0];
        assert_eq!(stream.read(&mut byte).await.unwrap(), 0);
    });
    let f = Fixture::new(config(port));
    for _ in 0..2 {
        let (session, _) = f.session(5000);
        let observer = session.observer();
        let done = f
            .provider
            .start(&session, request(port, HttpMethod::Get))
            .unwrap()
            .await
            .unwrap();
        assert!(done.response.is_ok());
        drop(done);
        drop(session);
        assert!(observer.is_quiescent());
        assert_eq!(
            f.io.snapshot(),
            latent_capabilities::broker::io::IoSnapshot::default()
        );
        assert_eq!(f.pools.snapshot().unwrap().idle_connections, 1);
    }
    f.clean().await;
    server.await.unwrap();
}
#[tokio::test]
async fn healthy_inflight_requests_share_bounded_provider_capacity() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (first, accepted) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut a, _) = listener.accept().await.unwrap();
        read_request(&mut a).await;
        first.send(()).unwrap();
        let (mut b, _) = listener.accept().await.unwrap();
        read_request(&mut b).await;
        for stream in [&mut a, &mut b] {
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                .await
                .unwrap();
        }
    });
    let f = Fixture::new(config(port));
    let (one, _) = f.session(5000);
    let (two, _) = f.session(5000);
    let mut first = f
        .provider
        .start(&one, request(port, HttpMethod::Get))
        .unwrap();
    tokio::select! {_=&mut first=>panic!("server waits for concurrent peer"),_=accepted=>{}}
    let second = f
        .provider
        .start(&two, request(port, HttpMethod::Get))
        .unwrap();
    let (a, b) = tokio::join!(first, second);
    let a = a.unwrap();
    let b = b.unwrap();
    assert!(a.response.is_ok());
    assert!(b.response.is_ok());
    drop(a);
    drop(b);
    drop(one);
    drop(two);
    server.await.unwrap();
    f.clean().await;
}

#[tokio::test]
async fn queue_revocation_denies_fresh_dispatch_and_zero_budget_never_connects() {
    use latent_policy::capability::{MutationRequest, RecordKind};
    use std::time::Instant;
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let f = Fixture::new(config(port));
    // Admit the zero-egress request once so the envelope and control share the
    // same deadline, even when setup crosses a wall-clock millisecond.
    let (request_zero, control) = f.request_with_outbound("no-egress", 5000, 0);
    let session = f
        .broker
        .open_session(f.plan.clone(), &request_zero, &control, &f.publication)
        .unwrap();
    assert!(matches!(
        f.provider
            .start(&session, request(port, HttpMethod::Get))
            .unwrap()
            .await,
        Err(HttpError::BudgetExhausted)
    ));
    drop(session);
    let (session, _) = f.session(5000);
    let future = f
        .provider
        .start(&session, request(port, HttpMethod::Get))
        .unwrap();
    f.policies
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "revoke",
                expected_revision: 2,
                document: None,
            },
            Instant::now() + Duration::from_secs(2),
            |_| Ok(()),
        )
        .unwrap();
    assert!(matches!(future.await, Err(HttpError::PermissionDenied)));
    assert!(
        tokio::time::timeout(Duration::from_millis(30), listener.accept())
            .await
            .is_err()
    );
    drop(session);
    f.clean().await;
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn cancelling_a_connect_stalled_by_full_accept_backlog_closes_its_owner() {
    let socket = tokio::net::TcpSocket::new_v4().unwrap();
    socket.bind("127.0.0.1:0".parse().unwrap()).unwrap();
    let listener = socket.listen(1).unwrap();
    let address = listener.local_addr().unwrap();
    let _first = tokio::net::TcpStream::connect(address).await.unwrap();
    let _second = tokio::net::TcpStream::connect(address).await.unwrap();
    let f = Fixture::new(config(address.port()));
    let (session, control) = f.session(5000);
    let mut operation = f
        .provider
        .start(&session, request(address.port(), HttpMethod::Get))
        .unwrap();
    tokio::select! {_=&mut operation=>panic!("full Linux accept backlog must stall the connect"),()=tokio::time::sleep(Duration::from_millis(40))=>{}}
    assert_eq!(f.pools.snapshot().unwrap().connections, 1);
    control.probe.0.store(true, Ordering::Release);
    let done = operation.await.unwrap();
    assert!(matches!(done.response, Err(HttpError::Cancelled)));
    drop(done);
    drop(session);
    assert_eq!(f.pools.snapshot().unwrap().connections, 0);
    f.clean().await;
}
#[tokio::test]
async fn cancelling_a_partial_mutation_write_is_uncertain_and_closes_the_socket() {
    let socket = tokio::net::TcpSocket::new_v4().unwrap();
    socket.set_recv_buffer_size(4096).unwrap();
    socket.bind("127.0.0.1:0".parse().unwrap()).unwrap();
    let listener = socket.listen(1).unwrap();
    let port = listener.local_addr().unwrap().port();
    let (started, received) = tokio::sync::oneshot::channel();
    let (release, wait) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = [0; 4096];
        let mut count = stream.read(&mut bytes).await.unwrap();
        assert!(count > 0);
        started.send(()).unwrap();
        wait.await.unwrap();
        loop {
            let n = tokio::time::timeout(Duration::from_secs(2), stream.read(&mut bytes))
                .await
                .unwrap()
                .unwrap();
            if n == 0 {
                break;
            }
            count += n;
            assert!(count < 512 * 1024);
        }
        count
    });
    let mut cfg = config(port);
    cfg.limits.maximum_request_body_bytes = 512 * 1024;
    let f = Fixture::new(cfg);
    let (session, control) = f.session(5000);
    let mut input = request(port, HttpMethod::Post);
    input.body = Some(vec![42; 512 * 1024]);
    let mut operation = f.provider.start(&session, input).unwrap();
    tokio::select! {_=&mut operation=>panic!("peer cannot accept the entire body"),_=received=>{}}
    assert!(f.io.snapshot().staged_bytes >= 512 * 1024);
    control.probe.0.store(true, Ordering::Release);
    let done = operation.await.unwrap();
    assert!(matches!(done.response, Err(HttpError::Uncertain)));
    drop(done);
    drop(session);
    release.send(()).unwrap();
    assert!(server.await.unwrap() < 512 * 1024);
    f.clean().await;
}

#[tokio::test]
async fn unpolled_input_and_stale_credential_epochs_cannot_escape_ownership() {
    let f = Fixture::new(config(12345));
    let (session, _) = f.session(5000);
    let observer = session.observer();
    let mut input = request(12345, HttpMethod::Post);
    input.body = Some(vec![0; 4096]);
    let invocation = f.provider.start(&session, input).unwrap();
    assert!(f.io.snapshot().staged_bytes >= 4096);
    drop(session);
    assert!(!observer.is_quiescent());
    drop(invocation);
    assert!(observer.is_quiescent());
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    let (session, _) = f.session(5000);
    let replacement = HttpProvider::install(
        f.pools.clone(),
        "http",
        2,
        1,
        config(12345),
        &[HttpCredential {
            destination: 0,
            name: "authorization",
            value: "rotated-private",
        }],
    )
    .unwrap();
    assert_eq!(
        f.provider.reference().configuration_digest(),
        replacement.reference().configuration_digest()
    );
    assert!(matches!(
        f.provider.start(&session, request(12345, HttpMethod::Get)),
        Err(HttpError::PermissionDenied)
    ));
    assert!(matches!(
        replacement.start(&session, request(12345, HttpMethod::Get)),
        Err(HttpError::PermissionDenied)
    ));
    drop(session);
    drop(replacement);
    f.clean().await;
}

// Borrowed source fixture; its preexisting caller storage is not the ingress copy.
struct BorrowedHttpInput<'a> {
    url: &'a str,
    body: Option<&'a [u8]>,
    headers: &'a [(&'a str, &'a str)],
    writes: usize,
}
impl latent_capabilities::broker::http::HttpRequestSource for BorrowedHttpInput<'_> {
    fn method(&self) -> HttpMethod {
        HttpMethod::Get
    }
    fn timeout_millis(&self) -> Option<u64> {
        None
    }
    fn header_count(&self) -> usize {
        self.headers.len()
    }
    fn text_len(
        &mut self,
        field: latent_capabilities::broker::http::HttpTextField,
    ) -> Result<Option<usize>, HttpError> {
        Ok(self.field(field)?.map(str::len))
    }
    fn write_text(
        &mut self,
        field: latent_capabilities::broker::http::HttpTextField,
        output: &mut [u8],
    ) -> Result<(), HttpError> {
        let text = self.field(field)?.ok_or(HttpError::InvalidRequest)?;
        if text.len() != output.len() {
            return Err(HttpError::InvalidRequest);
        }
        output.copy_from_slice(text.as_bytes());
        self.writes += 1;
        Ok(())
    }
    fn body_len(&self) -> Option<usize> {
        self.body.map(<[u8]>::len)
    }
    fn write_body(&mut self, output: &mut [u8]) -> Result<(), HttpError> {
        let bytes = self.body.ok_or(HttpError::InvalidRequest)?;
        if bytes.len() != output.len() {
            return Err(HttpError::InvalidRequest);
        }
        output.copy_from_slice(bytes);
        self.writes += 1;
        Ok(())
    }
}
impl BorrowedHttpInput<'_> {
    fn field(
        &self,
        field: latent_capabilities::broker::http::HttpTextField,
    ) -> Result<Option<&str>, HttpError> {
        use latent_capabilities::broker::http::HttpTextField::*;
        Ok(match field {
            Url => Some(self.url),
            HeaderName(i) => Some(self.headers.get(i).ok_or(HttpError::InvalidRequest)?.0),
            HeaderValue(i) => Some(self.headers.get(i).ok_or(HttpError::InvalidRequest)?.1),
            BodyMediaType | IdempotencyKey => None,
        })
    }
}
fn ingress_limits() -> latent_capabilities::broker::http::HttpInputLimits {
    latent_capabilities::broker::http::HttpInputLimits {
        maximum_headers: 32,
        maximum_header_bytes: 8192,
        maximum_body_bytes: 32768,
    }
}
#[tokio::test]
async fn native_http_ingress_refuses_before_materialization_and_unpolled_cancel_returns_credit() {
    let f = Fixture::new(config(12345));
    let (session, control) = f.session(5000);
    let baseline = control.budget.host_memory_bytes();
    let before = f.io.snapshot();
    let mut source = BorrowedHttpInput {
        url: "http://localhost:12345/allowed",
        body: Some(b"resident"),
        headers: &[],
        writes: 0,
    };
    let padding = control
        .budget
        .reserve_host_memory(control.budget.granted().memory_bytes - baseline)
        .unwrap();
    assert!(matches!(
        f.provider.start_from(&session, &mut source),
        Err(HttpError::BudgetExhausted)
    ));
    assert_eq!(source.writes, 0);
    assert_eq!(f.io.snapshot(), before);
    drop(padding);
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    let future = f.provider.start_from(&session, &mut source).unwrap();
    assert_eq!(source.writes, 2);
    assert!(control.budget.host_memory_bytes() > baseline);
    drop(future);
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    assert_eq!(f.io.snapshot(), before);
    drop(session);
    f.clean().await;
}
#[tokio::test]
async fn native_http_ingress_rejects_equal_grant_foreign_session_before_body_copy() {
    use latent_capabilities::broker::http::PreparedHttpInput;
    let f = Fixture::new(config(12345));
    let (a, ca) = f.session(5000);
    let (b, cb) = f.session(5000);
    let abase = ca.budget.host_memory_bytes();
    let mut source = BorrowedHttpInput {
        url: "http://localhost:12345/allowed",
        body: Some(b"resident"),
        headers: &[],
        writes: 0,
    };
    let prepared = PreparedHttpInput::new(&a, &mut source).unwrap();
    let client = f.provider.inner.client(0).unwrap();
    let foreign = f.pools.admit(&client, &b).unwrap();
    let bbefore = cb.budget.host_memory_bytes();
    assert!(matches!(
        prepared.finish(&foreign, &mut source, ingress_limits()),
        Err(HttpError::PermissionDenied)
    ));
    assert_eq!(source.writes, 1);
    assert_eq!(ca.budget.host_memory_bytes(), abase);
    assert_eq!(cb.budget.host_memory_bytes(), bbefore);
    drop(foreign);
    drop(a);
    drop(b);
    f.clean().await;
}
#[tokio::test]
async fn native_http_ingress_bytes_and_driver_token_keep_original_credit_until_actual_last_drop() {
    use latent_capabilities::broker::http::PreparedHttpInput;
    let f = Fixture::new(config(12345));
    let (session, control) = f.session(5000);
    let baseline = control.budget.host_memory_bytes();
    let mut caller = *b"resident";
    let mut source = BorrowedHttpInput {
        url: "http://localhost:12345/allowed",
        body: Some(&caller),
        headers: &[],
        writes: 0,
    };
    let prepared = PreparedHttpInput::new(&session, &mut source).unwrap();
    let client = f.provider.inner.client(0).unwrap();
    let admission = f.pools.admit(&client, &session).unwrap();
    let mut request = prepared
        .finish(&admission, &mut source, ingress_limits())
        .unwrap();
    drop(source);
    caller.fill(0);
    // These are the ACTUAL types stored by Bytes and HttpConnection.input.
    let driver_token = request.memory().clone();
    let body = bytes::Bytes::from_owner(request.take_body());
    let delayed = body.clone();
    drop(body);
    drop(request);
    drop(admission);
    assert_eq!(delayed.as_ref(), b"resident");
    let held = control.budget.host_memory_bytes();
    assert!(held > baseline);
    drop(delayed);
    assert_eq!(control.budget.host_memory_bytes(), held); // driver still owns current hop
    drop(driver_token);
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    drop(session);
    f.clean().await;
}
#[tokio::test]
async fn native_http_ingress_one_slot_redirect_retires_hop_without_retagging_credit() {
    use latent_capabilities::broker::pools::ProviderPoolLimits;
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        for hop in 0..2 {
            let (mut stream, _) = listener.accept().await.unwrap();
            read_request(&mut stream).await;
            if hop == 0 {
                stream.write_all(b"HTTP/1.1 302 Found\r\nLocation: /allowed/again\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").await.unwrap();
            } else {
                stream
                    .write_all(
                        b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok",
                    )
                    .await
                    .unwrap();
            }
        }
    });
    let mut cfg = config(port);
    cfg.limits.maximum_redirects = 1;
    let f = Fixture::configured(
        cfg,
        &[],
        ProviderPoolLimits {
            maximum_running_requests: 1,
            maximum_running_per_provider: 1,
            maximum_running_per_tenant: 1,
            ..ProviderPoolLimits::default()
        },
        None,
    );
    let (session, control) = f.session(5000);
    let baseline = control.budget.host_memory_bytes();
    let url = format!("http://localhost:{port}/allowed");
    let mut source = BorrowedHttpInput {
        url: &url,
        body: None,
        headers: &[],
        writes: 0,
    };
    let done = f
        .provider
        .start_from(&session, &mut source)
        .unwrap()
        .await
        .unwrap();
    assert_eq!(done.response.as_ref().unwrap().body(), b"ok");
    drop(done);
    server.await.unwrap();
    // Quarantine/driver cleanup is physical work, not the dropped waiter.
    f.clean().await;
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    drop(session);
}
#[tokio::test]
async fn native_http_ingress_pending_real_driver_cancellation_retires_original_credit() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (entered, started) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let wire = read_request(&mut stream).await;
        assert!(wire.ends_with(b"resident"));
        entered.send(()).unwrap();
        let mut byte = [0];
        assert_eq!(stream.read(&mut byte).await.unwrap(), 0);
    });
    let f = Fixture::new(config(port));
    let (session, control) = f.session(5000);
    let baseline = control.budget.host_memory_bytes();
    let url = format!("http://localhost:{port}/allowed");
    let mut source = BorrowedHttpInput {
        url: &url,
        body: Some(b"resident"),
        headers: &[],
        writes: 0,
    };
    let mut invocation = f.provider.start_from(&session, &mut source).unwrap();
    tokio::select! {_=&mut invocation=>panic!("server retains response"),_=started=>{}}
    assert!(control.budget.host_memory_bytes() > baseline);
    drop(invocation);
    server.await.unwrap();
    // Quarantine/driver cleanup is physical work, not the dropped waiter.
    f.clean().await;
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    drop(session);
}

#[tokio::test]
async fn native_http_ingress_nested_header_limit_refuses_without_payload_copy() {
    let f = Fixture::new(config(12345));
    let (session, control) = f.session(5000);
    let baseline = control.budget.host_memory_bytes();
    let headers = [("x-test", "value"); 65];
    let mut source = BorrowedHttpInput {
        url: "http://localhost:12345/allowed",
        body: Some(b"resident"),
        headers: &headers,
        writes: 0,
    };
    assert!(matches!(
        f.provider.start_from(&session, &mut source),
        Err(HttpError::RequestTooLarge)
    ));
    assert_eq!(source.writes, 0);
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    drop(session);
    f.clean().await;
}
#[test]
fn borrowed_http_target_validation_preserves_descriptor_and_destination_semantics() {
    use latent_policy::capability::{ResourceRequest, ResourceTarget};

    // The comparison uses the old serialized explanation boundary as its
    // oracle; the new borrowed predicate does not supply execution authority.
    let origins = [
        HttpOrigin {
            scheme: "http".into(),
            host: "localhost".into(),
            port: 18080,
        },
        HttpOrigin {
            scheme: "https".into(),
            host: "example.test".into(),
            port: 443,
        },
        HttpOrigin {
            scheme: "ftp".into(),
            host: "example.test".into(),
            port: 21,
        },
        HttpOrigin {
            scheme: "http".into(),
            host: "UPPER.test".into(),
            port: 80,
        },
        HttpOrigin {
            scheme: "http".into(),
            host: "".into(),
            port: 80,
        },
        HttpOrigin {
            scheme: "http".into(),
            host: "localhost".into(),
            port: 0,
        },
        HttpOrigin {
            scheme: "http".into(),
            host: "127.0.0.1".into(),
            port: 80,
        },
        HttpOrigin {
            scheme: "http".into(),
            host: "::1".into(),
            port: 80,
        },
        HttpOrigin {
            scheme: "http".into(),
            host: "127.00.0.1".into(),
            port: 80,
        },
    ];
    let longest = format!("/{}", "a".repeat(2047));
    let oversized = format!("{longest}a");
    let paths = [
        "/",
        "/allowed/item",
        "/a%2Fb",
        "/a\\b",
        "/a?b",
        "/a#b",
        "/./a",
        "/a/..",
        "/bad path",
        "/quoted\"path",
        "/é",
        &longest,
        &oversized,
    ];
    for origin in &origins {
        for method in [
            "GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE",
        ] {
            for path in paths {
                let encoded = serde_json::to_vec(&serde_json::json!({
                    "kind":"http", "origin":origin, "method":method, "path":path
                }))
                .unwrap();
                assert!(encoded.len() <= 4096);
                assert_eq!(
                    ResourceTarget::Http {
                        origin,
                        method,
                        path
                    }
                    .is_valid(),
                    ResourceRequest::parse(&encoded).is_ok()
                );
            }
        }
    }

    // Exercise the production caller, including canonical normalization before
    // policy validation. The opaque Url parser itself remains a separate cost.
    let config = config(18080);
    for raw in [
        "http://localhost:18080/allowed",
        "HTTP://LOCALHOST:18080/allowed",
        "http://localhost:18080/a/../allowed",
        "http://localhost:18080/allowed?q=%22",
    ] {
        let destination = crate::destination::parse(raw, &config).unwrap();
        let encoded = serde_json::to_vec(&serde_json::json!({"kind":"http",
            "origin":&destination.origin, "method":"GET", "path":destination.url.path()}))
        .unwrap();
        assert!(ResourceRequest::parse(&encoded).is_ok());
    }
    for (raw, expected) in [
        ("http://localhost:18080/a%2Fb", HttpError::InvalidUrl),
        ("http://localhost:18080/a\"b", HttpError::InvalidUrl),
        ("http://localhost:18080/a#b", HttpError::InvalidUrl),
        ("http://user@localhost:18080/a", HttpError::InvalidUrl),
        ("http://other.test:18080/a", HttpError::PermissionDenied),
        ("http://localhost:18080/é", HttpError::InvalidUrl),
    ] {
        assert_eq!(
            crate::destination::parse(raw, &config).err(),
            Some(expected)
        );
    }
    let prefix = "http://localhost:18080/";
    let raw = format!("{prefix}{}", "a".repeat(2048 - prefix.len()));
    let destination = crate::destination::parse(&raw, &config).unwrap();
    let encoded = serde_json::to_vec(&serde_json::json!({"kind":"http",
        "origin":&destination.origin, "method":"GET", "path":destination.url.path()}))
    .unwrap();
    assert!(encoded.len() <= 4096);
    assert!(ResourceRequest::parse(&encoded).is_ok());
    assert_eq!(
        crate::destination::parse(&(raw + "a"), &config).err(),
        Some(HttpError::InvalidUrl)
    );
}

#[test]
fn typed_http_digest_iterator_preserves_original_framing_and_bounds() {
    use latent_capabilities::broker::CapabilityRequestDigest;
    use latent_core::PlatformErrorCode;
    use std::cell::Cell;

    // Fixed vectors were independently generated from the original wire
    // framing: domain separator, then u64-LE length followed by each field.
    fn expected(hex: &str) -> String {
        let bytes: Vec<u8> = (0..hex.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).unwrap())
            .collect();
        format!("CapabilityRequestDigest({bytes:?})")
    }
    for (parts, hash) in [
        (
            &[][..],
            "6c14e5a0452fef4e03a99f601905c6ee467e5c7c5d3225778ae7673b93b63d0d",
        ),
        (
            &[&b"ab"[..], &b"c"[..]][..],
            "356e4ef73f78e342317b0b5c454dcfeb0cfba96a6ee7bb27ca55ae006ea011e2",
        ),
        (
            &[&b"a"[..], &b"bc"[..]][..],
            "8c481c85f1f41a4c4455b2f4fc5528c9938efe6e78a35f9de949db2b514d5ada",
        ),
    ] {
        assert_eq!(
            format!("{:?}", CapabilityRequestDigest::from_parts(parts).unwrap()),
            expected(hash)
        );
        assert_eq!(
            format!(
                "{:?}",
                CapabilityRequestDigest::from_parts_iter(parts.iter().copied()).unwrap()
            ),
            expected(hash)
        );
    }
    let destination =
        crate::destination::parse("http://localhost:18080/allowed", &config(18080)).unwrap();
    let mut input = request(18080, HttpMethod::Get);
    assert_eq!(
        format!(
            "{:?}",
            crate::execute::request::digest(&input, &destination).unwrap()
        ),
        expected("5bb5831fda556d967368b1bddbfd9471efa54f5a5b6f0da02f3b4a955ae2c6b9")
    );
    input.method = HttpMethod::Post;
    input.body = Some(vec![0, 1, 255, 42]);
    input.body_media_type = Some("application/octet-stream".into());
    input.idempotency_key = Some("key".into());
    input.headers = (0..64)
        .map(|i| HttpHeader {
            name: format!("x-{i}"),
            value: format!("v-{i}"),
        })
        .collect();
    assert_eq!(
        format!(
            "{:?}",
            crate::execute::request::digest(&input, &destination).unwrap()
        ),
        expected("fd152ba1325ba3b845458a7680f02d204cfad88efc23d0ab4081793fcf7ab7a5")
    );

    let empty = [&[][..]; 256];
    assert!(CapabilityRequestDigest::from_parts(&empty).is_ok());
    assert!(CapabilityRequestDigest::from_parts_iter(empty).is_ok());
    let seen = Cell::new(0);
    let error = CapabilityRequestDigest::from_parts_iter(
        std::iter::repeat(&[][..]).inspect(|_| seen.set(seen.get() + 1)),
    )
    .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(seen.get(), 257);
    let payload = vec![b'x'; 1024 * 1024 + 1];
    assert!(CapabilityRequestDigest::from_parts_iter([&payload[..1024 * 1024]]).is_ok());
    let error = CapabilityRequestDigest::from_parts_iter([payload.as_slice()]).unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(
        CapabilityRequestDigest::from_parts(&[payload.as_slice()])
            .unwrap_err()
            .code,
        error.code
    );
}
