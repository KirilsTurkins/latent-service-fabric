use super::*;
fn request() -> c::ControlDispatcherRequest {
    c::ControlDispatcherRequest {
        profile: Some(current_profile()),
        scope: c::DispatcherScope::Node as i32,
        operation_id: "original-resume".into(),
        action: c::DispatcherAction::Resume as i32,
        expected_generation: Some(c::DispatcherGeneration {
            owner_epoch: 9_007_199_254_740_993,
            revision: u64::MAX - 1,
        }),
    }
}
fn receipt() -> c::DispatcherOperationReceipt {
    let original = request();
    c::DispatcherOperationReceipt {
        operation_id: original.operation_id,
        receipt_id: "exact-receipt".into(),
        action: original.action,
        authenticated_operator: "host-derived-stable-actor".into(),
        actor_tenant: "tenant".into(),
        before_generation: original.expected_generation,
        after_generation: Some(c::DispatcherGeneration {
            owner_epoch: 9_007_199_254_740_993,
            revision: u64::MAX,
        }),
        observed_at_unix_millis: u64::MAX,
        clock_continuity_proven: true,
        restore_review_required: false,
        disposition: c::StateOperationDisposition::Committed as i32,
    }
}
#[test]
fn node_control_requires_explicit_scope_closed_action_original_generation_and_profile() {
    Request::from(request()).validate().unwrap();
    for case in 0..6 {
        let mut value = request();
        match case {
            0 => value.scope = 0,
            1 => value.scope = 99,
            2 => value.action = 99,
            3 => value.expected_generation.as_mut().unwrap().owner_epoch = 0,
            4 => value.expected_generation.as_mut().unwrap().revision = u64::MAX,
            _ => value.profile.as_mut().unwrap().profile = "unknown".into(),
        }
        assert!(Request::from(value).validate().is_err(), "case {case}");
    }
    let value = Request::from(request());
    assert!(value.is_management() && value.is_node_management() && value.is_recovery());
    assert!(value.tenant().is_none());
}
#[test]
fn historical_dispatcher_receipt_requires_exact_action_epoch_revision_and_safe_resume_facts() {
    let original = Request::from(c::GetDispatcherOperationRequest {
        original: Some(request()),
    });
    original.validate().unwrap();
    let response = |value| {
        Response::from(c::GetDispatcherOperationResponse {
            receipt: Some(value),
            audit_ack: Some(c::AuditAck {
                status: c::AuditAckStatus::Durable as i32,
                attempt_sequence: Some(u64::MAX),
            }),
        })
    };
    response(receipt()).validate_for(&original).unwrap();
    for case in 0..7 {
        let mut value = receipt();
        match case {
            0 => value.operation_id = "another".into(),
            1 => value.action = c::DispatcherAction::Pause as i32,
            2 => value.before_generation.as_mut().unwrap().revision -= 1,
            3 => value.after_generation.as_mut().unwrap().owner_epoch -= 1,
            4 => value.clock_continuity_proven = false,
            5 => value.restore_review_required = true,
            _ => value.disposition = c::StateOperationDisposition::Unknown as i32,
        }
        assert!(
            response(value).validate_for(&original).is_err(),
            "case {case}"
        );
    }
}
#[test]
fn dispatcher_replay_cannot_publish_and_pending_control_cannot_claim_unpaused() {
    let original = Request::from(request());
    let mut value = c::ControlDispatcherResponse {
        receipt: Some(receipt()),
        replayed: true,
        published: false,
        paused: true,
        audit_ack: Some(c::AuditAck {
            status: c::AuditAckStatus::OutcomeUnknown as i32,
            attempt_sequence: Some(9),
        }),
    };
    Response::from(value.clone())
        .validate_for(&original)
        .unwrap();
    value.published = true;
    assert!(Response::from(value).validate_for(&original).is_err());
    let query = Request::from(c::InspectDispatcherRequest {
        profile: Some(current_profile()),
        scope: c::DispatcherScope::Node as i32,
    });
    let value = c::InspectDispatcherResponse {
        dispatcher: Some(c::DispatcherSnapshot {
            generation: request().expected_generation,
            pending_control: true,
            paused: false,
            failure: c::DispatcherFailure::None as i32,
            ..Default::default()
        }),
        audit_ack: Some(c::AuditAck {
            status: c::AuditAckStatus::Durable as i32,
            attempt_sequence: Some(1),
        }),
    };
    assert!(Response::from(value).validate_for(&query).is_err());
}
