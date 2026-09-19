use super::{conversion, proto, validation, RequestBudget};
use crate::management::ManagementLimits;
use latent_artifacts::{
    web::{WebMutationResult, WebOperationReceipt},
    LifecycleScope, PublicationRef, ReleaseActor, ReleaseActorKind, ReleaseLifecycleAction,
    ReleaseLifecycleReason, ReleaseOperationDisposition,
};
use latent_core::TenantId;
use tonic::Code;

fn receipt() -> WebOperationReceipt {
    WebOperationReceipt {
        format_version: 1,
        publication: PublicationRef::package(
            LifecycleScope::Tenant(TenantId("tests".into())),
            &format!("sha256:{}", "a".repeat(64)).parse().unwrap(),
        )
        .unwrap(),
        operation_id: "web-create".into(),
        action: ReleaseLifecycleAction::Publish,
        actor: ReleaseActor {
            subject: "authenticated-operator".into(),
            kind: ReleaseActorKind::Administrator,
        },
        expected_generation: 0,
        resulting_generation: 1,
        disposition: ReleaseOperationDisposition::Committed,
        reason: ReleaseLifecycleReason::Admitted,
        request_digest: format!("sha256:{}", "b".repeat(64)).parse().unwrap(),
    }
}

#[test]
fn web_requires_scoped_exact_selector_and_bounded_explicit_operation() {
    let limits = ManagementLimits::default();
    let tenant = TenantId("tests".into());
    let mut budget = RequestBudget::new::<proto::GetWebPublicationRequest>(&limits).unwrap();
    assert_eq!(
        validation::publication(None, &tenant, &mut budget, &limits)
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
    let mut selected = proto::PublicationRef {
        id: receipt().publication.id.as_str().into(),
        tenant: "foreign".into(),
    };
    assert_eq!(
        validation::publication(Some(&selected), &tenant, &mut budget, &limits)
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
    selected.tenant = "tests".into();
    validation::publication(Some(&selected), &tenant, &mut budget, &limits).unwrap();
    assert!(validation::operation(None, &mut budget, &limits, true).is_err());
    let mut operation = proto::ReleaseOperationPrecondition {
        operation_id: "create".into(),
        expected_generation: Some(0),
    };
    validation::operation(Some(&operation), &mut budget, &limits, true).unwrap();
    assert!(validation::operation(Some(&operation), &mut budget, &limits, false).is_err());
    operation.operation_id = String::with_capacity(129);
    assert_eq!(
        validation::operation(Some(&operation), &mut budget, &limits, true)
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
}

#[test]
fn web_response_preflight_reserves_owned_preview_and_audit_before_any_mutation() {
    let value = WebMutationResult {
        receipt: receipt(),
        replay: false,
    };
    let tenant = TenantId("tests".into());
    let limits = ManagementLimits::default();
    let wire = conversion::mutation(&value, &tenant, &limits, true).unwrap();
    assert!(wire.audit_ack.is_some());
    assert_eq!(
        wire.operation.unwrap().publication.unwrap().id,
        value.receipt.publication.id.as_str()
    );
    let tiny = ManagementLimits {
        max_response_bytes: 512,
        ..limits
    };
    assert_eq!(
        conversion::mutation(&value, &tenant, &tiny, true)
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
}

#[test]
fn web_domain_receipt_cannot_claim_capsule_authority_foreign_scope_or_rejection() {
    let limits = ManagementLimits::default();
    let tenant = TenantId("tests".into());
    for field in 0..5 {
        let mut value = receipt();
        match field {
            0 => value.publication.scope = LifecycleScope::LocalUnscoped,
            1 => value.publication.scope = LifecycleScope::Tenant(TenantId("foreign".into())),
            2 => value.disposition = ReleaseOperationDisposition::Rejected,
            3 => value.resulting_generation = 0,
            _ => value.reason = ReleaseLifecycleReason::PolicyDenied,
        }
        let mut budget =
            RequestBudget::for_response::<proto::WebMutationResponse>(&limits).unwrap();
        assert_eq!(
            conversion::receipt(&value, false, &tenant, &mut budget, &limits)
                .unwrap_err()
                .code(),
            Code::Internal
        );
    }
}
