use std::sync::atomic::Ordering;

use super::support::{self, authenticated, client, invocation, start, status, until};
use super::*;

#[test]
fn every_rpc_authenticates_after_the_first_connection_deadline() {
    run(|control| async move {
        let mut config = configuration();
        config.unauthenticated_timeout = Duration::from_millis(150);
        let (transport, _) = start(config, control).await;
        let mut client = client(&transport).await;
        status(&mut client).await.unwrap();
        tokio::time::sleep(Duration::from_millis(200)).await;
        // This second valid RPC caught the original first-auth marker bug:
        // the expired initial deadline must not reject an established client.
        status(&mut client).await.unwrap();
        let mut invalid = authenticated(support::proto::GetActivationRequest {
            activation_id: "observed".to_owned(),
        });
        invalid
            .metadata_mut()
            .insert("authorization", "Bearer wrong-token".parse().unwrap());
        assert_eq!(
            client.get_activation(invalid).await.unwrap_err().code(),
            tonic::Code::Unauthenticated
        );
        status(&mut client).await.unwrap();
        assert_eq!(transport.handle().snapshot().active_connections, 1);
        assert_eq!(
            transport
                .handle()
                .snapshot()
                .expired_unauthenticated_connections,
            0
        );
        drop(client);
        assert_eq!(transport.shutdown().await.unwrap().active_rpcs, 0);
    });
}

fn aging_configuration() -> TransportConfig {
    let mut config = configuration();
    config.unauthenticated_timeout = Duration::from_millis(150);
    config.maximum_connection_age = Duration::from_millis(350);
    config.connection_drain_timeout = Duration::from_millis(700);
    config
}

#[test]
fn age_drain_rejects_new_calls_but_allows_an_owned_call_to_finish() {
    run(|control| async move {
        let (transport, runtime) = start(aging_configuration(), control).await;
        let handle = transport.handle();
        let mut client = client(&transport).await;
        let mut invoking = client.clone();
        let pending = tokio::spawn(async move { invoking.invoke(invocation()).await });
        until(|| runtime.started.load(Ordering::Acquire) == 1).await;
        status(&mut client).await.unwrap();
        client
            .cancel(authenticated(support::proto::CancelRequest {
                activation_id: "connection-owned".to_owned(),
                reason: "transport-control-probe".to_owned(),
            }))
            .await
            .unwrap();
        // Observe the real admission transition, not a guessed sleep duration.
        loop {
            match status(&mut client).await {
                Ok(_) => tokio::time::sleep(Duration::from_millis(5)).await,
                Err(error) => {
                    assert_eq!(error.code(), tonic::Code::Unavailable);
                    assert!(error.message().contains("draining"));
                    break;
                }
            }
        }
        assert_eq!(handle.snapshot().active_connections, 1);
        assert_eq!(handle.snapshot().active_rpcs, 1);
        assert_eq!(runtime.dropped.load(Ordering::Acquire), 0);
        runtime.release.trigger();
        assert_eq!(
            pending.await.unwrap().unwrap_err().code(),
            tonic::Code::InvalidArgument
        );
        until(|| handle.snapshot().active_rpcs == 0).await;
        assert_eq!(runtime.finished.load(Ordering::Acquire), 1);
        assert_eq!(runtime.dropped.load(Ordering::Acquire), 1);
        assert_eq!(runtime.cancelled.load(Ordering::Acquire), 0);
        // An idle authenticated connection still has a finite lifetime.
        until(|| handle.snapshot().active_connections == 0).await;
        assert_eq!(handle.snapshot().expired_max_age_connections, 1);
        assert_eq!(handle.snapshot().expired_unauthenticated_connections, 0);
        drop(client);
        assert_eq!(transport.shutdown().await.unwrap().active_rpcs, 0);
    });
}

#[test]
fn maximum_age_retires_stalled_rpc_and_its_owned_state() {
    run(|control| async move {
        let mut config = aging_configuration();
        config.connection_drain_timeout = Duration::from_millis(150);
        let (transport, runtime) = start(config, control).await;
        let handle = transport.handle();
        let mut client = client(&transport).await;
        let pending = tokio::spawn(async move { client.invoke(invocation()).await });
        until(|| runtime.started.load(Ordering::Acquire) == 1).await;
        assert!(pending.await.unwrap().is_err());
        until(|| handle.snapshot().active_connections == 0 && handle.snapshot().active_rpcs == 0)
            .await;
        assert_eq!(runtime.dropped.load(Ordering::Acquire), 1);
        assert_eq!(runtime.cancelled.load(Ordering::Acquire), 1);
        assert_eq!(runtime.finished.load(Ordering::Acquire), 0);
        assert_eq!(handle.snapshot().expired_max_age_connections, 1);
        let mut fresh = support::client(&transport).await;
        status(&mut fresh).await.unwrap();
        drop(fresh);
        transport.shutdown().await.unwrap();
    });
}

#[test]
fn peer_drop_and_node_shutdown_retire_active_connection_owners_once() {
    run(|control| async move {
        for shutdown in [false, true] {
            let (transport, runtime) = start(aging_configuration(), control.clone()).await;
            let handle = transport.handle();
            let mut client = client(&transport).await;
            let pending = tokio::spawn(async move { client.invoke(invocation()).await });
            until(|| runtime.started.load(Ordering::Acquire) == 1).await;
            if shutdown {
                let snapshot = transport.shutdown().await.unwrap();
                assert_eq!(snapshot.active_connections, 0);
                assert_eq!(snapshot.active_rpcs, 0);
                assert!(pending.await.unwrap().is_err());
            } else {
                pending.abort();
                assert!(pending.await.unwrap_err().is_cancelled());
                until(|| {
                    handle.snapshot().active_connections == 0 && handle.snapshot().active_rpcs == 0
                })
                .await;
                transport.shutdown().await.unwrap();
            }
            assert_eq!(runtime.dropped.load(Ordering::Acquire), 1);
            assert_eq!(runtime.cancelled.load(Ordering::Acquire), 1);
            assert_eq!(handle.snapshot().active_control_jobs, 0);
        }
    });
}
