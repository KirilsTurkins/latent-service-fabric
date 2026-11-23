use super::support::*;
use latent_capabilities::broker::secrets::TlsCredentialScope;
use latent_core::{PlatformError, TenantId};
use latent_nats::{
    triggers::{
        InboxAdmissionFactory, InboxDelivery, NatsTriggerInspector, NatsTriggers, RootBudget,
        TransactionalBinding, TriggerBinding, TriggerConfig,
    },
    NatsCredential,
};
use latent_node::{transaction_runtime::NativeTransactionAdmission, InboundActivationReservation};
use std::{fs, os::unix::fs::PermissionsExt, sync::Arc, time::Instant};

struct NoAdmission;

impl InboxAdmissionFactory for NoAdmission {
    fn admission(
        &self,
        _: &InboundActivationReservation,
        _: &InboxDelivery,
    ) -> Result<Arc<NativeTransactionAdmission>, PlatformError> {
        panic!("broker readiness must never admit a command")
    }
}

#[tokio::test]
#[ignore = "requires tools/run_nats_deferred_tests.py owned pinned real JetStream"]
#[expect(
    clippy::too_many_lines,
    reason = "Use one original broker and its retained inbox position"
)]
async fn real_deferred_input_inspection_keeps_original_consumer_position_and_never_pulls() {
    let qualification = serde_json::from_value(control("input-inspection-setup")).unwrap();
    let root = tempfile::tempdir().unwrap();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let (_catalog, _policies, pools) = install_shared_pools(root.path());
    let transport = config();
    let secrets = install_protected_credentials(root.path(), Arc::clone(&pools), &transport).await;
    let destination = transport.endpoint.credential_destination();
    let credential = || NatsCredential {
        username: if standalone_token_auth() {
            None
        } else {
            Some("observer".into())
        },
        secret: secrets
            .bind_tls_credential(
                TlsCredentialScope {
                    tenant: TenantId("tests".into()),
                    provider_id: "events".into(),
                    destination: destination.clone(),
                },
                "nats-password".into(),
            )
            .unwrap(),
    };
    let input = TriggerConfig {
        format_version: 1,
        endpoint: transport.endpoint,
        public_roots: false,
        extra_roots: transport.extra_roots,
        bindings: vec![TriggerBinding {
            id: "original".into(),
            tenant: "tests".into(),
            principal_subject: "inbox".into(),
            service: "example".into(),
            contract: "tests:inbox/api@1.0.0".into(),
            function: "apply".into(),
            route: None,
            stream: "INBOX".into(),
            consumer: "INPUT".into(),
            filter_subject: "lsf.trigger.a".into(),
            transaction: Some(TransactionalBinding {
                processing_scope: "original".into(),
                namespace: "input".into(),
                incarnation: 1,
                entity: None,
                qualification,
                duplicate_window_millis: 30_000,
                state_read_bytes: 4096,
                state_write_bytes: 1024,
                effect_count: 1,
            }),
            budget: RootBudget {
                cpu_fuel: 10_000,
                memory_bytes: 65536,
                wall_time_millis: 3000,
                child_calls: 0,
                outbound_requests: 0,
                blob_read_bytes: 0,
                blob_write_bytes: 0,
                log_bytes: 0,
            },
        }],
        maximum_payload_bytes: 1024,
        operation_timeout_millis: 3000,
        poll_interval_millis: 10,
        maximum_deliveries: 3,
        ack_wait_millis: 6000,
        redelivery_delay_millis: 100,
    };
    let inspector = NatsTriggerInspector::install(
        Arc::clone(&pools),
        "events",
        1,
        input.clone(),
        vec![credential()],
    )
    .unwrap();
    let prior = control("input-inspection-state");
    let observed = inspector
        .inspect("tests", "original", Instant::now() + WATCHDOG)
        .await
        .unwrap();
    let observed = serde_json::to_value(observed).unwrap();
    assert_eq!(observed["consumerCreated"], prior["created"]);
    assert_eq!(observed["pending"], "1");
    assert_eq!(observed["acknowledgementPending"], "0");
    assert_eq!(observed["acknowledgementFloorStreamSequence"], "0");
    let mut poller = NatsTriggers::install_with_transaction_admission(
        Arc::clone(&pools),
        "events",
        2,
        1,
        input.clone(),
        vec![credential()],
        Arc::new(NoAdmission),
    )
    .unwrap();
    poller
        .qualify_startup(Instant::now() + WATCHDOG)
        .await
        .unwrap();
    assert_eq!(poller.monitor().snapshot().pulls, 0);
    assert_eq!(poller.monitor().snapshot().executions, 0);
    poller.close_idle().unwrap();
    drop(poller);

    let mut stale = input;
    stale.bindings[0]
        .transaction
        .as_mut()
        .unwrap()
        .qualification
        .stream_created = "2026-01-01T00:00:00Z".into();
    let mut poller = NatsTriggers::install_with_transaction_admission(
        pools,
        "events",
        3,
        2,
        stale,
        vec![credential()],
        Arc::new(NoAdmission),
    )
    .unwrap();
    assert!(matches!(
        poller.qualify_startup(Instant::now() + WATCHDOG).await,
        Err(latent_nats::EventError::PermissionDenied)
    ));
    assert_eq!(poller.monitor().snapshot().pulls, 0);
    poller.close_idle().unwrap();
    let after = control("input-inspection-state");
    for field in [
        "created",
        "delivered",
        "ack_floor",
        "num_pending",
        "num_ack_pending",
    ] {
        assert_eq!(after[field], prior[field]);
    }
    secrets.close();
}
