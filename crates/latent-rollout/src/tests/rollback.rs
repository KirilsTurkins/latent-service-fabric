mod recovery;
mod support;
use super::*;
use latent_audit::{AuditControlAction, AuditOperationResult, AuditRecordData};
use latent_control_store::rollouts::{RolloutId, RolloutState};
use latent_core::{PlatformErrorCode, RouteGeneration, TenantId};
use std::sync::atomic::Ordering;
use support::request;

#[test]
fn rollback_retires_observation_and_replays_exact_receipt_after_target_denial() {
    runtime().block_on(async {
        let (mut fixture, gate) = support::fixture(true).await;
        support::start(&fixture, true).await;
        assert_eq!(fixture.handle.snapshot().canary_windows, 1);
        assert!(fixture
            .handle
            .submit(request("bypass", 1, 1), expires(), |_| Ok(()))
            .is_err());
        let result = fixture
            .handle
            .rollback(request("restore", 1, 1), expires(), |preview| {
                assert!(preview.failure.is_none());
                assert_eq!(
                    preview
                        .receipt
                        .unwrap()
                        .rollback_target
                        .as_ref()
                        .unwrap()
                        .historical_route_generation,
                    RouteGeneration(1)
                );
                Ok(())
            })
            .unwrap()
            .wait()
            .await
            .unwrap();
        assert_eq!(result.value().receipt.state, RolloutState::RolledBack);
        assert_eq!(result.value().receipt.route_generation, RouteGeneration(3));
        assert_eq!(
            result.value().observation.unwrap().state,
            RolloutObservationState::Retired
        );
        assert_eq!(fixture.handle.snapshot().canary_windows, 0);
        assert_eq!(
            fixture
                .handle
                .canary_snapshot()
                .unwrap()
                .unwrap()
                .tracked_series,
            0
        );
        let attempt = audit::attempt(&result.value().receipt, false).unwrap();
        assert_eq!(attempt.action, AuditControlAction::Rollback);
        assert_eq!(
            attempt.expected_rollback_target_generation,
            Some(RouteGeneration(1))
        );
        assert_eq!(
            attempt.identities.rollback_target_generation,
            Some(RouteGeneration(1))
        );
        assert_eq!(
            attempt.identities.route_generation,
            Some(RouteGeneration(3))
        );
        gate.store(2, Ordering::Release);
        let replay = fixture
            .handle
            .rollback(request("restore", 1, 1), expires(), |preview| {
                assert!(preview.replayed);
                Ok(())
            })
            .unwrap()
            .wait()
            .await
            .unwrap();
        assert_eq!(result.value().receipt, replay.value().receipt);
        let fresh = fixture
            .handle
            .rollback(request("again", 2, 1), expires(), |_| Ok(()))
            .unwrap()
            .wait()
            .await
            .err()
            .unwrap();
        assert_eq!(fresh.error.code, PlatformErrorCode::StateConflict);
        drop(replay);
        drop(result);
        fixture.shutdown().await;
    });
}

#[test]
fn target_failure_and_success_preflights_precede_audit_and_publication() {
    runtime().block_on(async {
        let (mut fixture,gate)=support::fixture(false).await;
        support::start(&fixture,false).await;
        let before=support::rows(&fixture).await.len();
        let rejected=fixture.handle.rollback(request("small-success",1,1),expires(),|preview| {
            assert!(preview.receipt.is_some()); Err(capacity("small-response"))
        }).unwrap().wait().await.err().unwrap();
        assert_eq!(rejected.error.code,PlatformErrorCode::ResourceExhausted);
        gate.store(1,Ordering::Release);
        let rejected=fixture.handle.rollback(request("small-rejection",1,1),expires(),|preview| {
            assert!(preview.failure.is_some()); assert!(preview.receipt.is_none());
            Err(capacity("small-response"))
        }).unwrap().wait().await.err().unwrap();
        assert_eq!(rejected.error.code,PlatformErrorCode::ResourceExhausted);
        assert_eq!(support::rows(&fixture).await.len(),before);
        let rejected=fixture.handle.rollback(request("missing-target",1,1),expires(),|_|Ok(()))
            .unwrap().wait().await.err().unwrap();
        assert_eq!(rejected.error.code,PlatformErrorCode::NotFound);
        assert_eq!(rejected.audit_ack.status,latent_artifacts::ReleaseAuditStatus::Durable);
        let rows=support::rows(&fixture).await;
        let attempt=rows.iter().find_map(|row|match &row.data {
            AuditRecordData::Attempt(value) if value.operation_id=="missing-target"=>Some(value),_=>None,
        }).unwrap();
        assert_eq!(attempt.expected_rollback_target_generation,Some(RouteGeneration(1)));
        assert_eq!(attempt.identities.rollback_target_generation,None);
        assert!(rows.iter().any(|row|matches!(&row.data,AuditRecordData::Outcome{conclusion,..}
            if conclusion.result==AuditOperationResult::Rejected && conclusion.receipt_digest.is_none())));
        assert_eq!(fixture.repository.get_rollout(&TenantId("alice".into()),&RolloutId("rollout".into())).unwrap().unwrap().revision,1);
        gate.store(2,Ordering::Release);
        let denied=fixture.handle.rollback(request("denied-target",1,1),expires(),|_|Ok(()))
            .unwrap().wait().await.err().unwrap();
        assert_eq!(denied.error.code,PlatformErrorCode::PermissionDenied);
        assert_eq!(denied.audit_ack.status,latent_artifacts::ReleaseAuditStatus::Durable);
        fixture.shutdown().await;
    });
}

#[test]
fn queued_rollback_cancellation_keeps_ownership_until_real_worker_retirement() {
    runtime().block_on(async {
        let (mut fixture, _gate) = support::fixture(false).await;
        support::start(&fixture, false).await;
        let (entered, ready) = std::sync::mpsc::sync_channel(1);
        let (release, proceed) = std::sync::mpsc::sync_channel(1);
        let first = fixture
            .handle
            .rollback(request("held", 1, 1), expires(), move |_| {
                entered.send(()).unwrap();
                proceed
                    .recv_timeout(Duration::from_secs(5))
                    .map_err(|_| closed())?;
                Err(invalid("test-preflight-reject"))
            })
            .unwrap();
        ready.recv_timeout(Duration::from_secs(5)).unwrap();
        let second = fixture
            .handle
            .rollback(request("cancelled", 1, 1), expires(), |_| Ok(()))
            .unwrap();
        assert!(second.control().cancel());
        drop(second);
        assert_eq!(
            (
                fixture.handle.snapshot().active_commands,
                fixture.handle.snapshot().queued_commands
            ),
            (1, 1)
        );
        fixture.handle.close();
        assert!(!fixture
            .worker
            .join_until(Instant::now() + Duration::from_millis(5))
            .await
            .unwrap());
        assert!(fixture.handle.snapshot().retained_request_bytes > 0);
        release.send(()).unwrap();
        assert!(first.wait().await.is_err());
        assert!(fixture.worker.join_until(expires()).await.unwrap());
        assert_eq!(fixture.handle.snapshot().retained_request_bytes, 0);
        fixture.shutdown().await;
    });
}
