use tokio::io::{AsyncReadExt, AsyncWriteExt};

use super::*;

mod lifetime;
mod protocol;
mod support;

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
        assert_peer_closed(&mut first).await;
    });
}

#[test]
fn unauthenticated_deadline_reclaims_silent_and_partial_connection_slots() {
    run(|control| async move {
        let mut config = configuration();
        config.maximum_connections = 2;
        config.unauthenticated_timeout = Duration::from_millis(150);
        let (transport, _) = support::start(config, control).await;
        let handle = transport.handle();

        let mut silent = tokio::net::TcpStream::connect(transport.local_addr())
            .await
            .unwrap();
        let mut partial = tokio::net::TcpStream::connect(transport.local_addr())
            .await
            .unwrap();
        partial
            .write_all(b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r")
            .await
            .unwrap();

        tokio::time::timeout(Duration::from_secs(1), async {
            while handle.snapshot().active_connections != 2 {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();

        let mut excess = tokio::net::TcpStream::connect(transport.local_addr())
            .await
            .unwrap();
        let mut byte = [0];
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(1), excess.read(&mut byte))
                .await
                .unwrap()
                .unwrap(),
            0
        );
        assert_eq!(handle.snapshot().rejected_connections, 1);

        tokio::time::timeout(Duration::from_secs(1), async {
            loop {
                let snapshot = handle.snapshot();
                if snapshot.active_connections == 0
                    && snapshot.expired_unauthenticated_connections == 2
                {
                    break;
                }
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert_peer_closed(&mut silent).await;
        assert_peer_closed(&mut partial).await;

        let mut fresh = support::client(&transport).await;
        assert_eq!(
            support::status(&mut fresh).await.unwrap().activation_id,
            "observed"
        );
        assert_eq!(handle.snapshot().active_connections, 1);
        assert_eq!(handle.snapshot().expired_unauthenticated_connections, 2);
        drop(fresh);

        let snapshot = transport.shutdown().await.unwrap();
        assert_eq!(snapshot.active_connections, 0);
        assert_eq!(snapshot.expired_unauthenticated_connections, 2);
    });
}

async fn assert_peer_closed(stream: &mut tokio::net::TcpStream) {
    // The peer may receive SETTINGS before it sends a preface. Drain that
    // bounded buffered protocol output before asserting actual TCP closure.
    tokio::time::timeout(Duration::from_secs(1), async {
        let mut protocol = [0_u8; 4097];
        let mut used = 0;
        loop {
            match stream.read(&mut protocol[used..]).await {
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
    })
    .await
    .unwrap();
}
