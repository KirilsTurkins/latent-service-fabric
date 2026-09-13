use super::support::{client, start, status, until};
use super::*;

#[test]
fn completed_http2_without_requests_expires_while_idle() {
    run(|control| async move {
        let mut config = configuration();
        config.unauthenticated_timeout = Duration::from_millis(300);
        let (transport, _) = start(config, control).await;
        let handle = transport.handle();
        let mut peer = handshake(&transport).await;
        assert_peer_closed(&mut peer).await;
        until(|| handle.snapshot().active_connections == 0).await;
        assert_eq!(handle.snapshot().expired_unauthenticated_connections, 1);
        let mut fresh = client(&transport).await;
        status(&mut fresh).await.unwrap();
        drop(fresh);
        transport.shutdown().await.unwrap();
    });
}

#[test]
fn completed_http2_and_ping_traffic_do_not_authenticate_a_connection() {
    run(|control| async move {
        let mut config = configuration();
        config.unauthenticated_timeout = Duration::from_millis(400);
        let (transport, _) = start(config, control).await;
        let handle = transport.handle();
        let mut peer = handshake(&transport).await;
        let mut acknowledged = 0;
        // Finite real protocol traffic continues until the original deadline;
        // neither a SETTINGS handshake nor PING acknowledgement grants auth.
        tokio::time::timeout(Duration::from_millis(750), async {
            for sequence in 0_u64..96 {
                let mut ping = vec![0, 0, 8, 6, 0, 0, 0, 0, 0];
                ping.extend_from_slice(&sequence.to_be_bytes());
                if peer.write_all(&ping).await.is_err() {
                    break;
                }
                match frame(&mut peer).await {
                    Ok((6, 1, bytes)) => {
                        assert_eq!(bytes, sequence.to_be_bytes());
                        acknowledged += 1;
                    }
                    Err(_) => break,
                    other => panic!("unexpected HTTP/2 response: {other:?}"),
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
            until(|| handle.snapshot().active_connections == 0).await;
        })
        .await
        .expect("PING traffic must not renew the original connection deadline");
        assert!(acknowledged >= 2);
        assert_eq!(handle.snapshot().expired_unauthenticated_connections, 1);
        assert_peer_closed(&mut peer).await;
        let mut fresh = client(&transport).await;
        status(&mut fresh).await.unwrap();
        drop(fresh);
        transport.shutdown().await.unwrap();
    });
}

#[test]
fn rejected_authentication_cannot_renew_connection_residency() {
    run(|control| async move {
        let mut config = configuration();
        config.unauthenticated_timeout = Duration::from_millis(400);
        let (transport, _) = start(config, control).await;
        let handle = transport.handle();
        let mut invalid = client(&transport).await;
        for _ in 0..3 {
            let error = invalid
                .get_activation(support::proto::GetActivationRequest {
                    activation_id: "observed".to_owned(),
                })
                .await
                .unwrap_err();
            assert_eq!(error.code(), tonic::Code::Unauthenticated);
            assert_eq!(handle.snapshot().active_rpcs, 0);
            tokio::time::sleep(Duration::from_millis(70)).await;
        }
        until(|| handle.snapshot().active_connections == 0).await;
        assert_eq!(handle.snapshot().expired_unauthenticated_connections, 1);
        drop(invalid);
        let mut fresh = client(&transport).await;
        status(&mut fresh).await.unwrap();
        drop(fresh);
        transport.shutdown().await.unwrap();
    });
}

async fn handshake(transport: &Transport) -> tokio::net::TcpStream {
    let mut peer = tokio::net::TcpStream::connect(transport.local_addr())
        .await
        .unwrap();
    peer.write_all(b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n")
        .await
        .unwrap();
    peer.write_all(&[0, 0, 0, 4, 0, 0, 0, 0, 0]).await.unwrap();
    let mut settings = false;
    let mut acknowledged = false;
    for _ in 0..4 {
        match frame(&mut peer).await.unwrap() {
            (4, 0, _) => {
                settings = true;
                peer.write_all(&[0, 0, 0, 4, 1, 0, 0, 0, 0]).await.unwrap();
            }
            (4, 1, bytes) => {
                assert!(bytes.is_empty());
                acknowledged = true;
            }
            (8, _, _) => {}
            other => panic!("unexpected handshake frame: {other:?}"),
        }
        if settings && acknowledged {
            return peer;
        }
    }
    panic!("HTTP/2 handshake did not complete within the frame allowance");
}

async fn frame(peer: &mut tokio::net::TcpStream) -> std::io::Result<(u8, u8, Vec<u8>)> {
    let mut header = [0; 9];
    peer.read_exact(&mut header).await?;
    let size = u32::from_be_bytes([0, header[0], header[1], header[2]]) as usize;
    assert!(size <= 1024, "unexpected protocol fixture allocation");
    let mut bytes = vec![0; size];
    peer.read_exact(&mut bytes).await?;
    Ok((header[3], header[4], bytes))
}
