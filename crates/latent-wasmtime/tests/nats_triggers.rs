//! Actual broker deliveries through publication admission, scheduler and fresh Wasm stores.
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "nats_triggers/acceptance.rs"]
mod acceptance;
#[path = "local_service/component.rs"]
mod component;
#[path = "nats_triggers/fixture.rs"]
mod fixture;
#[path = "local_service/packages.rs"]
#[allow(dead_code)]
mod packages;
#[path = "nats_triggers/provider.rs"]
mod provider;
#[path = "nats_triggers/proxy.rs"]
mod proxy;
#[path = "nats_triggers/recovery.rs"]
mod recovery;
use fixture::Fixture;
use latent_nats::triggers::{Acknowledgement, TriggerTerminal};

fn control(operation: &str) -> serde_json::Value {
    let result = std::process::Command::new("python3")
        .args([
            std::env::var("LSF_NATS_TEST_CONTROL").unwrap(),
            std::env::var("LSF_NATS_TEST_PORT").unwrap(),
            std::env::var("LSF_NATS_TEST_PEM").unwrap(),
            operation.into(),
        ])
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "fixture: {}",
        String::from_utf8_lossy(&result.stderr)
    );
    if result.stdout.is_empty() {
        serde_json::Value::Null
    } else {
        serde_json::from_slice(&result.stdout).unwrap()
    }
}

#[tokio::test]
#[ignore = "requires the owned pinned TLS JetStream trigger fixture"]
async fn real_nats_trigger_executes_two_tenants_and_reuses_bounded_connections() {
    control("reset-triggers");
    let mut f = Fixture::new(provider::config()).await;
    assert_eq!(f.triggers.monitor().snapshot().connection_attempts, 0);
    control("publish-triggers");
    let (_sender, mut stop) = tokio::sync::watch::channel(false);
    for index in 0..2 {
        let report = f
            .triggers
            .step(&f.manager, &mut stop)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(report.trigger_index, index);
        assert_eq!(report.terminal, TriggerTerminal::Succeeded, "{report:?}");
        assert_eq!(
            report.acknowledgement,
            Acknowledgement::Accepted,
            "{report:?}"
        );
        assert_eq!(report.delivery_count, 1);
    }
    f.idle().await;
    control("publish-triggers");
    tokio::time::sleep(std::time::Duration::from_millis(15)).await;
    for _ in 0..2 {
        let report = f
            .triggers
            .step(&f.manager, &mut stop)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(
            report.acknowledgement,
            Acknowledgement::Accepted,
            "{report:?}"
        );
    }
    let snapshot = f.triggers.monitor().snapshot();
    assert_eq!(
        (
            snapshot.executions,
            snapshot.acknowledged,
            snapshot.connection_attempts
        ),
        (4, 4, 2)
    );
    assert_eq!(snapshot.connection_reuses, 2);
    assert_eq!(f.backend.resource_snapshot().stores_created, 4);
    f.close().await;
}
