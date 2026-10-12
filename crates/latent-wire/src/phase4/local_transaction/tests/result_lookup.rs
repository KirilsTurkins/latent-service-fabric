//! Recovery reads never acquire activation, guest or ordinary native capacity.
use super::*;
use crate::phase4::StateManagementBackend;
use latent_rpc::phase4 as contract;

async fn lookup(
    backend: &StateManagementBackend,
    request: t::LookupCommandRequest,
) -> crate::phase4::OwnedPhase4Response {
    backend
        .execute_state(context("alice"), request.into())
        .await
        .unwrap()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_lost_result_lookup_preserves_original_receipt_under_ordinary_saturation() {
    let f = Fixture::with_lookup_frames().await;
    let original = invoke(&f, "lost-result", 1, false).await;
    let original_command = original.command.as_ref().unwrap().clone();
    let original_body = success(&original);
    drop(original);
    let backend = f.recovery_backend().await;
    let ordinary = f.saturate_ordinary_native();
    let adapter = crate::phase4::Phase4ServiceAdapter::with_services(
        Arc::new(backend.clone()),
        crate::management::ManagementLimits {
            auth: crate::invocation::InvocationLimits {
                budget_profile: latent_core::BudgetProfile::Phase4,
                ..Default::default()
            },
            ..Default::default()
        },
        crate::phase4::Phase4Services {
            principals: Arc::new(crate::invocation::LocalPrincipalPolicy),
            management: Arc::new(crate::management::LocalManagementPolicy),
            clock: Arc::new(latent_core::SystemActivationClock),
        },
    )
    .unwrap();
    let wire = adapter
        .lookup_command(context("alice").request(f.lookup_request("lost-result")))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        wire.command.as_ref().unwrap().commit,
        original_command.commit
    );
    drop(wire);
    drop(adapter);
    let recovered = lookup(&backend, f.lookup_request("lost-result")).await;
    let contract::Response::LookupCommand(value) = &recovered.response else {
        panic!("lookup response");
    };
    let command = value.command.as_ref().unwrap();
    assert_eq!(command.commit, original_command.commit);
    assert_eq!(command.source, original_command.source);
    assert_eq!(
        command.fingerprint_sha256,
        original_command.fingerprint_sha256
    );
    assert_eq!(command.retention, original_command.retention);
    assert_eq!(
        command.retained_result,
        Some(t::command_inspection::RetainedResult::Success(
            original_body
        ))
    );
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::Command).await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    let wrong_caller = backend
        .execute_state(context("bob"), f.lookup_request("lost-result").into())
        .await;
    assert_eq!(
        wrong_caller.err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    drop(ordinary);
    drop(recovered);
    drop(backend);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_lookup_retains_current_read_authority_and_distinct_payload_identity_cutoffs()
{
    let f = Fixture::with_lookup_frames().await;
    let original = invoke(&f, "retained-window", 1, false).await;
    let commit = original
        .command
        .as_ref()
        .unwrap()
        .commit
        .as_ref()
        .unwrap()
        .clone();
    drop(original);
    let backend = f.recovery_backend().await;
    let body = lookup(&backend, f.lookup_request("retained-window")).await;
    let request = f.lookup_request("retained-window");
    let receipt = backend
        .execute_state(
            context("alice"),
            t::LookupCommitRequest {
                profile: request.profile,
                command: request.command,
                receipt_id: commit.receipt_id.clone(),
                authorization_publication: request.authorization_publication,
            }
            .into(),
        )
        .await
        .unwrap();
    f.clock.0.store(11_001, Ordering::SeqCst);
    assert_eq!(
        body.owner.with_current(&mut || {}).unwrap_err().code,
        PlatformErrorCode::DeadlineExceeded
    );
    receipt.owner.with_current(&mut || {}).unwrap();
    let metadata = lookup(&backend, f.lookup_request("retained-window")).await;
    let contract::Response::LookupCommand(value) = &metadata.response else {
        panic!("lookup response");
    };
    assert!(value.command.as_ref().unwrap().retained_result.is_none());
    assert_eq!(
        value.command.as_ref().unwrap().commit.as_ref(),
        Some(&commit)
    );
    policy::revoke(&f.policy);
    assert_eq!(
        receipt.owner.with_current(&mut || {}).unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(backend
        .execute_state(context("alice"), f.lookup_request("retained-window").into())
        .await
        .is_err());
    drop(body);
    drop(receipt);
    drop(metadata);
    drop(backend);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_lookup_preserves_declared_rejection_after_later_business_mutation() {
    let f = Fixture::new(false).await;
    let rejected = invoke(&f, "original-rejection", 5, true).await;
    let Some(i::invoke_response::Result::DeclaredError(body)) =
        rejected.invocation.as_ref().unwrap().result.as_ref()
    else {
        panic!("declared rejection");
    };
    let body = body.clone();
    let inspection = rejected.command.as_ref().unwrap().clone();
    drop(rejected);
    drop(invoke(&f, "later-mutation", 2, false).await);
    let backend = f.recovery_backend().await;
    let recovered = lookup(&backend, f.lookup_request("original-rejection")).await;
    let contract::Response::LookupCommand(value) = &recovered.response else {
        panic!("lookup response");
    };
    let command = value.command.as_ref().unwrap();
    assert_eq!(command.outcome, t::CommandOutcome::Rejected as i32);
    assert_eq!(command.source, inspection.source);
    assert_eq!(
        command.retained_result,
        Some(t::command_inspection::RetainedResult::BusinessRejection(
            body
        ))
    );
    assert!(
        !command.application_state_committed
            && command.commit.is_none()
            && command.proven_abort.is_none()
    );
    assert_eq!(f.executions(), 2);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    drop(recovered);
    drop(backend);
    f.shutdown().await;
}
