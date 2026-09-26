use super::{control, provider, Fixture};
use latent_nats::triggers::{Acknowledgement, TriggerTerminal};
use std::time::{Duration, Instant};

#[tokio::test]
#[ignore = "requires the owned pinned TLS JetStream trigger fixture"]
async fn real_nats_idle_256_triggers_keep_two_connections_and_zero_guest_stores() {
    control("reset-many-triggers");
    let mut config = provider::config();
    let mut bindings = Vec::with_capacity(256);
    for template in &config.bindings {
        for index in 0..128 {
            let mut binding = template.clone();
            binding.id = format!("{}-{index}", template.id);
            if index != 0 {
                binding.consumer = format!("PROCESS{index}");
            }
            bindings.push(binding);
        }
    }
    config.bindings = bindings;
    let mut f = Fixture::new(config).await;
    let initial = f.pools.snapshot().unwrap();
    assert_eq!((initial.connections, initial.running_requests), (0, 0));
    let (_sender, mut stop) = tokio::sync::watch::channel(false);
    for _ in 0..256 {
        assert!(f
            .triggers
            .step(&f.manager, &mut stop)
            .await
            .unwrap()
            .is_none());
    }
    f.idle().await;
    let monitor = f.triggers.monitor().snapshot();
    assert_eq!(
        (monitor.triggers, monitor.pulls, monitor.executions),
        (256, 256, 0)
    );
    assert_eq!(
        (monitor.connection_attempts, monitor.connection_reuses),
        (2, 254)
    );
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    assert_eq!(f.pools.snapshot().unwrap().connections, 2);
    f.close().await;
}

#[tokio::test]
#[ignore = "requires the owned pinned TLS JetStream trigger fixture"]
async fn real_nats_overload_reserves_before_pull_and_recovers_without_prefetch() {
    control("reset-triggers");
    control("publish-triggers");
    let mut f = Fixture::new(provider::config()).await;
    let mut reservations = vec![];
    for index in 0..8 {
        let now = latent_core::ClockSample::system_now();
        reservations.push(
            f.manager
                .reserve_inbound(
                    f.request(&format!("held-{index}")),
                    1024,
                    latent_core::IncomingDeadline::new(
                        Instant::now() + Duration::from_secs(2),
                        now.unix_millis() + 2000,
                    ),
                )
                .unwrap(),
        );
    }
    let (_sender, mut stop) = tokio::sync::watch::channel(false);
    for _ in 0..2 {
        let rejected = f
            .triggers
            .step(&f.manager, &mut stop)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(rejected.acknowledgement, Acknowledgement::NotSent);
        assert_eq!(rejected.terminal, TriggerTerminal::Rejected);
    }
    assert_eq!(
        (
            f.triggers.monitor().snapshot().pulls,
            f.triggers.monitor().snapshot().connection_attempts
        ),
        (0, 0)
    );
    for info in control("trigger-info").as_array().unwrap() {
        assert_eq!(info["delivered"]["stream_seq"], 0);
    }
    drop(reservations);
    tokio::time::sleep(Duration::from_millis(120)).await;
    for _ in 0..2 {
        assert_eq!(
            f.triggers
                .step(&f.manager, &mut stop)
                .await
                .unwrap()
                .unwrap()
                .acknowledgement,
            Acknowledgement::Accepted
        );
    }
    f.close().await;
}

#[tokio::test]
#[ignore = "requires the owned pinned TLS JetStream trigger fixture"]
async fn real_nats_routes_change_future_deliveries_and_revocation_is_tenant_scoped() {
    use latent_control_store::DeploymentStore;
    control("reset-triggers");
    control("publish-triggers");
    let mut f = Fixture::new(provider::config()).await;
    let (_sender, mut stop) = tokio::sync::watch::channel(false);
    let first = f
        .triggers
        .step(&f.manager, &mut stop)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(first.acknowledgement, Acknowledgement::Accepted);
    assert_eq!(
        f.triggers
            .step(&f.manager, &mut stop)
            .await
            .unwrap()
            .unwrap()
            .acknowledgement,
        Acknowledgement::Accepted
    );
    let mut changed = f.targets[0].clone();
    changed.resources.cpu_fuel -= 1;
    f.store.apply(changed).await.unwrap();
    control("publish-triggers");
    tokio::time::sleep(Duration::from_millis(15)).await;
    let second = f
        .triggers
        .step(&f.manager, &mut stop)
        .await
        .unwrap()
        .unwrap();
    assert!(second.route_generation > first.route_generation);
    assert_eq!(second.acknowledgement, Acknowledgement::Accepted);
    f.triggers.step(&f.manager, &mut stop).await.unwrap();
    f.revoke(0);
    control("publish-triggers");
    tokio::time::sleep(Duration::from_millis(15)).await;
    let denied = f
        .triggers
        .step(&f.manager, &mut stop)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        (denied.terminal, denied.acknowledgement),
        (TriggerTerminal::Rejected, Acknowledgement::NotSent)
    );
    assert_eq!(
        f.triggers
            .step(&f.manager, &mut stop)
            .await
            .unwrap()
            .unwrap()
            .acknowledgement,
        Acknowledgement::Accepted
    );
    assert_eq!(f.backend.resource_snapshot().stores_created, 5);
    f.close().await;
}

#[tokio::test]
#[ignore = "requires the owned pinned TLS JetStream trigger fixture"]
async fn real_nats_declared_failure_terminates_and_transient_poison_exhausts_three_deliveries() {
    control("reset-triggers");
    control("publish-triggers");
    let mut config = provider::config();
    config.bindings[0].function = "fail".into();
    config.bindings[1].function = "spin".into();
    config.bindings[1].budget.cpu_fuel = 10000;
    let mut f = Fixture::new(config).await;
    let (_sender, mut stop) = tokio::sync::watch::channel(false);
    let declared = f
        .triggers
        .step(&f.manager, &mut stop)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        (declared.terminal, declared.acknowledgement),
        (
            TriggerTerminal::DeclaredFailure,
            Acknowledgement::Terminated
        )
    );
    let mut failures = vec![];
    for _ in 0..12 {
        if let Some(report) = f.triggers.step(&f.manager, &mut stop).await.unwrap() {
            failures.push(report);
        }
        if failures.len() == 3 {
            break;
        }
        tokio::time::sleep(Duration::from_millis(120)).await;
    }
    assert_eq!(failures.len(), 3, "{failures:?}");
    for (index, report) in failures.iter().enumerate() {
        assert_eq!(report.delivery_count, index as u32 + 1);
        assert_eq!(
            report.acknowledgement,
            if index == 2 {
                Acknowledgement::Terminated
            } else {
                Acknowledgement::RetryScheduled
            },
            "{report:?}"
        );
    }
    assert_eq!(failures[2].terminal, TriggerTerminal::Exhausted);
    assert_eq!(f.triggers.monitor().last_step(), Some(failures[2]));
    assert_eq!(f.triggers.monitor().snapshot().exhausted, 1);
    f.close().await;
}

#[tokio::test]
#[ignore = "requires the owned pinned TLS JetStream trigger fixture"]
async fn real_nats_invalid_payload_terminates_without_guest_execution() {
    control("reset-triggers");
    control("publish-poison");
    let mut f = Fixture::new(provider::config()).await;
    let (_sender, mut stop) = tokio::sync::watch::channel(false);
    for _ in 0..2 {
        let report = f
            .triggers
            .step(&f.manager, &mut stop)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(
            (report.terminal, report.acknowledgement),
            (TriggerTerminal::Rejected, Acknowledgement::Terminated),
            "{report:?}"
        );
    }
    f.close().await;
}
