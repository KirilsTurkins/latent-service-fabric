use super::*;

async fn reason_call(
    f: &Fixture,
    session: &latent_capabilities::broker::CapabilitySession,
) -> latent_capabilities::broker::pools::PoolCall {
    let client = f.provider.client(0).unwrap();
    let ready = f
        .pools
        .admit(&client, session)
        .unwrap()
        .wait()
        .await
        .unwrap();
    let origin = HttpOrigin {
        scheme: "http".into(),
        host: "localhost".into(),
        port: 80,
    };
    ready
        .dispatch(
            CAP,
            "send",
            latent_policy::capability::ResourceTarget::Http {
                origin: &origin,
                method: "GET",
                path: "/allowed",
            },
            &[],
            latent_capabilities::broker::CapabilityCallCost::new(2048)
                .with_charge(latent_core::BudgetDimension::OutboundRequests, 1)
                .unwrap(),
        )
        .await
        .unwrap()
}

#[tokio::test]
async fn reason_phrase_keeps_complete_prepaid_capacity_after_its_admission_and_session_close() {
    use latent_capabilities::broker::http::{HttpResponseHead, MAXIMUM_HTTP_REASON_BYTES};
    let f = Fixture::new(config(80));
    let (session, _) = f.session(5000);
    let observer = session.observer();
    let call = reason_call(&f, &session).await;
    let headers = call.io().buffer(64, 128).unwrap();
    let mut reason = call.io().buffer(MAXIMUM_HTTP_REASON_BYTES, 128).unwrap();
    reason.spare_mut().unwrap()[..3].copy_from_slice(b"raw");
    reason.advance_written(3).unwrap();
    let head = HttpResponseHead::with_reason_phrase(200, headers, Some(reason)).unwrap();
    assert_eq!(head.reason_phrase(), Some(&b"raw"[..]));
    assert_eq!(f.io.snapshot().result_bytes, 64 + MAXIMUM_HTTP_REASON_BYTES);
    assert_eq!(f.io.snapshot().buffers, 2);
    drop(call);
    drop(session);
    assert!(!observer.is_quiescent());
    assert_eq!(head.reason_phrase(), Some(&b"raw"[..]));
    assert_eq!(f.io.snapshot().result_bytes, 64 + MAXIMUM_HTTP_REASON_BYTES);
    drop(head);
    assert!(observer.is_quiescent());
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    f.clean().await;
}

#[tokio::test]
async fn reason_metadata_distinguishes_empty_absent_and_invalid_without_leaking_buffer_charges() {
    use latent_capabilities::broker::http::{HttpResponseHead, MAXIMUM_HTTP_REASON_BYTES};
    let f = Fixture::new(config(80));
    let (session, _) = f.session(5000);
    let call = reason_call(&f, &session).await;
    let baseline = f.io.snapshot();
    let headers = call.io().buffer(64, 128).unwrap();
    let head = HttpResponseHead::new(200, headers).unwrap();
    assert_eq!(head.reason_phrase(), None);
    assert_eq!(f.io.snapshot().buffers, 1);
    drop(head);
    let headers = call.io().buffer(64, 128).unwrap();
    let reason = call.io().buffer(MAXIMUM_HTTP_REASON_BYTES, 128).unwrap();
    let head = HttpResponseHead::with_reason_phrase(200, headers, Some(reason)).unwrap();
    assert_eq!(head.reason_phrase(), Some(&b""[..]));
    assert_eq!(f.io.snapshot().result_bytes, 64 + MAXIMUM_HTTP_REASON_BYTES);
    drop(head);
    assert_eq!(f.io.snapshot(), baseline);
    for (capacity, bytes) in [
        (MAXIMUM_HTTP_REASON_BYTES + 1, &b""[..]),
        (MAXIMUM_HTTP_REASON_BYTES, &b"bad\rphrase"[..]),
    ] {
        let headers = call.io().buffer(64, 128).unwrap();
        let mut reason = call.io().buffer(capacity, 128).unwrap();
        reason.spare_mut().unwrap()[..bytes.len()].copy_from_slice(bytes);
        reason.advance_written(bytes.len()).unwrap();
        assert!(HttpResponseHead::with_reason_phrase(200, headers, Some(reason)).is_err());
        assert_eq!(f.io.snapshot(), baseline);
    }
    drop(call);
    drop(session);
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    f.clean().await;
}
use std::io::Write;
async fn reply(raw: Vec<u8>, limit: usize) -> Result<Vec<u8>, HttpError> {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        let _ = stream.write_all(&raw).await;
    });
    let mut cfg = config(port);
    cfg.limits.maximum_response_body_bytes = limit;
    let f = Fixture::new(cfg);
    let (session, _) = f.session(5000);
    let done = f
        .provider
        .start(&session, request(port, HttpMethod::Get))
        .unwrap()
        .await
        .unwrap();
    let result = done
        .response
        .as_ref()
        .map(|r| r.body().to_vec())
        .map_err(|e| *e);
    drop(done);
    drop(session);
    server.await.unwrap();
    f.clean().await;
    result
}
#[tokio::test]
async fn lengths_framing_and_compression_are_bounded() {
    assert_eq!(
        reply(
            b"HTTP/1.1 200 OK\r\nContent-Length: 999999999999\r\n\r\n".to_vec(),
            32
        )
        .await,
        Err(HttpError::ResponseTooLarge)
    );
    for invalid in [
        "Content-Length: 1\r\nContent-Length: 2",
        "Content-Length: 1\r\nTransfer-Encoding: chunked",
        "X-Bad : value",
        "Transfer-Encoding: weird",
    ] {
        assert!(reply(
            format!("HTTP/1.1 200 OK\r\n{invalid}\r\nConnection: close\r\n\r\nx").into_bytes(),
            32
        )
        .await
        .is_err());
    }
    for (encoding, compressed) in [
        ("gzip", {
            let mut e = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
            e.write_all(&[b'x'; 4096]).unwrap();
            e.finish().unwrap()
        }),
        ("deflate", {
            let mut e = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
            e.write_all(&[b'x'; 4096]).unwrap();
            e.finish().unwrap()
        }),
    ] {
        let mut raw=format!("HTTP/1.1 200 OK\r\nContent-Encoding: {encoding}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",compressed.len()).into_bytes();
        raw.extend_from_slice(&compressed);
        assert_eq!(reply(raw.clone(), 4096).await.unwrap(), vec![b'x'; 4096]);
        assert_eq!(reply(raw, 32).await, Err(HttpError::ResponseTooLarge));
    }
}
#[tokio::test]
async fn a_slow_body_cannot_refresh_the_original_deadline() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\na")
            .await
            .unwrap();
        tokio::time::sleep(Duration::from_millis(150)).await;
        let _ = stream.write_all(b"bc").await;
    });
    let f = Fixture::new(config(port));
    let (session, _) = f.session(5000);
    let mut input = request(port, HttpMethod::Get);
    input.timeout_millis = Some(60);
    let done = f.provider.start(&session, input).unwrap().await.unwrap();
    assert!(matches!(done.response, Err(HttpError::DeadlineExceeded)));
    drop(done);
    drop(session);
    server.await.unwrap();
    f.clean().await;
}

#[tokio::test]
async fn trailers_and_unsolicited_response_bytes_cannot_change_the_next_result() {
    assert_eq!(reply(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n2\r\nok\r\n0\r\nX-Test: harmless\r\n\r\n".to_vec(),32).await.unwrap(),b"ok");
    assert!(reply(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n0\r\nContent-Length: 999\r\n\r\n".to_vec(),32).await.is_err());
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\naHTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\npoison").await.unwrap();
        let mut byte = [0];
        tokio::select! {
            result=stream.read(&mut byte)=>{if matches!(result,Ok(1)) {let _=stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\ngood").await;}},
            result=listener.accept()=>{let (mut fresh,_)=result.unwrap();read_request(&mut fresh).await;fresh.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\ngood").await.unwrap();},
            ()=tokio::time::sleep(Duration::from_millis(300))=>{}
        }
    });
    let f = Fixture::new(config(port));
    let (session, _) = f.session(5000);
    let first = f
        .provider
        .start(&session, request(port, HttpMethod::Get))
        .unwrap()
        .await
        .unwrap();
    if let Ok(response) = &first.response {
        assert_eq!(response.body(), b"a");
    }
    drop(first);
    let second = f
        .provider
        .start(&session, request(port, HttpMethod::Get))
        .unwrap()
        .await
        .unwrap();
    if let Ok(response) = &second.response {
        assert_eq!(response.body(), b"good");
    }
    drop(second);
    drop(session);
    server.await.unwrap();
    f.clean().await;
}
