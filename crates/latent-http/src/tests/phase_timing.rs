use super::*;
use latent_capabilities::broker::streaming_http::{
    HttpPhaseError as Phase, StreamingHttpError as Stream, StreamingHttpInvoker,
    StreamingHttpRequest,
};

fn fixture(port: u16) -> Fixture {
    let mut config = config(port);
    config.destinations[0].redirect_destinations.clear();
    Fixture::phase_timing(
        config,
        HttpStreamLimits {
            maximum_input_bytes: 1024,
            maximum_output_bytes: 1024,
            maximum_chunk_bytes: 4,
            maximum_outstanding_chunks: 2,
        },
    )
}
fn input(port: u16) -> StreamingHttpRequest {
    StreamingHttpRequest {
        metadata: request(port, HttpMethod::Get),
        body_length: Some(0),
    }
}

#[tokio::test]
async fn old_streaming_profile_rejects_nonzero_phase_contract_before_contact() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let mut config = config(port);
    config.destinations[0].redirect_destinations.clear();
    let f = Fixture::streaming(
        config,
        HttpStreamLimits {
            maximum_input_bytes: 1024,
            maximum_output_bytes: 1024,
            maximum_chunk_bytes: 4,
            maximum_outstanding_chunks: 2,
        },
    );
    let (session, _) = f.session(5000);
    assert!(matches!(
        f.streaming
            .as_ref()
            .unwrap()
            .start_with_connect_timeout(&session, input(port), Some(50)),
        Err(Phase::Unsupported)
    ));
    assert!(
        tokio::time::timeout(Duration::from_millis(30), listener.accept())
            .await
            .is_err()
    );
    drop(session);
    f.clean().await;
}

#[tokio::test]
async fn connect_phase_waits_for_real_tls_and_retires_the_stalled_transport() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = [0; 4096];
        assert!(stream.read(&mut bytes).await.unwrap() > 0);
        tokio::time::timeout(Duration::from_secs(2), async {
            let mut total = 0;
            loop {
                let count = stream.read(&mut bytes).await.unwrap();
                if count == 0 {
                    break;
                }
                total += count;
                assert!(
                    total <= 16384,
                    "no application payload may reach the stalled TLS peer"
                );
            }
        })
        .await
        .unwrap();
    });
    let mut config = config(port);
    config.destinations[0].redirect_destinations.clear();
    config.destinations[0].origin.scheme = "https".into();
    config.extra_roots.push(super::tls::certificate().0);
    let f = Fixture::phase_timing(
        config,
        HttpStreamLimits {
            maximum_input_bytes: 1024,
            maximum_output_bytes: 1024,
            maximum_chunk_bytes: 4,
            maximum_outstanding_chunks: 2,
        },
    );
    let (session, _) = f.session(5000);
    let mut request = input(port);
    request.metadata.url = format!("https://localhost:{port}/allowed");
    let opening = f
        .streaming
        .as_ref()
        .unwrap()
        .start_with_connect_timeout(&session, request, Some(200))
        .unwrap();
    assert!(matches!(opening.await, Err(Phase::ConnectTimeout)));
    drop(session);
    server.await.unwrap();
    f.clean().await;
}

#[tokio::test]
async fn connected_transport_does_not_charge_later_response_headers_to_connect_timer() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        tokio::time::sleep(Duration::from_millis(350)).await;
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            .await
            .unwrap();
    });
    let f = fixture(port);
    let (session, _) = f.session(5000);
    let upload = f
        .streaming
        .as_ref()
        .unwrap()
        .start_with_connect_timeout(&session, input(port), Some(200))
        .unwrap()
        .await
        .unwrap();
    let mut body = upload.finish_with_read_timeout(Some(1200)).await.unwrap();
    assert_eq!(body.head().status(), 200);
    assert!(body
        .read_with_timeout(4, Some(200))
        .await
        .unwrap()
        .is_none());
    drop(body);
    drop(session);
    server.await.unwrap();
    f.clean().await;
}

#[tokio::test]
async fn header_phase_timeout_keeps_written_request_uncertain_and_never_replays() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        let mut byte = [0];
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), stream.read(&mut byte))
                .await
                .unwrap()
                .unwrap(),
            0
        );
        assert!(
            tokio::time::timeout(Duration::from_millis(30), listener.accept())
                .await
                .is_err()
        );
    });
    let f = fixture(port);
    let (session, _) = f.session(5000);
    let observer = session.observer();
    let upload = f
        .streaming
        .as_ref()
        .unwrap()
        .start_with_connect_timeout(&session, input(port), Some(200))
        .unwrap()
        .await
        .unwrap();
    assert!(matches!(
        upload.finish_with_read_timeout(Some(100)).await,
        Err(Phase::ReadTimeout {
            external_completion_uncertain: true
        })
    ));
    drop(session);
    assert!(observer.is_quiescent());
    server.await.unwrap();
    f.clean().await;
}

#[tokio::test]
async fn body_phase_timeout_closes_io_while_prior_chunks_keep_their_original_charge() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (closed, physically_closed) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nabcd")
            .await
            .unwrap();
        let mut byte = [0];
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), stream.read(&mut byte))
                .await
                .unwrap()
                .unwrap(),
            0
        );
        closed.send(()).unwrap();
    });
    let f = fixture(port);
    let (session, control) = f.session(5000);
    let observer = session.observer();
    let upload = f
        .streaming
        .as_ref()
        .unwrap()
        .start_with_connect_timeout(&session, input(port), Some(200))
        .unwrap()
        .await
        .unwrap();
    let mut body = upload.finish_with_read_timeout(Some(1000)).await.unwrap();
    let chunk = body.read_with_timeout(4, Some(500)).await.unwrap().unwrap();
    assert_eq!(chunk.bytes(), b"abcd");
    for _ in 0..2 {
        assert!(matches!(
            body.read_with_timeout(4, Some(100)).await,
            Err(Phase::ReadTimeout {
                external_completion_uncertain: false
            })
        ));
    }
    // Observe the peer's actual EOF while both the failed body and its prior
    // chunk are still live. Dropping either here must not create this witness.
    tokio::time::timeout(Duration::from_secs(2), physically_closed)
        .await
        .unwrap()
        .unwrap();
    assert!(!observer.is_quiescent());
    assert_eq!(chunk.bytes(), b"abcd");
    control.probe.0.store(true, Ordering::Release);
    assert!(matches!(
        body.read_with_timeout(4, Some(100)).await,
        Err(Phase::Http(Stream::Http(HttpError::Cancelled)))
    ));
    drop(body);
    drop(session);
    assert!(!observer.is_quiescent());
    assert_eq!(chunk.bytes(), b"abcd");
    drop(chunk);
    assert!(observer.is_quiescent());
    server.await.unwrap();
    f.clean().await;
}

#[tokio::test]
async fn original_root_deadline_and_cancellation_are_never_reported_as_phase_timeouts() {
    for cancelled in [false, true] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let (sent, received) = tokio::sync::oneshot::channel();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            read_request(&mut stream).await;
            sent.send(()).unwrap();
            let mut byte = [0];
            assert_eq!(
                tokio::time::timeout(Duration::from_secs(2), stream.read(&mut byte))
                    .await
                    .unwrap()
                    .unwrap(),
                0
            );
        });
        let f = fixture(port);
        let (session, control) = f.session(if cancelled { 5000 } else { 500 });
        let observer = session.observer();
        let upload = f
            .streaming
            .as_ref()
            .unwrap()
            .start_with_connect_timeout(&session, input(port), Some(1000))
            .unwrap()
            .await
            .unwrap();
        let mut response = upload.finish_with_read_timeout(Some(1000));
        tokio::select! {
            _ = &mut response => panic!("the peer has not sent response headers"),
            _ = received => {},
        }
        if cancelled {
            control.probe.0.store(true, Ordering::Release);
        }
        let expected = if cancelled {
            HttpError::Cancelled
        } else {
            HttpError::DeadlineExceeded
        };
        assert_eq!(
            response.await.err(),
            Some(Phase::Http(Stream::Http(expected)))
        );
        drop(session);
        assert!(observer.is_quiescent());
        server.await.unwrap();
        f.clean().await;
    }
}
