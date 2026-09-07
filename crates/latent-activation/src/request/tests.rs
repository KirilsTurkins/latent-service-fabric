use latent_core::{ActivationId, PlatformErrorCode, ReleaseDigest, RevisionId, RouteGeneration};
use latent_routing::ResolvedRevision;

use super::*;

mod support;
use support::request;

#[derive(Default)]
struct Ids(AtomicU64);
impl ActivationIdSource for Ids {
    fn next_id(&self) -> Result<ActivationId, PlatformError> {
        Ok(ActivationId(format!(
            "assigned-{}",
            self.0.fetch_add(1, Ordering::Relaxed)
        )))
    }
}

fn builder(limits: ActivationRequestLimits) -> (ActivationRequestBuilder, Arc<Ids>) {
    let ids = Arc::new(Ids::default());
    (
        ActivationRequestBuilder::new(limits, ids.clone()).expect("builder"),
        ids,
    )
}

#[test]
fn missing_identity_is_assigned_once_and_root_uses_that_identity() {
    let (builder, ids) = builder(ActivationRequestLimits::default());
    let envelope = builder.build(request()).expect("new root");
    assert_eq!(envelope.activation_id.0, "assigned-0");
    assert_eq!(envelope.root_activation_id, envelope.activation_id);
    assert_eq!(envelope.parent_activation_id, None);
    assert_eq!(envelope.resolved_revision, None);
    assert_eq!(ids.0.load(Ordering::Relaxed), 1);
}

#[test]
fn explicit_correlation_and_trusted_context_are_preserved_without_ancestry_lookup() {
    let (builder, ids) = builder(ActivationRequestLimits::default());
    let mut input = request();
    input.activation_id = Some(ActivationId("chosen".to_owned()));
    input.root_activation_id = Some(ActivationId("unknown-root".to_owned()));
    input.parent_activation_id = Some(ActivationId("unknown-parent".to_owned()));
    input.idempotency_key = Some(IdempotencyKey("opaque-key".to_owned()));
    input.retry_attempt = 3;
    input
        .metadata
        .insert("note".to_owned(), "preserve spaces and π".to_owned());
    input
        .trace
        .baggage
        .insert("caller".to_owned(), "baggage".to_owned());
    input
        .principal
        .claims
        .insert("scope".to_owned(), "diagnostic only".to_owned());
    let expected = input.clone();
    let envelope = builder.build(input).expect("bounded opaque lineage");
    assert_eq!(ActivationRequest::from_envelope(envelope), expected);
    assert_eq!(ids.0.load(Ordering::Relaxed), 0);
}

#[test]
fn present_empty_and_invalid_lineage_never_become_absent() {
    let (builder, ids) = builder(ActivationRequestLimits::default());
    for field in 0..3 {
        let mut input = request();
        match field {
            0 => input.activation_id = Some(ActivationId(String::new())),
            1 => input.root_activation_id = Some(ActivationId(String::new())),
            _ => {
                input.root_activation_id = Some(ActivationId("root".to_owned()));
                input.parent_activation_id = Some(ActivationId(String::new()));
            }
        }
        assert_eq!(
            builder.build(input).expect_err("present-empty").message,
            "invalid-activation-identifier"
        );
    }
    let mut input = request();
    input.parent_activation_id = Some(ActivationId("parent".to_owned()));
    assert_eq!(
        builder.build(input).expect_err("missing root").message,
        "activation-parent-requires-root"
    );
    assert_eq!(ids.0.load(Ordering::Relaxed), 0);
}

#[test]
fn foreign_tenant_anonymous_and_missing_service_identity_are_rejected_before_ids() {
    let (builder, ids) = builder(ActivationRequestLimits::default());
    for case in 0..4 {
        let mut input = request();
        match case {
            0 => input.principal.tenant = None,
            1 => input.principal.tenant.as_mut().expect("tenant").0 = "other".to_owned(),
            2 => input.principal.kind = latent_core::PrincipalKind::Anonymous,
            _ => input.principal.kind = latent_core::PrincipalKind::Service,
        }
        assert_eq!(
            builder.build(input).expect_err("principal").code,
            PlatformErrorCode::PermissionDenied
        );
    }
    assert_eq!(ids.0.load(Ordering::Relaxed), 0);
}

#[test]
fn context_and_payload_bounds_are_checked_before_generation() {
    let mut limits = ActivationRequestLimits {
        maximum_input_bytes: 3,
        ..ActivationRequestLimits::default()
    };
    let (payload_builder, ids) = builder(limits);
    let mut input = request();
    input.input = vec![0; 4];
    assert_eq!(
        payload_builder.build(input).expect_err("payload").message,
        "activation-request-too-large"
    );
    assert_eq!(ids.0.load(Ordering::Relaxed), 0);

    limits.maximum_context_bytes = 4096;
    let (metadata_builder, ids) = builder(limits);
    let mut input = request();
    input.metadata.insert("one".to_owned(), "value".to_owned());
    assert_eq!(
        metadata_builder
            .build(input)
            .expect_err("metadata bookkeeping")
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(ids.0.load(Ordering::Relaxed), 0);
}

#[test]
fn small_values_with_oversized_owned_allocations_are_rejected_before_generation() {
    let limits = ActivationRequestLimits {
        maximum_input_bytes: 16,
        maximum_context_bytes: 16 * 1024,
        ..ActivationRequestLimits::default()
    };
    let (builder, ids) = builder(limits);
    for case in 0..3 {
        let mut input = request();
        if case == 0 {
            input.input = Vec::with_capacity(limits.maximum_input_bytes + 1);
            input.input.push(1);
        } else {
            let mut oversized = String::with_capacity(limits.maximum_context_bytes + 1);
            oversized.push_str("small");
            if case == 1 {
                input.principal.subject = oversized;
            } else {
                input.metadata.insert("note".to_owned(), oversized);
            }
        }
        assert_eq!(
            builder
                .build(input)
                .expect_err("retained allocation")
                .message,
            "activation-request-too-large"
        );
    }
    assert_eq!(ids.0.load(Ordering::Relaxed), 0);
}

#[test]
fn generated_identity_does_not_retain_the_sources_spare_capacity() {
    struct SpareCapacityIds;
    impl ActivationIdSource for SpareCapacityIds {
        fn next_id(&self) -> Result<ActivationId, PlatformError> {
            let mut value = String::with_capacity(8192);
            value.push_str("assigned");
            Ok(ActivationId(value))
        }
    }
    let builder = ActivationRequestBuilder::new(
        ActivationRequestLimits::default(),
        Arc::new(SpareCapacityIds),
    )
    .expect("builder");
    let envelope = builder.build(request()).expect("compact assigned identity");
    assert_eq!(envelope.activation_id.0, "assigned");
    assert_eq!(envelope.root_activation_id, envelope.activation_id);
    assert_eq!(
        envelope.activation_id.0.capacity(),
        envelope.activation_id.0.len()
    );
    assert_eq!(
        envelope.root_activation_id.0.capacity(),
        envelope.root_activation_id.0.len()
    );
}

#[test]
fn envelope_adapter_discards_an_untrusted_resolved_revision() {
    let (builder, _) = builder(ActivationRequestLimits::default());
    let mut envelope = builder.build(request()).expect("envelope");
    envelope.resolved_revision = Some(ResolvedRevision {
        target: envelope.target.clone(),
        revision: RevisionId("untrusted".to_owned()),
        release: ReleaseDigest("wrong-release".to_owned()),
        route_generation: RouteGeneration(999),
        attributes: Metadata::new(),
    });
    let normalized = builder
        .build(ActivationRequest::from_envelope(envelope))
        .expect("fresh resolution required");
    assert_eq!(normalized.resolved_revision, None);
    assert_eq!(normalized.activation_id.0, "assigned-0");
}

#[test]
fn generated_ids_and_unimplemented_budget_dimensions_are_validated() {
    struct InvalidIds;
    impl ActivationIdSource for InvalidIds {
        fn next_id(&self) -> Result<ActivationId, PlatformError> {
            Ok(ActivationId("invalid id".to_owned()))
        }
    }
    let builder =
        ActivationRequestBuilder::new(ActivationRequestLimits::default(), Arc::new(InvalidIds))
            .expect("builder");
    assert_eq!(
        builder
            .build(request())
            .expect_err("invalid generated ID")
            .message,
        "invalid-activation-identifier"
    );
    let mut input = request();
    input.budget.child_calls = 1;
    assert_ne!(
        builder
            .build(input)
            .expect_err("unsupported dimension before generation")
            .message,
        "invalid-activation-identifier"
    );
}

#[test]
fn default_id_source_never_wraps_its_counter() {
    let source = SystemActivationIdSource {
        namespace: 7,
        next: AtomicU64::new(u64::MAX - 1),
    };
    let last = source.next_id().expect("last nonwrapping ID");
    assert!(last.0.ends_with("fffffffffffffffe"));
    assert_eq!(
        source.next_id().expect_err("exhausted namespace").message,
        "activation-id-exhausted"
    );
    assert_eq!(source.next.load(Ordering::Relaxed), u64::MAX);
}
