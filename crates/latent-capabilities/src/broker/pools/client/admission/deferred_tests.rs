use super::*;
use crate::broker::pools::{limits::Kind, tests::fixture::*, ProviderPoolLimits};
use crate::broker::tests::fixture::{pending, ready};
use latent_core::PlatformErrorCode;
use latent_effects::authority::{
    AuthorityError, CommitLink, DispatchCeiling, DispatchContext, DispatchGrant, DispatchProfile,
    EffectAuthorityOwner, EffectRule, EffectScope, EffectTime, ProviderLookupAuthorization,
};
use std::{
    io::Read,
    net::{TcpListener, TcpStream},
    time::Instant,
};

struct LookupPermission;
impl ProviderLookupAuthorization for LookupPermission {
    fn with_current(
        &self,
        accept: &mut dyn FnMut() -> Result<(), AuthorityError>,
    ) -> Result<(), AuthorityError> {
        accept()
    }
    fn with_live(
        &self,
        accept: &mut dyn FnMut() -> Result<(), AuthorityError>,
    ) -> Result<(), AuthorityError> {
        accept()
    }
}

fn original_grant(lookup: bool, deadline: Option<Instant>) -> (DispatchContext, DispatchGrant) {
    let provider = "secrets";
    let tenant = "tenant-a";
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
    let mut context = if lookup {
        owner
            .accept_lookup(
                &authority,
                1,
                time,
                deadline.unwrap_or_else(|| Instant::now() + Duration::from_secs(1)),
                Arc::new(LookupPermission),
            )
            .unwrap()
    } else {
        let mut context = owner.accept(&authority, 1, time).unwrap();
        if let Some(deadline) = deadline {
            context.restrict_deadline(deadline).unwrap();
        }
        context
    };
    let grant = context
        .accept_with(&authority, 1, time, |grant| grant)
        .unwrap();
    (context, grant)
}

fn request(
    setup: &Setup,
    lookup: bool,
    deadline: Option<Instant>,
) -> (DispatchContext, DeferredRequest) {
    let (context, grant) = original_grant(lookup, deadline);
    let request = setup
        .pools
        .deferred(&setup.client, grant, 2, 16384)
        .unwrap();
    (context, request)
}

#[tokio::test]
async fn deferred_registry_inspection_waits_without_false_capacity_or_socket_allocation() {
    for lookup in [false, true] {
        let setup = Setup::new(single());
        let (context, request) = request(&setup, lookup, None);
        let mut waiting = Box::pin(setup.client.reserve_deferred_connection_wait(&request));
        {
            let _inspection = setup.pools.inner.state.lock().unwrap();
            // Demonstrate the original immediate refusal under this exact lock,
            // with available physical capacity and an already accepted request.
            assert_eq!(
                setup
                    .client
                    .reserve_deferred_connection(&request)
                    .err()
                    .unwrap()
                    .code,
                PlatformErrorCode::ResourceExhausted
            );
            pending(waiting.as_mut());
            assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
            assert!(!setup.client.core.backoff.lock().unwrap().dialing);
        }
        let reservation = waiting.await.unwrap();
        assert_eq!(setup.pools.snapshot().unwrap().connecting_connections, 1);
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let (mut peer, _) = listener.accept().unwrap();
        peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
        let connection = reservation.connected(stream).unwrap();
        drop(request);
        assert_eq!(setup.pools.snapshot().unwrap().connections, 1);
        assert_eq!(
            setup.pools.snapshot().unwrap().running_requests,
            usize::from(!lookup)
        );
        assert_eq!(
            setup.pools.snapshot().unwrap().cleanup_jobs,
            usize::from(lookup)
        );
        drop(connection);
        assert_eq!(peer.read(&mut [0]).unwrap(), 0);
        context.retire().unwrap();
        clean(&setup.pools).await;
    }
}

#[tokio::test]
async fn deferred_backoff_inspection_waits_without_starting_or_retrying_a_dial() {
    for lookup in [false, true] {
        let setup = Setup::new(single());
        let (context, request) = request(&setup, lookup, None);
        let mut waiting = Box::pin(setup.client.reserve_deferred_connection_wait(&request));
        {
            let _inspection = setup.client.core.backoff.lock().unwrap();
            pending(waiting.as_mut());
            assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
        }
        let reservation = waiting.await.unwrap();
        assert_eq!(setup.pools.snapshot().unwrap().connecting_connections, 1);
        drop((reservation, request));
        context.retire().unwrap();
        clean(&setup.pools).await;
    }
}

#[tokio::test]
async fn deferred_idle_contention_waits_and_fresh_lookup_never_borrows_a_guest_socket() {
    for lookup in [false, true] {
        let setup = Setup::new(single());
        let (session, _control) = setup.session("original-idle-socket");
        let call = setup.call(&session).await;
        let (mut connection, _peer) = connect(&setup.client, &call);
        let address = connection.resource().local_addr().unwrap();
        connection.park().unwrap();
        drop((call, session));
        let (context, request) = request(&setup, lookup, None);
        let mut waiting = Box::pin(setup.client.checkout_deferred_wait(&request));
        {
            let _inspection = setup.client.idle.lock().unwrap();
            if lookup {
                assert!(ready(waiting.as_mut()).unwrap().is_none());
            } else {
                pending(waiting.as_mut());
            }
            assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
            assert_eq!(setup.pools.inner.quotas.use_of(Kind::Idle), 1);
        }
        if lookup {
            drop(waiting);
        } else {
            let mut reused = waiting.await.unwrap().unwrap();
            assert_eq!(reused.resource().local_addr().unwrap(), address);
            assert_eq!(setup.pools.snapshot().unwrap().idle_connections, 0);
            drop(reused);
        }
        drop(request);
        context.retire().unwrap();
        clean(&setup.pools).await;
    }
}

#[tokio::test]
async fn deferred_actual_capacity_active_dial_and_backoff_keep_immediate_refusals() {
    for lookup in [false, true] {
        let setup = Setup::new(ProviderPoolLimits {
            maximum_connections: 1,
            maximum_connections_per_client: 1,
            maximum_idle_connections: 1,
            ..ProviderPoolLimits::default()
        });
        let (context, request) = request(&setup, lookup, None);
        let charge = setup
            .pools
            .inner
            .quotas
            .acquire(Kind::Connection, 1)
            .unwrap();
        assert_eq!(
            ready(setup.client.reserve_deferred_connection_wait(&request))
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::ResourceExhausted
        );
        drop(charge);
        let reservation = ready(setup.client.reserve_deferred_connection_wait(&request)).unwrap();
        assert_eq!(
            ready(setup.client.reserve_deferred_connection_wait(&request))
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::ResourceExhausted
        );
        drop(reservation);
        let failure = ready(setup.client.reserve_deferred_connection_wait(&request))
            .err()
            .unwrap();
        assert_eq!(failure.code, PlatformErrorCode::Unavailable);
        assert_eq!(failure.message, "provider-backoff");
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
        drop(request);
        context.retire().unwrap();
        clean(&setup.pools).await;
    }
}

#[tokio::test]
async fn deferred_wait_preserves_original_deadline_and_abandonment_retirement() {
    for lookup in [false, true] {
        for action in ["expire", "abandon", "retire"] {
            let setup = Setup::new(single());
            let (context, request) = request(
                &setup,
                lookup,
                Some(Instant::now() + Duration::from_millis(100)),
            );
            let original = request.deadline();
            let mut waiting = Box::pin(setup.client.reserve_deferred_connection_wait(&request));
            {
                let _inspection = setup.pools.inner.state.lock().unwrap();
                pending(waiting.as_mut());
                if action == "expire" {
                    std::thread::sleep(Duration::from_millis(125));
                }
                assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
            }
            if action == "abandon" {
                drop(waiting);
            } else {
                if action == "retire" {
                    setup.pools.retire();
                }
                assert_eq!(
                    waiting.await.err().unwrap().code,
                    if action == "expire" {
                        PlatformErrorCode::DeadlineExceeded
                    } else {
                        PlatformErrorCode::PermissionDenied
                    }
                );
            }
            assert_eq!(request.deadline(), original);
            assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
            drop(request);
            context.retire().unwrap();
            clean(&setup.pools).await;
        }
    }
}

#[tokio::test]
async fn deferred_poisoned_registry_fails_closed_without_waiting_or_reserving() {
    for lookup in [false, true] {
        let setup = Setup::new(single());
        let (context, request) = request(&setup, lookup, None);
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _inspection = setup.pools.inner.state.lock().unwrap();
            panic!("controlled deferred registry poison");
        }))
        .is_err());
        let failure = ready(setup.client.reserve_deferred_connection_wait(&request))
            .err()
            .unwrap();
        assert_eq!(failure.code, PlatformErrorCode::Unavailable);
        assert_eq!(failure.message, "provider-client-owner-poisoned");
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
        setup.pools.inner.state.clear_poison();
        drop(request);
        context.retire().unwrap();
        clean(&setup.pools).await;
    }
}

#[tokio::test]
async fn deferred_wait_cannot_select_another_client_or_revive_a_retired_epoch() {
    for lookup in [false, true] {
        let setup = Setup::new(single());
        let (context, request) = request(&setup, lookup, None);
        let wrong = setup.pools.client::<TcpStream>(&setup.provider, 1).unwrap();
        assert_eq!(
            ready(wrong.reserve_deferred_connection_wait(&request))
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::PermissionDenied
        );
        assert_eq!(
            ready(wrong.checkout_deferred_wait(&request))
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::PermissionDenied
        );
        let replacement = install(&setup.pools, "secrets", 2, 1, b"rotated-deferred-secret");
        assert_eq!(
            ready(setup.client.reserve_deferred_connection_wait(&request))
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::PermissionDenied
        );
        assert_eq!(
            ready(setup.client.checkout_deferred_wait(&request))
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::PermissionDenied
        );
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
        drop((request, replacement));
        context.retire().unwrap();
        clean(&setup.pools).await;
    }
}
