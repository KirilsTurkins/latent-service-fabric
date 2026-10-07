use super::*;
use latent_effects::authority::{
    CommitLink, DispatchCeiling, DispatchContext, DispatchGrant, DispatchProfile,
    EffectAuthorityOwner, EffectRule, EffectScope, EffectTime,
};

fn grant(provider: &str, tenant: &str) -> (DispatchContext, DispatchGrant) {
    let owner = EffectAuthorityOwner::new(1, 1, 100).unwrap();
    let rule = EffectRule {
        scope: EffectScope {
            tenant: tenant.into(),
            namespace: "orders".into(),
            incarnation: 1,
            publication: "publication".into(),
            binding: "events".into(),
            operation: "publish".into(),
        },
        profile: DispatchProfile {
            provider: provider.into(),
            destination: "orders".into(),
            adapter: "test.v1".into(),
            intent_format: 1,
            payload_format: "value.v1".into(),
            idempotency_profile: "window.v1".into(),
        },
        policy_revision: 1,
        credential_epoch: 1,
        protected_credential_reference: "provider-secret".into(),
        ceiling: DispatchCeiling {
            maximum_payload_bytes: 4096,
            maximum_response_bytes: 16384,
            maximum_attempts: 3,
            maximum_age_millis: 10000,
            attempt_timeout_millis: 5000,
        },
        enabled: true,
    };
    owner.publish(rule.clone()).unwrap();
    let time = EffectTime {
        unix_millis: 100,
        continuity_proven: true,
    };
    let authority = owner
        .capture(
            &rule.scope,
            CommitLink {
                command: "command".into(),
                caller_scope: "caller".into(),
                attempt: 1,
                commit: "commit".into(),
                effect: "a".repeat(64),
                sequence: 0,
            },
            0,
            "b".repeat(64),
            time,
        )
        .unwrap();
    let mut context = owner.accept(&authority, 1, time).unwrap();
    let grant = context
        .accept_with(&authority, 1, time, |grant| grant)
        .unwrap();
    (context, grant)
}

#[tokio::test]
async fn deferred_socket_preserves_shared_capacity_after_request_drop_and_finite_operations() {
    let setup = Setup::new(single());
    let (context, grant) = grant("secrets", "tenant-a");
    let request = setup
        .pools
        .deferred(&setup.client, grant, 2, 16384)
        .unwrap();
    request.begin_operation().unwrap();
    request.begin_operation().unwrap();
    assert!(request.begin_operation().is_err());
    let wrong = setup.pools.client::<TcpStream>(&setup.provider, 1).unwrap();
    assert!(wrong.reserve_deferred_connection(&request).is_err());
    let reservation = setup.client.reserve_deferred_connection(&request).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (mut peer, _) = listener.accept().unwrap();
    peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
    let connection = reservation.connected(stream).unwrap();
    drop(request);
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);
    assert_eq!(setup.pools.snapshot().unwrap().connections, 1);
    assert_eq!(setup.pools.snapshot().unwrap().cleanup_jobs, 0);
    drop(connection);
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 0);
    context.retire().unwrap();
    clean(&setup.pools).await;
}

#[tokio::test]
async fn deferred_authority_cannot_select_another_provider_or_refund_live_rotated_requests() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_running_requests: 2,
        maximum_running_per_tenant: 1,
        maximum_running_per_provider: 2,
        ..ProviderPoolLimits::default()
    });
    let (context, wrong) = grant("another-provider", "tenant-a");
    let before = setup.pools.snapshot().unwrap();
    assert!(setup.pools.deferred(&setup.client, wrong, 1, 4096).is_err());
    assert_eq!(setup.pools.snapshot().unwrap(), before);
    context.retire().unwrap();
    let (first_context, first) = grant("secrets", "tenant-a");
    let first = setup.pools.deferred(&setup.client, first, 1, 4096).unwrap();
    let (other_context, other) = grant("secrets", "tenant-a");
    assert!(setup.pools.deferred(&setup.client, other, 1, 4096).is_err());
    other_context.retire().unwrap();
    let (second_context, second) = grant("secrets", "tenant-b");
    let second = setup
        .pools
        .deferred(&setup.client, second, 1, 4096)
        .unwrap();
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 2);
    let replacement = install(&setup.pools, "secrets", 2, 1, b"rotated-secret");
    assert!(first.checkpoint().is_err());
    assert!(second.checkpoint().is_err());
    assert!(setup.client.reserve_deferred_connection(&first).is_err());
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 2);
    drop((first, second, replacement));
    first_context.retire().unwrap();
    second_context.retire().unwrap();
    clean(&setup.pools).await;
}
