use super::*;

fn fixture(bytes: usize, duplicate: bool, rejected: bool) -> (Request, t::InvokeCommandResponse) {
    let mut command = rejection();
    command.retention = Some(t::LinkedRetention {
        record_format: "lsf-command-v3".into(),
        record_version: 3,
        payload_available: true,
        ..Default::default()
    });
    let result = if rejected {
        let body = i::DeclaredError {
            code: "account-blocked".into(),
            payload: vec![b'a'; bytes],
            media_type: "application/octet-stream".into(),
            ..Default::default()
        };
        command.retained_result = duplicate
            .then(|| t::command_inspection::RetainedResult::BusinessRejection(body.clone()));
        i::invoke_response::Result::DeclaredError(body)
    } else {
        command.outcome = t::CommandOutcome::Committed as i32;
        command.application_state_committed = true;
        let body = i::Success {
            payload: vec![b'a'; bytes],
            media_type: "application/octet-stream".into(),
            committed_state_version: Some("03".repeat(32)),
            effect_ids: vec!["effect".into()],
            ..Default::default()
        };
        command.commit = Some(t::CommitReceipt {
            command_id: command.command_id.clone(),
            attempt_id: command.attempt_id.clone(),
            transaction_id: "transaction".into(),
            committed_version: vec![3; 32],
            receipt_id: "receipt".into(),
            effect_ids: body.effect_ids.clone(),
            source: command.source.clone(),
            ..Default::default()
        });
        command.retained_result =
            duplicate.then(|| t::command_inspection::RetainedResult::Success(body.clone()));
        i::invoke_response::Result::Success(body)
    };
    let captured = command.source.as_ref().unwrap();
    let invocation = i::InvokeResponse {
        activation_id: "activation".into(),
        revision_id: captured.revision_id.clone(),
        release_digest: captured.component_digest.clone(),
        publication_id: Some(captured.publication_id.clone()),
        route_generation: captured.route_generation,
        consumption: Some(i::BudgetConsumption::default()),
        result: Some(result),
        ..Default::default()
    };
    let original = Request::from(t::InvokeCommandRequest {
        command: Some(selector()),
        ..Default::default()
    });
    (
        original,
        t::InvokeCommandResponse {
            invocation: Some(invocation),
            command: Some(command),
            replayed: false,
        },
    )
}

#[test]
fn exact_maximum_inline_success_and_rejection_fit_the_unchanged_frame_budget() {
    for rejected in [false, true] {
        let (request, response) = fixture(1024 * 1024, false, rejected);
        assert!(Response::from(response).validate_for(&request).is_ok());
        let (request, response) = fixture(1024 * 1024 + 1, false, rejected);
        assert!(Response::from(response).validate_for(&request).is_err());
    }
}

#[test]
fn explicit_retry_response_selects_only_the_linked_next_attempt() {
    for duplicate in [false, true] {
        let (_, mut response) = fixture(16, duplicate, false);
        let command = response.command.as_mut().unwrap();
        command.attempt_id = "2".into();
        command.commit.as_mut().unwrap().attempt_id = "2".into();
        let original = t::InvokeCommandRequest {
            command: Some(selector()),
            retry_attempt: Some(t::RetryAttempt {
                request_id: "retry-request".into(),
                expected_abort: Some(t::AbortFence {
                    command_id: command.command_id.clone(),
                    attempt_id: "1".into(),
                    transaction_id: "prior-transaction".into(),
                    owner_fence: vec![1; 32],
                }),
            }),
            ..Default::default()
        };
        let request = Request::from(original.clone());
        assert!(Response::from(response.clone())
            .validate_for(&request)
            .is_ok());
        for attempt in ["1", "3", "02", "17", "attempt"] {
            let mut wrong = response.clone();
            let command = wrong.command.as_mut().unwrap();
            command.attempt_id = attempt.into();
            command.commit.as_mut().unwrap().attempt_id = attempt.into();
            assert!(Response::from(wrong).validate_for(&request).is_err());
        }
        for change in ["command", "noncanonical", "exhausted"] {
            let mut wrong = original.clone();
            let abort = wrong
                .retry_attempt
                .as_mut()
                .unwrap()
                .expected_abort
                .as_mut()
                .unwrap();
            match change {
                "command" => abort.command_id = "other".into(),
                "noncanonical" => abort.attempt_id = "01".into(),
                "exhausted" => abort.attempt_id = "16".into(),
                _ => unreachable!(),
            }
            assert!(Response::from(response.clone())
                .validate_for(&Request::from(wrong))
                .is_err());
        }
    }
}

#[test]
fn legacy_equal_duplicate_bodies_remain_valid_and_malformed_duplicates_reject() {
    for rejected in [false, true] {
        let (request, mut response) = fixture(16, true, rejected);
        assert!(Response::from(response.clone())
            .validate_for(&request)
            .is_ok());
        match response
            .command
            .as_mut()
            .unwrap()
            .retained_result
            .as_mut()
            .unwrap()
        {
            t::command_inspection::RetainedResult::Success(body) => body.payload.push(b'b'),
            t::command_inspection::RetainedResult::BusinessRejection(body) => {
                body.payload.push(b'b')
            }
            _ => unreachable!(),
        }
        assert!(Response::from(response).validate_for(&request).is_err());
    }
}

#[test]
fn inline_body_requires_current_source_disposition_durability_and_available_payload() {
    for change in [
        "publication",
        "revision",
        "release",
        "route",
        "outcome",
        "durability",
        "availability",
        "missing-body",
        "kind",
    ] {
        let (request, mut response) = fixture(16, false, false);
        let invocation = response.invocation.as_mut().unwrap();
        let command = response.command.as_mut().unwrap();
        match change {
            "publication" => {
                invocation.publication_id = Some(format!("publication:sha256:{}", "b".repeat(64)))
            }
            "revision" => invocation.revision_id = "other".into(),
            "release" => invocation.release_digest = format!("sha256:{}", "b".repeat(64)),
            "route" => invocation.route_generation += 1,
            "outcome" => command.outcome = t::CommandOutcome::Rejected as i32,
            "durability" => command.metadata_durable = false,
            "availability" => command.retention.as_mut().unwrap().payload_available = false,
            "missing-body" => invocation.result = None,
            "kind" => {
                invocation.result = Some(i::invoke_response::Result::DeclaredError(
                    i::DeclaredError {
                        code: "rejected".into(),
                        media_type: "application/octet-stream".into(),
                        ..Default::default()
                    },
                ))
            }
            _ => unreachable!(),
        }
        assert!(
            Response::from(response).validate_for(&request).is_err(),
            "{change}"
        );
    }
}

#[test]
fn inline_and_duplicate_success_bodies_require_the_exact_commit_and_effect_association() {
    for duplicate in [false, true] {
        for change in [
            "command",
            "attempt",
            "source",
            "effect",
            "version",
            "missing-version",
        ] {
            let (request, mut response) = fixture(16, duplicate, false);
            let command = response.command.as_mut().unwrap();
            let commit = command.commit.as_mut().unwrap();
            match change {
                "command" => commit.command_id = "other".into(),
                "attempt" => commit.attempt_id = "other".into(),
                "source" => commit.source.as_mut().unwrap().revision_id = "other".into(),
                "effect" => commit.effect_ids[0] = "other".into(),
                "version" => commit.committed_version[0] = 4,
                "missing-version" => commit.committed_version.clear(),
                _ => unreachable!(),
            }
            assert!(
                Response::from(response).validate_for(&request).is_err(),
                "{change}"
            );
        }
    }
}

#[test]
fn inline_invocation_body_cannot_stand_in_for_a_missing_standalone_lookup_result() {
    let (_, response) = fixture(16, false, false);
    let result = Response::from(t::LookupCommandResponse {
        command: response.command,
    });
    assert!(result.validate_for(&Request::from(lookup())).is_err());
}
