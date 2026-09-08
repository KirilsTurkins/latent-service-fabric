use tokio::io::AsyncReadExt;

use super::*;

#[test]
fn accepted_connections_are_bounded_and_incomplete_http2_is_closed_on_shutdown() {
    run(|control| async move {
        let transport = Transport::start_routes(
            configuration(),
            tonic::service::Routes::default(),
            Arc::new(SystemActivationClock),
            control,
        )
        .await
        .unwrap();
        assert!(!transport.handle().snapshot().accepting);
        let mut first = tokio::net::TcpStream::connect(transport.local_addr())
            .await
            .unwrap();
        while transport.handle().snapshot().active_connections != 1 {
            tokio::task::yield_now().await;
        }
        let mut excess = tokio::net::TcpStream::connect(transport.local_addr())
            .await
            .unwrap();
        let mut byte = [0];
        assert_eq!(excess.read(&mut byte).await.unwrap(), 0);
        assert_eq!(transport.handle().snapshot().active_connections, 1);
        assert_eq!(transport.handle().snapshot().rejected_connections, 1);
        let snapshot = transport.shutdown().await.unwrap();
        assert_eq!(snapshot.active_connections, 0);
        assert_eq!(snapshot.active_rpcs, 0);
        assert_eq!(snapshot.active_control_jobs, 0);
        // The peer may receive SETTINGS before it sends a preface. Drain that
        // bounded buffered protocol output before asserting actual TCP closure.
        let mut protocol = [0_u8; 4097];
        let mut used = 0;
        loop {
            match first.read(&mut protocol[used..]).await {
                Ok(0) => break,
                Ok(count) => {
                    used += count;
                    assert!(
                        used < protocol.len(),
                        "unexpected unbounded protocol output"
                    );
                }
                Err(error) if error.kind() == std::io::ErrorKind::ConnectionReset => break,
                Err(error) => panic!("unexpected socket error: {error}"),
            }
        }
    });
}
