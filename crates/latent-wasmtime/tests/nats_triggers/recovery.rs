use super::{control, provider, proxy, Fixture};
use latent_nats::triggers::{Acknowledgement, TriggerTerminal};
use std::{sync::atomic::Ordering, time::Duration};

#[tokio::test]
#[ignore = "requires the owned pinned TLS JetStream trigger fixture"]
async fn real_nats_shutdown_during_guest_execution_keeps_ownership_through_cleanup() {
    control("reset-triggers");
    control("publish-triggers");
    let mut config = provider::config();
    config.bindings[0].function = "spin".into();
    let mut f = Fixture::new(config).await;
    let (sender, stop) = tokio::sync::watch::channel(false);
    let monitor = f.triggers.monitor();
    {
        let run = f.triggers.run(&f.manager, stop);
        tokio::pin!(run);
        tokio::select! {
            result=&mut run=>panic!("poller ended early: {result:?}"),
            ()=async {while f.backend.active_instance_reservations()==0 {tokio::task::yield_now().await;}}=>{},
            ()=tokio::time::sleep(Duration::from_secs(2))=>panic!("guest did not start"),
        }
        assert_eq!(f.quotas.usage().unwrap().active_activations, 1);
        sender.send(true).unwrap();
        tokio::time::timeout(Duration::from_secs(2), &mut run)
            .await
            .unwrap()
            .unwrap();
    }
    let last = monitor.last_step().unwrap();
    assert_eq!(
        (last.terminal, last.acknowledgement),
        (TriggerTerminal::Cancelled, Acknowledgement::NotSent)
    );
    assert_eq!(control("trigger-info")[0]["num_ack_pending"], 1);
    f.close().await;
}

#[tokio::test]
#[ignore = "requires the owned pinned TLS JetStream trigger fixture"]
async fn real_nats_lost_ack_restart_redelivers_and_can_execute_the_guest_twice() {
    control("reset-triggers");
    control("publish-triggers");
    let proxy = proxy::Proxy::new(provider::config()).await;
    let mut f = Fixture::new(proxy.config.clone()).await;
    proxy.mode.store(proxy::DROP_BEFORE_ACK, Ordering::Release);
    let (_sender, mut stop) = tokio::sync::watch::channel(false);
    let report = f
        .triggers
        .step(&f.manager, &mut stop)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        (report.terminal, report.acknowledgement),
        (TriggerTerminal::Succeeded, Acknowledgement::Uncertain),
        "{report:?}"
    );
    assert_eq!(f.backend.resource_snapshot().stores_created, 1);
    let first_sequence = report.stream_sequence;
    assert_eq!(control("trigger-info")[0]["num_ack_pending"], 1);
    proxy.mode.store(proxy::HEALTHY, Ordering::Release);
    let mut restarted = f.restart().await;
    // Broker durable position alone decides redelivery; there is no saved local offset.
    tokio::time::sleep(Duration::from_millis(3600)).await;
    let repeated = restarted
        .triggers
        .step(&restarted.manager, &mut stop)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(repeated.stream_sequence, first_sequence);
    assert_eq!(repeated.delivery_count, 2);
    assert_eq!(
        repeated.acknowledgement,
        Acknowledgement::Accepted,
        "{repeated:?}"
    );
    assert_eq!(restarted.backend.resource_snapshot().stores_created, 1);
    restarted.close().await;
    proxy.close().await;
}

#[tokio::test]
#[ignore = "requires the owned pinned TLS JetStream trigger fixture"]
async fn real_nats_lost_ack_receipt_remains_uncertain_when_the_broker_already_committed() {
    control("reset-triggers");
    control("publish-triggers");
    let proxy = proxy::Proxy::new(provider::config()).await;
    let mut f = Fixture::new(proxy.config.clone()).await;
    proxy.mode.store(proxy::DROP_ACK, Ordering::Release);
    let (_sender, mut stop) = tokio::sync::watch::channel(false);
    let report = f
        .triggers
        .step(&f.manager, &mut stop)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        (report.terminal, report.acknowledgement),
        (TriggerTerminal::Succeeded, Acknowledgement::Uncertain)
    );
    assert_eq!(control("trigger-info")[0]["num_ack_pending"], 0);
    assert_eq!(f.triggers.monitor().snapshot().executions, 1);
    f.close().await;
    proxy.close().await;
}

#[tokio::test]
#[ignore = "requires the owned pinned TLS JetStream trigger fixture"]
async fn real_nats_shutdown_reclaims_pending_delivery_without_running_guest_or_acknowledging() {
    control("reset-triggers");
    control("publish-triggers");
    let proxy = proxy::Proxy::new(provider::config()).await;
    let mut f = Fixture::new(proxy.config.clone()).await;
    proxy.mode.store(proxy::HOLD_DELIVERY, Ordering::Release);
    let (sender, stop) = tokio::sync::watch::channel(false);
    let monitor = f.triggers.monitor();
    {
        let run = f.triggers.run(&f.manager, stop);
        tokio::pin!(run);
        tokio::select! {
            result=&mut run=>panic!("poller ended early: {result:?}"),
            ()=proxy.seen.notified()=>{},
            ()=tokio::time::sleep(Duration::from_secs(2))=>panic!("delivery was not pulled"),
        }
        assert_eq!(monitor.snapshot().active_deliveries, 1);
        assert_eq!(f.quotas.usage().unwrap().active_activations, 1);
        sender.send(true).unwrap();
        tokio::time::timeout(Duration::from_secs(2), &mut run)
            .await
            .unwrap()
            .unwrap();
    }
    assert_eq!(monitor.snapshot().active_deliveries, 0);
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    assert_eq!(f.pools.snapshot().unwrap().connections, 0);
    assert_eq!(control("trigger-info")[0]["num_ack_pending"], 1);
    proxy.close().await;
    f.close().await;
}
