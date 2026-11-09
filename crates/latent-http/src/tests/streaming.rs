use super::*;
use latent_capabilities::broker::streaming_http::{
    StreamingHttpError as Error, StreamingHttpInvoker, StreamingHttpRequest,
};
fn fixture(port: u16, chunks: usize) -> Fixture {
    let mut config = config(port);
    config.destinations[0].redirect_destinations.clear();
    Fixture::streaming(
        config,
        HttpStreamLimits {
            maximum_input_bytes: 1024,
            maximum_output_bytes: 1024,
            maximum_chunk_bytes: 4,
            maximum_outstanding_chunks: chunks,
        },
    )
}
fn input(port: u16, length: Option<u64>) -> StreamingHttpRequest {
    StreamingHttpRequest {
        metadata: request(port, HttpMethod::Post),
        body_length: length,
    }
}
#[tokio::test]
async fn requested_read_maximum_is_limited_by_the_original_provider_window() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\nConnection: close\r\n\r\nabcdefgh")
            .await
            .unwrap();
    });
    let f = fixture(port, 1);
    let (session, _) = f.session(5000);
    let observer = session.observer();
    let upload = f
        .streaming
        .as_ref()
        .unwrap()
        .start(&session, input(port, Some(0)))
        .unwrap()
        .await
        .unwrap();
    let mut body = upload.finish().await.unwrap();

    // A zero maximum is still rejected before verified EOF and does not
    // poison the response. The configured four-byte window remains owned.
    assert!(body.read(0).await.is_err());
    let first = body.read(4096).await.unwrap().unwrap();
    assert!(!first.bytes().is_empty() && first.bytes().len() <= 4);
    let retained = f.io.snapshot();
    assert!(matches!(
        body.read(4096).await,
        Err(Error::Http(HttpError::BudgetExhausted))
    ));
    assert_eq!(f.io.snapshot(), retained);
    let mut output = first.bytes().to_vec();
    drop(first);
    while let Some(chunk) = body.read(4096).await.unwrap() {
        assert!(!chunk.bytes().is_empty() && chunk.bytes().len() <= 4);
        output.extend_from_slice(chunk.bytes());
    }
    assert_eq!(output, b"abcdefgh");
    assert!(body.read(4096).await.unwrap().is_none());
    assert!(body.read(0).await.unwrap().is_none());
    drop(body);
    drop(session);
    assert!(observer.is_quiescent());
    server.await.unwrap();
    f.clean().await;
}

#[tokio::test]
async fn requested_read_maximum_does_not_expand_total_response_budget() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (send_more, wait) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n4\r\nabcd\r\n")
            .await
            .unwrap();
        wait.await.unwrap();
        stream.write_all(b"4\r\nefgh\r\n0\r\n\r\n").await.unwrap();
    });
    let mut config = config(port);
    config.destinations[0].redirect_destinations.clear();
    let f = Fixture::streaming(
        config,
        HttpStreamLimits {
            maximum_input_bytes: 4,
            maximum_output_bytes: 4,
            maximum_chunk_bytes: 4,
            maximum_outstanding_chunks: 1,
        },
    );
    let (session, _) = f.session(5000);
    let upload = f
        .streaming
        .as_ref()
        .unwrap()
        .start(&session, input(port, Some(0)))
        .unwrap()
        .await
        .unwrap();
    let mut body = upload.finish().await.unwrap();
    let mut output = Vec::new();
    while output.len() < 4 {
        let chunk = body.read(4096).await.unwrap().unwrap();
        assert!(!chunk.bytes().is_empty() && chunk.bytes().len() <= 4);
        output.extend_from_slice(chunk.bytes());
    }
    assert_eq!(output, b"abcd");
    send_more.send(()).unwrap();
    assert!(matches!(
        body.read(4096).await,
        Err(Error::Http(HttpError::ResponseTooLarge))
    ));
    assert!(matches!(
        body.read(4096).await,
        Err(Error::Http(HttpError::ResponseTooLarge))
    ));
    drop(body);
    drop(session);
    server.await.unwrap();
    f.clean().await;
}

#[tokio::test]
async fn first_chunk_precedes_complete_body_and_retained_chunks_keep_ownership() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (allow, wait) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nabcd")
            .await
            .unwrap();
        wait.await.unwrap();
        let mut b = [0];
        assert_eq!(stream.read(&mut b).await.unwrap(), 0);
    });
    let f = fixture(port, 1);
    let (session, _) = f.session(5000);
    let observer = session.observer();
    let upload = f
        .streaming
        .as_ref()
        .unwrap()
        .start(&session, input(port, Some(0)))
        .unwrap()
        .await
        .unwrap();
    let mut body = upload.finish().await.unwrap();
    assert_eq!(body.head().status(), 200);
    let chunk = tokio::time::timeout(Duration::from_millis(500), body.read(4))
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(chunk.bytes(), b"abcd");
    let retained = f.io.snapshot();
    assert!(matches!(
        body.read(4).await,
        Err(Error::Http(HttpError::BudgetExhausted))
    ));
    assert_eq!(f.io.snapshot(), retained);
    drop(body);
    drop(session);
    assert!(!observer.is_quiescent());
    assert_eq!(chunk.bytes(), b"abcd");
    allow.send(()).unwrap();
    server.await.unwrap();
    drop(chunk);
    assert!(observer.is_quiescent());
    f.clean().await;
}
#[tokio::test]
async fn upload_and_download_cross_many_windows_without_whole_body_buffering() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let wire = read_request(&mut stream).await;
        assert!(wire.ends_with(b"abcdefghijklmnop"));
        assert!(String::from_utf8(wire)
            .unwrap()
            .contains("accept-encoding: identity"));
        stream.write_all(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n10\r\nabcdefghijklmnop\r\n0\r\nx-check: done\r\n\r\n").await.unwrap();
        let mut b = [0];
        let _ = stream.read(&mut b).await;
    });
    let f = fixture(port, 1);
    let (session, _) = f.session(5000);
    let mut upload = f
        .streaming
        .as_ref()
        .unwrap()
        .start(&session, input(port, Some(16)))
        .unwrap()
        .await
        .unwrap();
    for part in b"abcdefghijklmnop".chunks(4) {
        upload.write(part.to_vec()).await.unwrap();
    }
    let mut body = upload.finish().await.unwrap();
    assert!(matches!(body.trailers(), Err(Error::InvalidState)));
    let mut output = Vec::new();
    while let Some(chunk) = body.read(4).await.unwrap() {
        output.extend_from_slice(chunk.bytes());
    }
    assert_eq!(output, b"abcdefghijklmnop");
    assert_eq!(
        body.trailers().unwrap().iter().collect::<Vec<_>>(),
        [("x-check", "done")]
    );
    assert!(body.read(4).await.unwrap().is_none());
    drop(body);
    drop(session);
    f.clean().await;
    server.await.unwrap();
}
#[tokio::test]
async fn truncated_body_is_terminal_and_never_verified_eof() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nabcd")
            .await
            .unwrap();
    });
    let f = fixture(port, 1);
    let (session, _) = f.session(5000);
    let upload = f
        .streaming
        .as_ref()
        .unwrap()
        .start(&session, input(port, Some(0)))
        .unwrap()
        .await
        .unwrap();
    let mut body = upload.finish().await.unwrap();
    assert_eq!(body.read(4).await.unwrap().unwrap().bytes(), b"abcd");
    let error = body.read(4).await.err().unwrap();
    assert!(matches!(
        error,
        Error::UnexpectedEof | Error::Http(HttpError::ConnectionFailed)
    ));
    assert_eq!(body.read(4).await.err(), Some(error));
    assert!(body.trailers().is_err());
    drop(body);
    drop(session);
    server.await.unwrap();
    f.clean().await;
}
#[tokio::test]
async fn encoding_and_upgrade_are_rejected_and_redirect_is_an_ordinary_response() {
    for (status, extra, expected) in [
        (
            200,
            "Content-Encoding: gzip\r\n",
            Some(Error::UnsupportedEncoding),
        ),
        (
            101,
            "Upgrade: websocket\r\n",
            Some(Error::Http(HttpError::ConnectionFailed)),
        ),
        (302, "Location: http://example.invalid/\r\n", None),
    ] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            read_request(&mut stream).await;
            stream.write_all(format!("HTTP/1.1 {status} Test\r\n{extra}Content-Length: 0\r\nConnection: close\r\n\r\n").as_bytes()).await.unwrap();
        });
        let f = fixture(port, 1);
        let (session, _) = f.session(5000);
        let upload = f
            .streaming
            .as_ref()
            .unwrap()
            .start(&session, input(port, Some(0)))
            .unwrap()
            .await
            .unwrap();
        match upload.finish().await {
            Ok(mut body) => {
                assert!(expected.is_none());
                assert_eq!(body.head().status(), 302);
                assert!(body.read(4).await.unwrap().is_none());
            }
            Err(error) => assert_eq!(Some(error), expected),
        }
        drop(session);
        server.await.unwrap();
        f.clean().await;
    }
}
#[tokio::test]
async fn bodyless_responses_preserve_encoding_metadata_without_body_budget() {
    for (method, status, length) in [
        (HttpMethod::Head, 200, "Content-Length: 4096\r\n"),
        (HttpMethod::Get, 204, ""),
        (HttpMethod::Get, 304, "Content-Length: 4096\r\n"),
    ] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            read_request(&mut stream).await;
            stream
                .write_all(format!("HTTP/1.1 {status} Test\r\nContent-Encoding: gzip\r\n{length}Connection: close\r\n\r\n").as_bytes())
                .await
                .unwrap();
        });
        let f = fixture(port, 1);
        let (session, _) = f.session(5000);
        let observer = session.observer();
        let upload = f
            .streaming
            .as_ref()
            .unwrap()
            .start(
                &session,
                StreamingHttpRequest {
                    metadata: request(port, method),
                    body_length: Some(0),
                },
            )
            .unwrap()
            .await
            .unwrap();
        let mut body = upload.finish().await.unwrap();
        assert_eq!(body.head().status(), status);
        assert!(body
            .head()
            .headers()
            .any(|field| field == ("content-encoding", "gzip")));
        assert!(body.read(4).await.unwrap().is_none());
        assert_eq!(body.trailers().unwrap().iter().count(), 0);
        assert!(body.read(4).await.unwrap().is_none());
        drop(body);
        drop(session);
        assert!(observer.is_quiescent());
        assert_eq!(
            f.io.snapshot(),
            latent_capabilities::broker::io::IoSnapshot::default()
        );
        server.await.unwrap();
        f.clean().await;
    }
}
#[tokio::test]
async fn encoded_entity_responses_remain_unsupported_even_with_zero_length() {
    for (status, encoding) in [(200, "gzip"), (302, "br")] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            read_request(&mut stream).await;
            stream
                .write_all(format!("HTTP/1.1 {status} Test\r\nContent-Encoding: {encoding}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").as_bytes())
                .await
                .unwrap();
        });
        let f = fixture(port, 1);
        let (session, _) = f.session(5000);
        let observer = session.observer();
        let upload = f
            .streaming
            .as_ref()
            .unwrap()
            .start(
                &session,
                StreamingHttpRequest {
                    metadata: request(port, HttpMethod::Get),
                    body_length: Some(0),
                },
            )
            .unwrap()
            .await
            .unwrap();
        assert!(matches!(
            upload.finish().await,
            Err(Error::UnsupportedEncoding)
        ));
        drop(session);
        assert!(observer.is_quiescent());
        server.await.unwrap();
        f.clean().await;
    }
}
#[tokio::test]
async fn original_deadline_closes_a_stalled_response_without_refunding_held_chunks() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nabcd")
            .await
            .unwrap();
        let mut b = [0];
        assert_eq!(stream.read(&mut b).await.unwrap(), 0);
    });
    let f = fixture(port, 2);
    let (session, _) = f.session(150);
    let observer = session.observer();
    let upload = f
        .streaming
        .as_ref()
        .unwrap()
        .start(&session, input(port, Some(0)))
        .unwrap()
        .await
        .unwrap();
    let mut body = upload.finish().await.unwrap();
    let chunk = body.read(4).await.unwrap().unwrap();
    assert!(matches!(
        body.read(4).await,
        Err(Error::Http(HttpError::DeadlineExceeded))
    ));
    drop(body);
    drop(session);
    assert!(!observer.is_quiescent());
    drop(chunk);
    assert!(observer.is_quiescent());
    server.await.unwrap();
    f.clean().await;
}

#[tokio::test]
async fn completed_stream_reuses_socket_without_retaining_an_activation_cycle() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        for _ in 0..2 {
            read_request(&mut stream).await;
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nabcdefgh")
                .await
                .unwrap();
        }
        let mut b = [0];
        assert_eq!(stream.read(&mut b).await.unwrap(), 0);
    });
    let f = fixture(port, 1);
    for _ in 0..2 {
        let (session, _) = f.session(5000);
        let observer = session.observer();
        let upload = f
            .streaming
            .as_ref()
            .unwrap()
            .start(&session, input(port, Some(0)))
            .unwrap()
            .await
            .unwrap();
        let mut body = upload.finish().await.unwrap();
        while let Some(chunk) = body.read(4).await.unwrap() {
            assert_eq!(chunk.bytes().len(), 4);
        }
        drop(body);
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
async fn unknown_length_upload_uses_finite_chunked_framing_and_cannot_reset_its_total() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let headers = read_request(&mut stream).await;
        assert!(String::from_utf8(headers)
            .unwrap()
            .contains("transfer-encoding: chunked"));
        let mut chunked = vec![0; 23];
        stream.read_exact(&mut chunked).await.unwrap();
        assert_eq!(chunked, b"4\r\nabcd\r\n4\r\nefgh\r\n0\r\n\r\n");
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            .await
            .unwrap();
    });
    let mut config = config(port);
    config.destinations[0].redirect_destinations.clear();
    let f = Fixture::streaming(
        config,
        HttpStreamLimits {
            maximum_input_bytes: 8,
            maximum_output_bytes: 8,
            maximum_chunk_bytes: 4,
            maximum_outstanding_chunks: 1,
        },
    );
    let (session, _) = f.session(5000);
    let mut upload = f
        .streaming
        .as_ref()
        .unwrap()
        .start(&session, input(port, None))
        .unwrap()
        .await
        .unwrap();
    upload.write(b"abcd".to_vec()).await.unwrap();
    upload.write(b"efgh".to_vec()).await.unwrap();
    assert!(matches!(
        upload.write(vec![b'x']).await,
        Err(Error::Http(HttpError::BudgetExhausted))
    ));
    let mut body = upload.finish().await.unwrap();
    assert!(body.read(4).await.unwrap().is_none());
    drop(body);
    drop(session);
    server.await.unwrap();
    f.clean().await;
}
#[tokio::test]
async fn finite_upload_window_stalls_without_an_unbounded_producer_queue() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (accepted, connected) = tokio::sync::oneshot::channel();
    let (done, wait) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        accepted.send(()).unwrap();
        wait.await.unwrap();
        let mut bytes = [0; 4096];
        let mut received = 0;
        loop {
            match stream.read(&mut bytes).await {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    received += n;
                    assert!(received < 2 * 1024 * 1024);
                }
            }
        }
    });
    let mut config = config(port);
    config.destinations[0].redirect_destinations.clear();
    let f = Fixture::streaming(
        config,
        HttpStreamLimits {
            maximum_input_bytes: 1024 * 1024,
            maximum_output_bytes: 1024,
            maximum_chunk_bytes: 4096,
            maximum_outstanding_chunks: 1,
        },
    );
    let (session, _) = f.session(200);
    let mut upload = f
        .streaming
        .as_ref()
        .unwrap()
        .start(&session, input(port, Some(1024 * 1024)))
        .unwrap()
        .await
        .unwrap();
    connected.await.unwrap();
    let baseline = f.io.snapshot();
    let mut saw_wait = false;
    let result = {
        let sending = async move {
            for _ in 0..256 {
                upload.write(vec![b'x'; 4096]).await?;
            }
            Ok::<_, Error>(())
        };
        tokio::pin!(sending);
        loop {
            tokio::select! {result=&mut sending=>break result,()=tokio::time::sleep(Duration::from_millis(10))=>{saw_wait=true;let now=f.io.snapshot();assert!(now.staged_bytes<=baseline.staged_bytes+4096);assert!(now.buffers<=baseline.buffers+1);}}
        }
    };
    assert!(saw_wait);
    assert!(matches!(result, Err(Error::Http(HttpError::Uncertain))));
    drop(session);
    done.send(()).unwrap();
    server.await.unwrap();
    f.clean().await;
}

// The gate is scoped to this fixture's actual provider and pauses only after
// Sender::send has accepted the original chunk. It does not claim a kernel send.
async fn queued_upload_write_case(cancel: bool) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut peer, _) = listener.accept().await.unwrap();
        if cancel {
            let mut received = Vec::new();
            tokio::time::timeout(Duration::from_secs(3), peer.read_to_end(&mut received))
                .await
                .expect("cancelled upload must retire its original connection")
                .unwrap();
            assert!(!received.windows(4).any(|window| window == b"abcd"));
        } else {
            let request = read_request(&mut peer).await;
            assert!(request.ends_with(b"abcd"));
            peer.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                .await
                .unwrap();
        }
    });
    let f = fixture(port, 1);
    let (session, control) = f.session(5000);
    let observer = session.observer();
    let mut upload = f
        .streaming
        .as_ref()
        .unwrap()
        .start(&session, input(port, Some(4)))
        .unwrap()
        .await
        .unwrap();
    let before = f.io.snapshot();
    let native_before = control.budget.host_memory_bytes();
    let (entered, entered_rx) = tokio::sync::oneshot::channel();
    let (release, release_rx) = tokio::sync::oneshot::channel();
    assert!(f
        .provider
        .inner
        .write_gate
        .lock()
        .unwrap()
        .replace(crate::provider::WriteGate {
            entered,
            release: release_rx
        })
        .is_none());
    let mut writing = upload.write(b"abcd".to_vec());
    tokio::time::timeout(Duration::from_secs(2), async {
        tokio::select! {
            result = &mut writing => panic!("write finished before the queued barrier: {result:?}"),
            entered = entered_rx => entered.expect("original chunk must be queued"),
        }
    })
    .await
    .expect("write did not reach its queued barrier");
    let queued = f.io.snapshot();
    assert!(queued.staged_bytes >= before.staged_bytes + 4);
    assert!(queued.buffers > before.buffers);
    // This is the same activation's admitted write-future backing, not a
    // separate claim that its already-lifted input Vec has a native owner.
    assert!(control.budget.host_memory_bytes() > native_before);
    assert!(!observer.is_quiescent());
    assert_eq!(f.pools.snapshot().unwrap().active_connections, 1);
    if cancel {
        // Dropping the sole gate sender on any test unwind also releases it.
        drop(writing);
        drop(release);
        assert!(matches!(
            upload.write(b"x".to_vec()).await,
            Err(Error::InvalidState)
        ));
        assert!(matches!(upload.finish().await, Err(Error::InvalidState)));
        assert_eq!(f.pools.snapshot().unwrap().idle_connections, 0);
    } else {
        release.send(()).unwrap();
        writing.await.unwrap();
        let mut body = upload.finish().await.unwrap();
        assert_eq!(body.head().status(), 200);
        assert!(body.read(4).await.unwrap().is_none());
        drop(body);
    }
    drop(session);
    assert!(observer.is_quiescent());
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    // No claim is made about a separate kernel or remote application rollback.
    drop(control);
    tokio::time::timeout(Duration::from_secs(3), server)
        .await
        .expect("peer did not retire")
        .unwrap();
    f.clean().await;
}

#[tokio::test]
async fn queued_upload_cancel_retires_original_connection_and_disallows_reuse() {
    queued_upload_write_case(true).await;
}

#[tokio::test]
async fn queued_upload_release_completes_with_the_same_provider() {
    queued_upload_write_case(false).await;
}
