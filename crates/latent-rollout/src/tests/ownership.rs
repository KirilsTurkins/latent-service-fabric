use super::*;
use latent_control_store::rollouts::{RolloutId, RolloutOperationLookup};
use latent_core::{PlatformErrorCode, TenantId};
use std::sync::mpsc;

#[test]
fn mutation_preflight_precedes_audit_and_catalog_effects() {
    runtime().block_on(async {
        let mut fixture = Fixture::new(CoordinatorLimits::default()).await;
        let before = fixture.audit.snapshot().retained_records;
        let result = fixture
            .handle
            .submit(support::start(), expires(), |preview| {
                assert_eq!(preview.receipt.revision, 1);
                assert_eq!(preview.audit_ack.attempt_sequence, Some(u64::MAX));
                Err(capacity("tiny-wire-budget"))
            })
            .unwrap()
            .wait()
            .await;
        assert_eq!(
            result.err().unwrap().error.code,
            PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(fixture.audit.snapshot().retained_records, before);
        assert!(fixture
            .repository
            .get_rollout(&TenantId("alice".into()), &RolloutId("rollout".into()))
            .unwrap()
            .is_none());
        fixture.shutdown().await;
    });
}

#[test]
fn committed_replay_keeps_revision_and_returned_response_owns_its_allowance() {
    runtime().block_on(async {
        let mut fixture = Fixture::new(CoordinatorLimits::default()).await;
        let first = fixture
            .handle
            .submit(support::start(), expires(), |_| Ok(()))
            .unwrap()
            .wait()
            .await
            .unwrap();
        assert!(!first.value().replayed);
        assert!(first.value().durability.is_ok());
        assert_eq!(
            first.value().audit_ack.status,
            latent_artifacts::ReleaseAuditStatus::Durable
        );
        let revision = first.value().receipt.revision;
        let second = fixture
            .handle
            .submit(support::start(), expires(), |_| Ok(()))
            .unwrap()
            .wait()
            .await
            .unwrap();
        assert!(second.value().replayed);
        assert_eq!(second.value().receipt, first.value().receipt);
        assert_eq!(second.value().receipt.revision, revision);
        assert_eq!(fixture.handle.snapshot().response_owners, 2);
        drop(second);
        let (_, lease) = first.into_parts();
        let extra = lease.clone();
        drop(lease);
        assert_eq!(fixture.handle.snapshot().response_owners, 1);
        fixture.shutdown().await;
        assert_eq!(fixture.handle.snapshot().response_owners, 1);
        drop(extra);
        assert_eq!(fixture.handle.snapshot().response_bytes, 0);
    });
}

#[test]
fn queued_cancel_and_shutdown_keep_active_owner_until_preflight_returns() {
    runtime().block_on(async {
        let mut fixture = Fixture::new(CoordinatorLimits::default()).await;
        let (entered, ready) = mpsc::sync_channel(1);
        let (release, proceed) = mpsc::sync_channel(1);
        // A bounded deliberately stalled adapter makes ownership observable;
        // production adapters must keep this callback nonblocking.
        let first = fixture
            .handle
            .submit(support::start(), expires(), move |_| {
                let _ = entered.send(());
                proceed
                    .recv_timeout(Duration::from_secs(5))
                    .map_err(|_| closed())
            })
            .unwrap();
        ready.recv_timeout(Duration::from_secs(5)).unwrap();
        let queued = fixture
            .handle
            .get(
                TenantId("alice".into()),
                RolloutId("rollout".into()),
                expires(),
            )
            .unwrap();
        let control = queued.control();
        assert!(control.cancel());
        drop(queued);
        assert_eq!(fixture.handle.snapshot().active_commands, 1);
        assert_eq!(fixture.handle.snapshot().queued_commands, 1);
        fixture.handle.close();
        assert!(!fixture
            .worker
            .join_until(Instant::now() + Duration::from_millis(5))
            .await
            .unwrap());
        assert_eq!(fixture.handle.snapshot().active_commands, 1);
        assert!(fixture.handle.snapshot().retained_request_bytes > 0);
        release.send(()).unwrap();
        assert!(first.wait().await.is_err());
        assert!(fixture.worker.join_until(expires()).await.unwrap());
        let snapshot = fixture.handle.snapshot();
        assert_eq!(
            (
                snapshot.active_commands,
                snapshot.queued_commands,
                snapshot.retained_request_bytes
            ),
            (0, 0, 0)
        );
        assert_eq!(fixture.audit.snapshot().retained_records, 0);
        fixture.shutdown().await;
    });
}

#[test]
fn expired_queued_command_cannot_create_an_audit_attempt() {
    runtime().block_on(async {
        let mut fixture = Fixture::new(CoordinatorLimits::default()).await;
        let (entered, ready) = mpsc::sync_channel(1);
        let (release, proceed) = mpsc::sync_channel(1);
        let first = fixture
            .handle
            .submit(support::start(), expires(), move |_| {
                let _ = entered.send(());
                let _ = proceed.recv_timeout(Duration::from_secs(5));
                Err(invalid("fixture-reject"))
            })
            .unwrap();
        ready.recv_timeout(Duration::from_secs(5)).unwrap();
        let second = fixture
            .handle
            .submit(
                support::start(),
                Instant::now() + Duration::from_millis(5),
                |_| Ok(()),
            )
            .unwrap();
        tokio::time::sleep(Duration::from_millis(10)).await;
        assert_eq!(
            second.wait().await.err().unwrap().error.code,
            PlatformErrorCode::DeadlineExceeded
        );
        release.send(()).unwrap();
        assert!(first.wait().await.is_err());
        fixture.shutdown().await;
        assert_eq!(fixture.audit.snapshot().retained_records, 0);
    });
}

#[test]
fn response_slots_bound_reads_and_owned_input_capacity_rejects_before_admission() {
    runtime().block_on(async {
        let limits = CoordinatorLimits {
            maximum_query_owners: 1,
            ..CoordinatorLimits::default()
        };
        let mut fixture = Fixture::new(limits).await;
        let response = fixture
            .handle
            .operation(
                TenantId("alice".into()),
                RolloutId("missing".into()),
                "unknown".into(),
                expires(),
            )
            .unwrap()
            .wait()
            .await
            .unwrap();
        assert!(matches!(response.value(), RolloutOperationLookup::Unknown));
        assert!(fixture
            .handle
            .get(
                TenantId("alice".into()),
                RolloutId("missing".into()),
                expires()
            )
            .is_err());
        drop(response);
        let mut oversized = String::with_capacity(1024);
        oversized.push_str("alice");
        assert_eq!(
            fixture
                .handle
                .get(TenantId(oversized), RolloutId("missing".into()), expires())
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::InvalidArgument
        );
        assert_eq!(fixture.handle.snapshot().retained_request_bytes, 0);
        fixture.shutdown().await;
    });
}

#[test]
fn ready_reply_polled_after_deadline_is_rejected_and_lease_released() {
    runtime().block_on(async {
        let mut fixture = Fixture::new(CoordinatorLimits::default()).await;
        let ticket = fixture
            .handle
            .get(
                TenantId("alice".into()),
                RolloutId("missing".into()),
                Instant::now() + Duration::from_millis(10),
            )
            .unwrap();
        tokio::time::sleep(Duration::from_millis(25)).await;
        assert_eq!(
            ticket.wait().await.err().unwrap().error.code,
            PlatformErrorCode::DeadlineExceeded
        );
        assert_eq!(fixture.handle.snapshot().response_owners, 0);
        fixture.shutdown().await;
    });
}
