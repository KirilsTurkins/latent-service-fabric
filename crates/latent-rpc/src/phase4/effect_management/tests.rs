use super::*;
use crate::phase4::{current_profile, Request, Response};

fn target() -> c::InspectNamespaceRequest {
    c::InspectNamespaceRequest {
        profile: Some(current_profile()),
        namespace: Some(t::NamespaceSelector {
            tenant: "tenant".into(),
            namespace: "app".into(),
            incarnation: "1".into(),
        }),
        authorization_publication: Some(c::PublicationRef {
            tenant: "tenant".into(),
            id: format!("publication:sha256:{}", "a".repeat(64)),
        }),
    }
}
fn original() -> c::PlanEffectMutationRequest {
    let target = target();
    c::PlanEffectMutationRequest {
        effect: Some(t::GetEffectRequest {
            profile: target.profile,
            authorization_publication: target.authorization_publication,
            command: Some(t::CommandSelector {
                namespace: target.namespace,
                operation: "save".into(),
                entity: None,
                client_key: "original-command".into(),
                shared_recovery_scope: None,
            }),
            effect_id: "b".repeat(64),
        }),
        operation_id: "original-management".into(),
        mutation: c::StateMutationKind::TerminateEffect as i32,
        expected_version: vec![1; 32],
        expected_policy_digest: format!("sha256:{}", "c".repeat(64)),
        reason: "operator declaration".into(),
        retry_delay_millis: 0,
    }
}
fn plan() -> c::EffectManagementPlan {
    c::EffectManagementPlan {
        original: Some(original()),
        plan_digest: vec![2; 32],
        management_sequence: 1,
        owner_epoch: 0,
        claim_generation: 0,
        dispatch_attempt: 0,
        expires_at_unix_millis: 2000,
        prepared_at_unix_millis: 1000,
        before: t::EffectDisposition::Pending as i32,
        safety: c::EffectPlanSafety::AdministratorDeclared as i32,
        dedup_valid_until_unix_millis: None,
    }
}
fn mutation() -> c::MutateStateRequest {
    let original = original();
    c::MutateStateRequest {
        namespace: Some(target()),
        operation_id: original.operation_id,
        mutation: original.mutation,
        record_id: Some(original.effect.unwrap().effect_id),
        expected_version: original.expected_version,
        expected_policy_digest: original.expected_policy_digest,
        reason: original.reason,
        effect_plan: Some(plan()),
    }
}
fn receipt() -> c::StateOperationReceipt {
    let original = original();
    c::StateOperationReceipt {
        operation_id: original.operation_id,
        receipt_id: "receipt".into(),
        mutation: original.mutation,
        namespace: target().namespace,
        authenticated_operator: "operator".into(),
        before_version: original.expected_version,
        after_version: vec![3; 32],
        completed_at_unix_millis: 1500,
        record_id: Some(original.effect.unwrap().effect_id),
        policy_digest: original.expected_policy_digest,
        disposition: c::StateOperationDisposition::Committed as i32,
        effect: Some(c::EffectManagementReceiptDetails {
            original_plan: Some(plan()),
            before: t::EffectDisposition::Pending as i32,
            after: t::EffectDisposition::DeadLettered as i32,
            fact: c::EffectManagementFact::AdministratorTerminated as i32,
            provider_receipt: None,
            provider_observed_at_unix_millis: None,
        }),
    }
}

#[test]
fn applying_plan_preserves_original_cas_action_reason_and_publication() {
    let valid = mutation();
    assert!(Request::from(valid.clone()).validate().is_ok());
    let mut variants = vec![valid.clone(); 5];
    variants[0].expected_version[0] = 7;
    variants[1].mutation = c::StateMutationKind::ReconcileEffect as i32;
    variants[2].reason = "replacement".into();
    variants[3]
        .namespace
        .as_mut()
        .unwrap()
        .authorization_publication
        .as_mut()
        .unwrap()
        .id = format!("publication:sha256:{}", "d".repeat(64));
    variants[4].effect_plan = None;
    for changed in variants {
        assert!(Request::from(changed).validate().is_err());
    }
}

#[test]
fn historical_receipt_keeps_expired_plan_and_independent_unknown_audit() {
    let request = Request::from(c::GetStateOperationReceiptRequest {
        namespace: Some(target()),
        operation_id: original().operation_id,
        original_effect_plan: Some(plan()),
    });
    let response = Response::from(c::GetStateOperationReceiptResponse {
        receipt: Some(receipt()),
        namespace_receipt: None,
        audit_ack: Some(c::AuditAck {
            status: c::AuditAckStatus::OutcomeUnknown as i32,
            ..Default::default()
        }),
    });
    assert!(request.validate().is_ok());
    assert!(response.validate_for(&request).is_ok());
    let Request::GetStateOperationReceipt(mut changed) = request else {
        unreachable!()
    };
    changed
        .original_effect_plan
        .as_mut()
        .unwrap()
        .original
        .as_mut()
        .unwrap()
        .reason = "replacement".into();
    assert!(response
        .validate_for(&Request::GetStateOperationReceipt(changed))
        .is_err());
}

#[test]
fn fresh_read_publication_does_not_rewrite_original_plan() {
    let mut current = target();
    current.authorization_publication.as_mut().unwrap().id =
        format!("publication:sha256:{}", "d".repeat(64));
    let request = Request::from(c::GetStateOperationReceiptRequest {
        namespace: Some(current),
        operation_id: original().operation_id,
        original_effect_plan: Some(plan()),
    });
    assert!(request.validate().is_ok());
    assert!(Response::from(c::GetStateOperationReceiptResponse {
        receipt: Some(receipt()),
        namespace_receipt: None,
        audit_ack: None
    })
    .validate_for(&request)
    .is_ok());
}

#[test]
fn lookup_and_dedup_safety_need_original_attempt_and_finite_horizon() {
    let mut value = plan();
    value.original.as_mut().unwrap().mutation = c::StateMutationKind::ReconcileEffect as i32;
    value.safety = c::EffectPlanSafety::ProviderReceiptLookup as i32;
    value.before = t::EffectDisposition::UncertainAfterDispatch as i32;
    let validate = |value: c::EffectManagementPlan| {
        Response::from(c::PlanEffectMutationResponse {
            plan: Some(value.clone()),
            replayed: false,
            audit_ack: None,
        })
        .validate_for(&Request::from(value.original.unwrap()))
    };
    assert!(validate(value.clone()).is_err());
    value.owner_epoch = 1;
    value.claim_generation = 2;
    value.dispatch_attempt = 1;
    assert!(validate(value.clone()).is_ok());
    value.original.as_mut().unwrap().mutation = c::StateMutationKind::RetryKnownFailedEffect as i32;
    value.original.as_mut().unwrap().retry_delay_millis = 100;
    value.safety = c::EffectPlanSafety::QualifiedDeduplication as i32;
    assert!(validate(value.clone()).is_err());
    value.dedup_valid_until_unix_millis = Some(3000);
    assert!(validate(value.clone()).is_ok());
    value.management_sequence = 0;
    assert!(validate(value).is_err());
}

#[test]
fn provider_confirmation_cannot_be_an_administrator_declaration() {
    let request = Request::from(mutation());
    let mut response = c::MutateStateResponse {
        receipt: Some(receipt()),
        audit_ack: None,
        replayed: false,
    };
    assert!(Response::from(response.clone())
        .validate_for(&request)
        .is_ok());
    response
        .receipt
        .as_mut()
        .unwrap()
        .effect
        .as_mut()
        .unwrap()
        .provider_receipt = Some("unverified".into());
    assert!(Response::from(response).validate_for(&request).is_err());
}

#[test]
fn absent_old_version_and_hidden_large_buffer_cannot_authorize_planning() {
    for bytes in [Vec::new(), vec![0; 32], vec![1; 31], vec![1; 33]] {
        let mut value = original();
        value.expected_version = bytes;
        assert!(Request::from(value).validate().is_err());
    }
    let mut value = original();
    value.reason.reserve(crate::phase4::MAX_REQUEST_BYTES + 1);
    assert_eq!(
        Request::from(value).validate(),
        Err(ValidationError::Capacity)
    );
}
