//! Actual new canonical ABI over the same broker, transport and fresh Store.
use super::*;

async fn headers(stream: &mut tokio::net::TcpStream) {
    let mut bytes = Vec::new();
    let mut byte = [0];
    while !bytes.ends_with(b"\r\n\r\n") {
        assert!(bytes.len() < 8192);
        assert_eq!(stream.read(&mut byte).await.unwrap(), 1);
        bytes.push(byte[0]);
    }
    assert!(bytes.starts_with(b"GET /allowed HTTP/1.1\r\n"));
}
async fn returned(f: &Fixture, mode: u32, expected: u32) {
    let (request, control) = f.request("phase-profile", mode);
    let report = tokio::time::timeout(
        Duration::from_secs(3),
        f.backend.invoke_contained(request, &control),
    )
    .await
    .unwrap();
    let GuestOutcome::Returned {
        output,
        consumption,
        ..
    } = report.outcome.unwrap()
    else {
        panic!("the exact typed phase result must cross the component ABI")
    };
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&output).unwrap(),
        serde_json::json!([expected])
    );
    assert_eq!(consumption.outbound_requests, 1);
    let budget = control
        .budget
        .finalize_at(Some(&consumption), Instant::now());
    assert!(budget.violation().is_none());
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    f.idle();
    assert_eq!(f.io.snapshot(), IoSnapshot::default());
}

#[tokio::test]
async fn phase_component_preserves_actual_latin1_and_observed_empty_reason_and_linear_body() {
    for mode in [0, 3] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            headers(&mut stream).await;
            let wire = if mode == 0 {
                &b"HTTP/1.1 200 Caf\xe9\r\nContent-Length: 4\r\nConnection: close\r\n\r\nabcd"[..]
            } else {
                &b"HTTP/1.1 200 \r\nContent-Length: 0\r\nConnection: close\r\n\r\n"[..]
            };
            stream.write_all(wire).await.unwrap();
        });
        let f = Fixture::phase_timing(port, "/allowed").await;
        returned(&f, mode, 200).await;
        server.await.unwrap();
        assert!(f
            .pools
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap()
            .is_clean());
    }
}

#[tokio::test]
async fn phase_component_header_timeout_returns_uncertain_typed_error_and_closes_transport() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        headers(&mut stream).await;
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
    let f = Fixture::phase_timing(port, "/allowed").await;
    returned(&f, 1, 2021).await;
    server.await.unwrap();
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[tokio::test]
async fn phase_component_body_timeout_reclaims_held_chunk_at_original_store_retirement() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        headers(&mut stream).await;
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
    });
    let f = Fixture::phase_timing(port, "/allowed").await;
    returned(&f, 2, 3020).await;
    server.await.unwrap();
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}
