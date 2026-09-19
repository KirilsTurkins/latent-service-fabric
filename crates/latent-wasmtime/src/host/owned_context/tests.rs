use std::mem::size_of;

use latent_core::{ActivationId, Metadata, PrincipalKind};

use super::{fits, metadata, text, ActivationHostContext};
use crate::host::request_context::{context_charge, validate_request_context};

mod fixture;

fn web_request() -> latent_executor::ExecutionRequest {
    let mut request = fixture::request();
    request.activation.target.contract.0 = latent_artifacts::web::WEB_CONTRACT.into();
    request.activation.target.function.0 = "handle".into();
    let publication = format!("publication:sha256:{}", "a".repeat(64))
        .parse()
        .unwrap();
    request.prepared.key.publication = Some(publication);
    request.activation.resolved_revision = Some(latent_routing::ResolvedRevision {
        target: request.activation.target.clone(),
        revision: latent_core::RevisionId("web-revision".into()),
        release: request.prepared.key.release.clone(),
        publication: request.prepared.key.publication.clone(),
        route_generation: latent_core::RouteGeneration(1),
        attributes: Metadata::new(),
    });
    request.activation.metadata.insert(
        crate::host::web_identity::KEY.into(),
        "caller-cannot-select-hydration-publication".into(),
    );
    request
}

#[test]
fn web_asset_identity_comes_from_the_prepared_revision_not_caller_metadata() {
    let request = web_request();
    let expected = request
        .prepared
        .key
        .publication
        .as_ref()
        .unwrap()
        .to_string();
    let charge = context_charge(&request, usize::MAX).unwrap().charged_bytes;
    validate_request_context(&request, charge).unwrap();
    assert!(validate_request_context(&request, charge - 1).is_err());
    let context = ActivationHostContext::from_request(request, None);
    assert_eq!(context.metadata[crate::host::web_identity::KEY], expected);
    assert_eq!(context.metadata["metadata"], "value");
}

#[test]
fn unselected_or_mismatched_execution_cannot_spoof_the_reserved_web_identity() {
    for variant in 0..4 {
        let mut request = web_request();
        match variant {
            0 => request.activation.target.contract.0 = "tests:other/api@1.0.0".into(),
            1 => request.prepared.key.publication = None,
            2 => request.activation.resolved_revision = None,
            _ => {
                request
                    .activation
                    .resolved_revision
                    .as_mut()
                    .unwrap()
                    .publication = None
            }
        }
        let context = ActivationHostContext::from_request(request, None);
        assert!(!context
            .metadata
            .contains_key(crate::host::web_identity::KEY));
        assert_eq!(context.metadata["metadata"], "value");
    }
}

#[test]
fn web_identity_map_entry_is_charged_before_context_ownership_transfer() {
    let mut request = web_request();
    let selected = context_charge(&request, usize::MAX).unwrap().charged_bytes;
    request.activation.target.function.0 = "other!".into();
    let unselected = context_charge(&request, usize::MAX).unwrap().charged_bytes;
    assert!(selected >= unselected + 4096);
}

fn allocation(value: &String) -> (usize, usize) {
    (value.as_ptr() as usize, value.capacity())
}

fn surplus(value: &str) -> String {
    let mut text = String::with_capacity(4096);
    text.push_str(value);
    text
}

#[test]
fn validated_context_moves_every_field_and_ordinary_backing_buffer() {
    let request = fixture::request();
    let expected = request.activation.clone();
    let before = strings(&request).map(allocation);
    let map_key = request.activation.metadata.keys().next().unwrap();
    let key_node = std::ptr::from_ref(map_key) as usize;
    let key_allocation = allocation(map_key);
    let charged = context_charge(&request, usize::MAX).unwrap().charged_bytes;
    validate_request_context(&request, charged).unwrap();
    let context = ActivationHostContext::from_request(request, Some(456));

    assert_eq!(context.activation_id, expected.activation_id);
    assert_eq!(context.root_activation_id, expected.root_activation_id);
    assert_eq!(context.parent_activation_id, expected.parent_activation_id);
    assert_eq!(context.principal, expected.principal);
    assert_eq!(context.trace_id, expected.trace.trace_id.0);
    assert_eq!(context.span_id, expected.trace.span_id.0);
    assert_eq!(context.trace_flags, expected.trace.trace_flags);
    assert_eq!(context.baggage, expected.trace.baggage);
    assert_eq!(context.metadata, expected.metadata);
    // The ledger projection wins over the request's legacy diagnostic value.
    assert_eq!(context.deadline_unix_millis, Some(456));
    assert_eq!(context_strings(&context).map(allocation), before);
    let moved_key = context.metadata.keys().next().unwrap();
    assert_eq!(std::ptr::from_ref(moved_key) as usize, key_node);
    assert_eq!(allocation(moved_key), key_allocation);
}

#[test]
fn capacity_threshold_is_inclusive_and_excess_has_a_hard_postcondition() {
    for value in ["", "x", "é𐐀"] {
        let limit = 2 * (value.len() + size_of::<String>());
        let mut exact = "x".repeat(limit).into_boxed_str().into_string();
        exact.clear();
        exact.push_str(value);
        assert_eq!(exact.capacity(), limit);
        let original = allocation(&exact);
        assert!(fits(&exact));
        let moved = text(exact);
        assert_eq!(allocation(&moved), original);
        let mut over = "x".repeat(limit + 1).into_boxed_str().into_string();
        over.clear();
        over.push_str(value);
        assert!(!fits(&over));
        let compacted = text(over);
        assert_eq!(compacted, value);
        assert_eq!(compacted.capacity(), compacted.len());
    }
}

#[test]
fn spare_capacity_does_not_change_the_existing_logical_admission_boundary() {
    let mut request = fixture::request();
    let baseline = context_charge(&request, usize::MAX).unwrap().charged_bytes;
    // Equivalent to the accepted duplicate-singular-field Prost shape proven
    // in latent-wire: a long value is cleared, then replaced by a short ID.
    let mut reused = "x".repeat(4096).into_boxed_str().into_string();
    reused.clear();
    reused.push_str(&request.activation.activation_id.0);
    assert_eq!(reused.capacity(), 4096);
    request.activation.activation_id.0 = reused;
    request.activation.root_activation_id.0 = surplus("root");
    request.activation.parent_activation_id = Some(ActivationId(surplus("parent")));
    request.activation.principal.subject = surplus("subject");
    request.activation.principal.tenant.as_mut().unwrap().0 = surplus("tenant");
    request.activation.principal.service.as_mut().unwrap().0 = surplus("service");
    request.activation.trace.trace_id.0 = surplus("trace");
    request.activation.trace.span_id.0 = surplus("span");
    request.activation.principal.claims = [(surplus("claim"), surplus("allowed"))].into();
    request.activation.trace.baggage = [(surplus("baggage"), surplus("value"))].into();
    request.activation.metadata = [(surplus("metadata"), surplus("value"))].into();
    assert_eq!(
        context_charge(&request, usize::MAX).unwrap().charged_bytes,
        baseline
    );
    assert!(validate_request_context(&request, baseline - 1).is_err());
    validate_request_context(&request, baseline).unwrap();
    validate_request_context(&request, baseline + 1).unwrap();
    let expected = request.activation.clone();
    let context = ActivationHostContext::from_request(request, None);
    assert_eq!(context.principal, expected.principal);
    assert_eq!(context.principal.kind, PrincipalKind::Service);
    assert_eq!(context.activation_id, expected.activation_id);
    assert_eq!(context.metadata, expected.metadata);
    assert_eq!(context.baggage, expected.trace.baggage);
    for value in context_strings(&context) {
        assert_eq!(value.capacity(), value.len());
    }
    for map in [
        &context.principal.claims,
        &context.baggage,
        &context.metadata,
    ] {
        for (key, value) in map {
            assert_eq!(key.capacity(), key.len());
            assert_eq!(value.capacity(), value.len());
        }
    }
}

#[test]
fn excessive_values_keep_map_nodes_and_ordinary_keys_in_place() {
    let values: Metadata = [("key".to_owned(), surplus("value"))].into();
    let key = values.keys().next().unwrap();
    let key_node = std::ptr::from_ref(key) as usize;
    let original = allocation(key);
    let moved = metadata(values);
    let (key, value) = moved.first_key_value().unwrap();
    assert_eq!(std::ptr::from_ref(key) as usize, key_node);
    assert_eq!(allocation(key), original);
    assert_eq!(value, "value");
    assert_eq!(value.capacity(), value.len());
}

#[test]
fn excessive_keys_rebuild_only_their_map_and_preserve_values_and_order() {
    let values: Metadata = [
        (surplus("z"), "last".to_owned()),
        ("a".to_owned(), "first".to_owned()),
    ]
    .into();
    let expected = values.clone();
    let first = allocation(values.get("a").unwrap());
    let last = allocation(values.get("z").unwrap());
    let normal_key = allocation(values.keys().next().unwrap());
    let moved = metadata(values);
    assert_eq!(moved, expected);
    assert_eq!(allocation(moved.get("a").unwrap()), first);
    assert_eq!(allocation(moved.get("z").unwrap()), last);
    assert_eq!(allocation(moved.keys().next().unwrap()), normal_key);
    assert_eq!(moved.last_key_value().unwrap().0.capacity(), 1);
    assert!(metadata(Metadata::new()).is_empty());
}

fn strings(request: &latent_executor::ExecutionRequest) -> [&String; 11] {
    let value = &request.activation;
    [
        &value.activation_id.0,
        &value.root_activation_id.0,
        &value.parent_activation_id.as_ref().unwrap().0,
        &value.principal.subject,
        &value.principal.tenant.as_ref().unwrap().0,
        &value.principal.service.as_ref().unwrap().0,
        &value.trace.trace_id.0,
        &value.trace.span_id.0,
        value.principal.claims.get("claim").unwrap(),
        value.trace.baggage.get("baggage").unwrap(),
        value.metadata.get("metadata").unwrap(),
    ]
}

fn context_strings(value: &ActivationHostContext) -> [&String; 11] {
    [
        &value.activation_id.0,
        &value.root_activation_id.0,
        &value.parent_activation_id.as_ref().unwrap().0,
        &value.principal.subject,
        &value.principal.tenant.as_ref().unwrap().0,
        &value.principal.service.as_ref().unwrap().0,
        &value.trace_id,
        &value.span_id,
        value.principal.claims.get("claim").unwrap(),
        value.baggage.get("baggage").unwrap(),
        value.metadata.get("metadata").unwrap(),
    ]
}
