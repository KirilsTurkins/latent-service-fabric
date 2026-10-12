// Appended only to a source-labeled private copy of the actual provider tests.
// Shipped TLS installation remains refused; this does not grant a capability.
#[tokio::test]
async fn malformed_truncated_and_oversized_tls_wire_retire_original_physical_owners() {
    let vectors = [
        vec![255, 3, 3, 0, 0],
        vec![22, 3, 3, 255, 255],
        vec![22, 3, 3, 0, 16, 2],
        vec![22, 3, 3, 0, 4, 2, 255, 255, 255],
        {
            let mut value = vec![22, 3, 3, 0, 132];
            for _ in 0..33 { value.extend([2, 0, 0, 0]); }
            value
        },
    ];
    for wire in vectors {
        let peer = Peer::new().await;
        let fixture = Fixture::new(peer.config());
        let server = tokio::spawn(async move {
            let (mut socket, _) = peer.listener.accept().await.unwrap();
            let mut client_hello = [0; 4096];
            assert!(socket.read(&mut client_hello).await.unwrap() > 0);
            socket.write_all(&wire).await.unwrap();
            socket.shutdown().await.unwrap();
            let mut remaining = Vec::new();
            match socket.read_to_end(&mut remaining).await {
                Ok(_) => {},
                Err(error) => assert!(matches!(error.kind(),
                    std::io::ErrorKind::ConnectionReset | std::io::ErrorKind::BrokenPipe)),
            }
        });
        let (session, control) = fixture.session(2000);
        let failure = fixture.provider.start(&session, request(&fixture)).unwrap().await.err().unwrap();
        assert!(matches!(failure.code, StreamErrorCode::TlsFailed | StreamErrorCode::Exhausted));
        tokio::time::timeout(Duration::from_secs(2), server).await.unwrap().unwrap();
        assert_eq!(fixture.provider.usage().unwrap().connections, 0);
        assert_eq!(control.budget.host_memory_bytes(), 0);
        drop(session);
        fixture.clean().await;
    }
}
