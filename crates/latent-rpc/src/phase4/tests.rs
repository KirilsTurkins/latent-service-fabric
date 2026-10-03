use super::*;
use crate::{control::v1 as c, invocation::v1 as i, transaction::v1 as t};

fn namespace() -> t::NamespaceSelector {
    t::NamespaceSelector {
        tenant: "tenant".into(),
        namespace: "app".into(),
        incarnation: "1".into(),
    }
}
fn publication() -> c::PublicationRef {
    c::PublicationRef {
        id: format!("publication:sha256:{}", "a".repeat(64)),
        tenant: "tenant".into(),
    }
}
fn inspect() -> c::InspectNamespaceRequest {
    c::InspectNamespaceRequest {
        profile: Some(current_profile()),
        namespace: Some(namespace()),
        authorization_publication: Some(publication()),
    }
}
fn selector() -> t::CommandSelector {
    t::CommandSelector {
        namespace: Some(namespace()),
        operation: "save".into(),
        entity: Some("document with spaces".into()),
        client_key: "original".into(),
        shared_recovery_scope: None,
    }
}
fn lookup() -> t::LookupCommandRequest {
    t::LookupCommandRequest {
        profile: Some(current_profile()),
        command: Some(selector()),
        attempt_id: None,
        authorization_publication: Some(publication()),
    }
}
fn source() -> t::SourceIdentity {
    let digest = format!("sha256:{}", "a".repeat(64));
    t::SourceIdentity {
        publication_id: publication().id,
        revision_id: "revision".into(),
        release_digest: digest.clone(),
        component_digest: digest.clone(),
        contract_digest: digest.clone(),
        route_generation: 1,
        state_schema: digest,
        input_format: "raw-v1".into(),
        result_format: "raw-v1".into(),
    }
}
fn rejection() -> t::CommandInspection {
    let requested = selector();
    t::CommandInspection {
        key: Some(t::CommandKey {
            namespace: requested.namespace,
            recovery_scope: "host-derived-caller".into(),
            operation: requested.operation,
            entity: requested.entity,
            client_key: requested.client_key,
        }),
        command_id: "command".into(),
        attempt_id: "attempt".into(),
        fingerprint_sha256: vec![7; 32],
        outcome: t::CommandOutcome::Rejected as i32,
        metadata_durable: true,
        application_state_committed: false,
        source: Some(source()),
        retained_result: Some(t::command_inspection::RetainedResult::BusinessRejection(
            i::DeclaredError {
                code: "account-blocked".into(),
                message: "original decision".into(),
                payload: vec![],
                media_type: "application/octet-stream".into(),
                metadata: std::collections::HashMap::default(),
            },
        )),
        ..Default::default()
    }
}
fn rejected_response() -> Response {
    Response::from(t::LookupCommandResponse {
        command: Some(rejection()),
    })
}
fn quota() -> c::NamespaceQuota {
    c::NamespaceQuota {
        state_keys: 4096,
        state_bytes: 8_388_608,
        result_rows: 4096,
        result_bytes: 8_388_608,
        effect_rows: 4096,
        effect_bytes: 8_388_608,
        payload_bytes: 8_388_608,
        recovery_bytes: 1_048_576,
    }
}
fn mutation() -> c::MutateNamespaceRequest {
    c::MutateNamespaceRequest {
        namespace: Some(inspect()),
        operation_id: "original-operation".into(),
        mutation: c::NamespaceMutationKind::Create as i32,
        expected_generation: Some(0),
        configuration: Some(c::NamespaceConfiguration {
            state_schema: "schema".into(),
            quota: Some(quota()),
        }),
    }
}

#[test]
fn current_read_publication_is_required_without_changing_command_selector() {
    let mut request = lookup();
    let original = request.command.clone();
    request.authorization_publication = None;
    assert_eq!(
        Request::from(request.clone()).validate(),
        Err(ValidationError::Shape)
    );
    request.authorization_publication = Some(publication());
    assert!(Request::from(request.clone()).validate().is_ok());
    request.authorization_publication.as_mut().unwrap().id =
        format!("publication:sha256:{}", "b".repeat(64));
    assert!(Request::from(request.clone()).validate().is_ok());
    assert_eq!(request.command, original);
}
#[test]
fn cross_tenant_current_publication_fails_before_lookup() {
    let mut request = lookup();
    request.authorization_publication.as_mut().unwrap().tenant = "other".into();
    assert_eq!(
        Request::from(request).validate(),
        Err(ValidationError::Association)
    );
}
#[test]
fn exact_negotiated_profile_has_no_unknown_fallback() {
    let mut request = lookup();
    request.profile.as_mut().unwrap().profile = "lsf-transaction-v2".into();
    assert_eq!(
        Request::from(request).validate(),
        Err(ValidationError::UnsupportedProfile)
    );
}
#[test]
fn incarnation_is_positive_canonical_lossless_unsigned64() {
    for invalid in ["", "0", "01", "-1", "18446744073709551616"] {
        let mut request = lookup();
        request
            .command
            .as_mut()
            .unwrap()
            .namespace
            .as_mut()
            .unwrap()
            .incarnation = invalid.into();
        assert!(Request::from(request).validate().is_err());
    }
    let mut request = lookup();
    request
        .command
        .as_mut()
        .unwrap()
        .namespace
        .as_mut()
        .unwrap()
        .incarnation = u64::MAX.to_string();
    assert!(Request::from(request).validate().is_ok());
}
#[test]
fn create_preserves_present_zero_and_requires_finite_configuration() {
    assert!(Request::from(mutation()).validate().is_ok());
    let mut missing = mutation();
    missing.expected_generation = None;
    assert!(Request::from(missing).validate().is_err());
    let mut unlimited = mutation();
    unlimited
        .configuration
        .as_mut()
        .unwrap()
        .quota
        .as_mut()
        .unwrap()
        .recovery_bytes = 0;
    assert!(Request::from(unlimited).validate().is_err());
    let mut transition = mutation();
    transition.mutation = c::NamespaceMutationKind::Retire as i32;
    transition.expected_generation = Some(4);
    assert!(Request::from(transition.clone()).validate().is_err());
    transition.configuration = None;
    assert!(Request::from(transition).validate().is_ok());
}
#[test]
fn retained_allocation_capacity_is_charged_before_encoded_length() {
    let mut request = lookup();
    let mut large = String::with_capacity(MAX_REQUEST_BYTES + 1);
    large.push_str("save");
    request.command.as_mut().unwrap().operation = large;
    assert_eq!(
        Request::from(request).validate(),
        Err(ValidationError::Capacity)
    );
}
#[test]
fn business_rejection_remains_durable_without_application_commit() {
    assert!(rejected_response()
        .validate_for(&Request::from(lookup()))
        .is_ok());
    let mut rejected = rejection();
    rejected.application_state_committed = true;
    assert!(Response::from(t::LookupCommandResponse {
        command: Some(rejected)
    })
    .validate_for(&Request::from(lookup()))
    .is_err());
}
#[test]
fn unknown_expired_and_in_progress_never_supply_abort_fence() {
    for outcome in [
        t::CommandOutcome::Unknown,
        t::CommandOutcome::Expired,
        t::CommandOutcome::InProgress,
    ] {
        let mut value = rejection();
        value.outcome = outcome as i32;
        value.retained_result = None;
        value.proven_abort = Some(t::AbortFence {
            command_id: value.command_id.clone(),
            attempt_id: value.attempt_id.clone(),
            transaction_id: "tx".into(),
            owner_fence: vec![1],
        });
        assert!(Response::from(t::LookupCommandResponse {
            command: Some(value)
        })
        .validate_for(&Request::from(lookup()))
        .is_err());
    }
}
#[test]
fn technical_abort_requires_exact_attempt_fence() {
    let mut value = rejection();
    value.outcome = t::CommandOutcome::Aborted as i32;
    value.retained_result = None;
    let request = Request::from(lookup());
    assert!(Response::from(t::LookupCommandResponse {
        command: Some(value.clone())
    })
    .validate_for(&request)
    .is_err());
    value.proven_abort = Some(t::AbortFence {
        command_id: value.command_id.clone(),
        attempt_id: value.attempt_id.clone(),
        transaction_id: "tx".into(),
        owner_fence: vec![1],
    });
    assert!(Response::from(t::LookupCommandResponse {
        command: Some(value.clone())
    })
    .validate_for(&request)
    .is_ok());
    value.proven_abort.as_mut().unwrap().attempt_id = "other".into();
    assert!(Response::from(t::LookupCommandResponse {
        command: Some(value)
    })
    .validate_for(&request)
    .is_err());
}
#[test]
fn response_cannot_substitute_command_body_or_requested_attempt() {
    let mut value = rejection();
    value.key.as_mut().unwrap().client_key = "new-key".into();
    assert_eq!(
        Response::from(t::LookupCommandResponse {
            command: Some(value)
        })
        .validate_for(&Request::from(lookup())),
        Err(ValidationError::Association)
    );
    let mut request = lookup();
    request.attempt_id = Some("different-attempt".into());
    assert!(rejected_response()
        .validate_for(&Request::from(request))
        .is_err());
}
#[test]
fn compatible_current_publication_preserves_original_retained_source() {
    let mut request = lookup();
    request.authorization_publication.as_mut().unwrap().id =
        format!("publication:sha256:{}", "b".repeat(64));
    assert!(rejected_response()
        .validate_for(&Request::from(request))
        .is_ok());
}
#[test]
fn short_and_filtered_empty_pages_retain_explicit_continuation() {
    let original = Request::from(c::SelectEntityRequest {
        namespace: Some(inspect()),
        prefix: None,
        page: Some(t::PageRequest {
            limit: 128,
            cursor: Some(vec![1]),
        }),
    });
    let response = Response::from(c::SelectEntityResponse {
        entities: vec![],
        page: Some(t::PageResponse {
            next_cursor: Some(vec![2]),
            returned_count: 0,
            encoded_bytes: 0,
        }),
    });
    assert!(response.validate_for(&original).is_ok());
    let duplicate = Response::from(c::SelectEntityResponse {
        entities: vec![],
        page: Some(t::PageResponse {
            next_cursor: Some(vec![1]),
            returned_count: 0,
            encoded_bytes: 0,
        }),
    });
    assert!(duplicate.validate_for(&original).is_err());
}
#[test]
fn namespaces_reject_unknown_mutation_and_unbounded_page_requests() {
    let mut value = mutation();
    value.mutation = 991;
    assert!(Request::from(value).validate().is_err());
    for limit in [0, 129, u32::MAX] {
        assert!(Request::from(c::SelectEntityRequest {
            namespace: Some(inspect()),
            prefix: None,
            page: Some(t::PageRequest {
                limit,
                cursor: None
            })
        })
        .validate()
        .is_err());
    }
}
#[test]
fn operation_receipt_recovery_requires_one_associated_receipt() {
    let request = Request::from(c::GetStateOperationReceiptRequest {
        namespace: Some(inspect()),
        operation_id: "original".into(),
    });
    assert!(
        Response::from(c::GetStateOperationReceiptResponse::default())
            .validate_for(&request)
            .is_err()
    );
    let receipt = c::NamespaceOperationReceipt {
        operation_id: "original".into(),
        receipt_id: "receipt".into(),
        mutation: c::NamespaceMutationKind::Quiesce as i32,
        namespace: Some(namespace()),
        authenticated_operator: "operator".into(),
        before_generation: Some(2),
        after_generation: 3,
        status: c::NamespaceStatus::Quiescing as i32,
        state_schema: "schema".into(),
        disposition: c::StateOperationDisposition::Committed as i32,
    };
    assert!(Response::from(c::GetStateOperationReceiptResponse {
        receipt: None,
        namespace_receipt: Some(receipt.clone())
    })
    .validate_for(&request)
    .is_ok());
    let mut other = receipt;
    other.operation_id = "new-operation".into();
    assert!(Response::from(c::GetStateOperationReceiptResponse {
        receipt: None,
        namespace_receipt: Some(other)
    })
    .validate_for(&request)
    .is_err());
}
