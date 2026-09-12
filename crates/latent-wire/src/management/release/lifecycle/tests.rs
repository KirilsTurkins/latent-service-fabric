use super::super::super::RequestBudget;
use super::{proto, requests, response, ManagementLimits, Preflight};
use latent_artifacts::{
    LifecycleScope, ReleaseActor, ReleaseActorKind, ReleaseLifecycleAction, ReleaseLifecycleReason,
    ReleaseMutationContext, ReleaseOperationDisposition, ReleaseOperationReceipt,
};
use latent_core::{ArtifactBlobDigest, TenantId};
use tonic::Code;

fn receipt() -> ReleaseOperationReceipt {
    ReleaseOperationReceipt {
        operation_id: "attempt-1".to_owned(),
        request_digest: format!("sha256:{}", "a".repeat(64))
            .parse::<ArtifactBlobDigest>()
            .unwrap(),
        scope: LifecycleScope::Tenant(TenantId("acme".to_owned())),
        actor: ReleaseActor {
            subject: "alice".to_owned(),
            kind: ReleaseActorKind::Administrator,
        },
        action: ReleaseLifecycleAction::Publish,
        disposition: ReleaseOperationDisposition::Rejected,
        reason: ReleaseLifecycleReason::InvalidPackage,
        component_digest: None,
        package_manifest_digest: None,
        expected_generation: Some(0),
        record: None,
        policy: None,
        observed_at_unix_millis: None,
    }
}

#[test]
fn release_mutations_require_explicit_generation_without_changing_legacy_publish() {
    let limits = ManagementLimits::default();
    let check = |value: Option<&proto::ReleaseOperationPrecondition>, publish| {
        requests::operation(
            value,
            &mut RequestBudget::new::<proto::ChangeReleaseLifecycleRequest>(&limits).unwrap(),
            &limits,
            publish,
        )
    };
    assert!(check(None, true).is_ok());
    assert_eq!(
        check(None, false).unwrap_err().code(),
        Code::InvalidArgument
    );
    let mut value = proto::ReleaseOperationPrecondition {
        operation_id: "known-op".to_owned(),
        expected_generation: None,
    };
    assert!(check(Some(&value), true).is_err());
    value.expected_generation = Some(0);
    assert!(check(Some(&value), true).is_ok());
    assert!(check(Some(&value), false).is_err());
    value.expected_generation = Some(1);
    assert!(check(Some(&value), true).is_err());
    assert!(check(Some(&value), false).is_ok());
    value.operation_id = String::with_capacity(129);
    value.operation_id.push_str("short");
    assert_eq!(
        check(Some(&value), false).unwrap_err().code(),
        Code::ResourceExhausted
    );
}

#[test]
fn lifecycle_actions_cannot_request_restore_or_unknown_reason() {
    use proto::{ReleaseLifecycleAction as A, ReleaseLifecycleReason as R};
    assert!(super::conversion::change(A::Revoke as i32, R::SecurityIncident as i32).is_ok());
    for (action, reason) in [
        (A::Publish as i32, R::Admitted as i32),
        (A::Retire as i32, R::SecurityIncident as i32),
        (A::RenewEvidence as i32, R::EvidenceRenewed as i32),
        (0, 0),
        (i32::MAX, i32::MAX),
    ] {
        assert_eq!(
            super::conversion::change(action, reason)
                .unwrap_err()
                .code(),
            Code::InvalidArgument
        );
    }
}

#[test]
fn historical_operation_output_rejects_foreign_scope_and_spare_capacity() {
    let tenant = TenantId("acme".to_owned());
    let limits = ManagementLimits::default();
    let original = receipt();
    let wire = response::operation(&original, &tenant, &limits).unwrap();
    assert_eq!(wire.actor.unwrap().subject, "alice");
    assert!(wire.component_digest.is_none() && wire.record.is_none());
    for scope in [
        LifecycleScope::LocalUnscoped,
        LifecycleScope::Tenant(TenantId("foreign".to_owned())),
    ] {
        let mut value = receipt();
        value.scope = scope;
        assert_eq!(
            response::operation(&value, &tenant, &limits)
                .unwrap_err()
                .code(),
            Code::Internal
        );
    }
    let mut value = receipt();
    value.actor.subject = String::with_capacity(513);
    value.actor.subject.push_str("alice");
    assert_eq!(
        response::operation(&value, &tenant, &limits)
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
}

#[test]
fn rejected_operation_preflight_binds_actor_and_checks_error_budget() {
    let tenant = TenantId("acme".to_owned());
    let limits = ManagementLimits::default();
    let original = receipt();
    let context = ReleaseMutationContext {
        scope: original.scope.clone(),
        actor: original.actor.clone(),
        operation: None,
    };
    let error = latent_core::PlatformError {
        code: latent_core::PlatformErrorCode::AdmissionRejected,
        message: "private /host/path".to_owned(),
        retryable: false,
        details: Vec::new(),
    };
    fn preview<'a>(
        value: &'a ReleaseOperationReceipt,
        error: &'a latent_core::PlatformError,
    ) -> latent_artifacts::ReleaseOperationPreview<'a> {
        latent_artifacts::ReleaseOperationPreview {
            receipt: value,
            release: None,
            failure: Some(error),
        }
    }
    let mut checked = Preflight::new(
        &tenant,
        &limits,
        &context,
        None,
        ReleaseLifecycleAction::Publish,
    );
    checked.preview(preview(&original, &error)).unwrap();
    assert!(!format!("{:?}", checked.failure).contains("/host/path"));
    assert!(checked.preview(preview(&original, &error)).is_err());
    let mut changed = receipt();
    changed.actor.subject = "mallory".to_owned();
    let mut checked = Preflight::new(
        &tenant,
        &limits,
        &context,
        None,
        ReleaseLifecycleAction::Publish,
    );
    assert!(checked.preview(preview(&changed, &error)).is_err());
    let mut tiny = limits;
    tiny.max_response_bytes = 512;
    let mut checked = Preflight::new(
        &tenant,
        &tiny,
        &context,
        None,
        ReleaseLifecycleAction::Publish,
    );
    assert!(checked.preview(preview(&original, &error)).is_err());
}
