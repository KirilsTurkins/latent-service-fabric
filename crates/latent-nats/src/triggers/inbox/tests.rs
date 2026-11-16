use super::*;
use latent_activation::{ActivationOutcome, ActivationSuccess};
use latent_core::{ActivationId, BudgetConsumption, Metadata};
use serde_json::json;

fn config() -> TriggerConfig {
    let mut config = super::super::tests::config();
    config.bindings[0].transaction = Some(TransactionalBinding {
        processing_scope: "order-processing".into(),
        namespace: "orders".into(),
        incarnation: 1,
        qualification: JetStreamQualification {
            format_version: 1,
            server_version: "2.14.6".into(),
            stream_created: "2026-10-06T00:00:00Z".into(),
            maximum_messages: 10_000,
            maximum_bytes: 64 * 1024 * 1024,
            maximum_age_millis: 0,
            maximum_message_bytes: 16_384,
        },
        duplicate_window_millis: 30_000,
        state_read_bytes: 4096,
        state_write_bytes: 4096,
        effect_count: 4,
    });
    config
}

fn delivery(
    provider: &str,
    binding: &TriggerBinding,
    sequence: u64,
    bytes: &[u8],
) -> InboxDelivery {
    capture(
        provider,
        binding,
        QualifiedStream {
            binding: binding_identity(binding).unwrap(),
        },
        sequence,
        bytes,
    )
    .unwrap()
}

#[test]
fn input_identity_survives_consumer_and_binding_display_changes_but_refuses_payload_drift() {
    let mut config = config();
    let original = delivery("input-broker", &config.bindings[0], 42, b"input");
    config.bindings[0].consumer = "REPLACEMENT".into();
    config.bindings[0].id = "rotated-display".into();
    let rotated = delivery("input-broker", &config.bindings[0], 42, b"input");
    assert_eq!(original.client_id(), rotated.client_id());
    assert_eq!(original.identity(), rotated.identity());
    let changed = delivery("input-broker", &config.bindings[0], 42, b"other");
    assert_eq!(original.client_id(), changed.client_id());
    assert_eq!(original.identity().binding, changed.identity().binding);
    assert_eq!(original.identity().message, changed.identity().message);
    assert_ne!(
        original.identity().payload_digest,
        changed.identity().payload_digest
    );
}

#[test]
fn qualified_delivery_exposes_exact_origin_without_changing_existing_binding() {
    let config = config();
    let binding = &config.bindings[0];
    let transaction = binding.transaction.as_ref().unwrap();
    let original = delivery("input-broker", binding, 42, b"input");
    let incarnation = transaction.incarnation.to_le_bytes();
    let expected = identity(
        b"lsf-jetstream-input-scope-v1\0",
        &[
            binding.tenant.as_bytes(),
            b"input-broker",
            binding.stream.as_bytes(),
            transaction.qualification.stream_created.as_bytes(),
            transaction.processing_scope.as_bytes(),
            transaction.namespace.as_bytes(),
            &incarnation,
        ],
    );
    assert_eq!(original.identity().binding, expected.hex());
    assert_eq!(original.scope().input_binding().unwrap(), expected.hex());
    assert_eq!(original.scope().provider, "input-broker");
    assert_eq!(original.scope().stream, binding.stream);
    assert_eq!(
        original.scope().stream_created,
        transaction.qualification.stream_created
    );
}

#[test]
fn transactional_request_metadata_survives_trigger_display_rename() {
    let mut config = config();
    let deadline = latent_core::IncomingDeadline::new(
        std::time::Instant::now() + std::time::Duration::from_secs(2),
        1234,
    );
    let before = super::super::execution::root_request(
        &config.bindings[0],
        ActivationId("before".into()),
        deadline,
    );
    config.bindings[0].id = "rotated-display".into();
    let after = super::super::execution::root_request(
        &config.bindings[0],
        ActivationId("after".into()),
        deadline,
    );
    assert_eq!(before.metadata, after.metadata);
    assert!(before.metadata.is_empty());
    config.bindings[0].transaction = None;
    let stateless = super::super::execution::root_request(
        &config.bindings[0],
        ActivationId("stateless".into()),
        deadline,
    );
    assert_eq!(
        stateless.metadata.get("trigger.id").unwrap(),
        "rotated-display"
    );
}

#[test]
fn trusted_input_identity_separates_tenant_provider_stream_birth_scope_and_namespace() {
    let original = config();
    let baseline = delivery("input-broker", &original.bindings[0], 42, b"input");
    assert_ne!(
        baseline.client_id(),
        delivery("other-broker", &original.bindings[0], 42, b"input").client_id()
    );
    assert_ne!(
        baseline.client_id(),
        delivery("input-broker", &original.bindings[0], 43, b"input").client_id()
    );
    for field in [
        "tenant",
        "namespace",
        "incarnation",
        "scope",
        "stream",
        "birth",
    ] {
        let mut changed = original.clone();
        let binding = &mut changed.bindings[0];
        let selected = binding.transaction.as_mut().unwrap();
        match field {
            "tenant" => binding.tenant = "tenant-b".into(),
            "namespace" => selected.namespace = "another".into(),
            "incarnation" => selected.incarnation = 2,
            "scope" => selected.processing_scope = "approved-replay".into(),
            "stream" => binding.stream = "OTHER".into(),
            "birth" => selected.qualification.stream_created = "2026-10-07T00:00:00Z".into(),
            _ => unreachable!(),
        }
        assert_ne!(
            baseline.client_id(),
            delivery("input-broker", binding, 42, b"input").client_id(),
            "{field}"
        );
    }
}

#[test]
fn transaction_opt_in_preserves_stateless_bytes_and_refuses_unbounded_or_immediate_work() {
    let stateless = super::super::tests::config();
    let bytes = stateless.to_json().unwrap();
    assert!(
        !serde_json::from_slice::<serde_json::Value>(&bytes).unwrap()["bindings"][0]
            .as_object()
            .unwrap()
            .contains_key("transaction")
    );
    assert_eq!(
        TriggerConfig::from_json(&bytes).unwrap().to_json().unwrap(),
        bytes
    );
    let config = config();
    config.validate().unwrap();
    let budget = config.bindings[0].activation_budget();
    assert_eq!(
        (
            budget.state_read_bytes,
            budget.state_write_bytes,
            budget.effect_count
        ),
        (4096, 4096, 4)
    );
    for field in [
        "child",
        "outbound",
        "scope",
        "incarnation",
        "read",
        "write",
        "effects",
        "retention",
    ] {
        let mut changed = config.clone();
        let binding = &mut changed.bindings[0];
        let selected = binding.transaction.as_mut().unwrap();
        match field {
            "child" => binding.budget.child_calls = 1,
            "outbound" => binding.budget.outbound_requests = 1,
            "scope" => selected.processing_scope = "wild.>".into(),
            "incarnation" => selected.incarnation = 0,
            "read" => selected.state_read_bytes = 8 * 1024 * 1024 + 1,
            "write" => selected.state_write_bytes = 8 * 1024 * 1024 + 1,
            "effects" => selected.effect_count = 33,
            "retention" => {
                selected.qualification.maximum_age_millis = INBOX_IDENTITY_RETENTION_MILLIS - 1;
            }
            _ => unreachable!(),
        }
        assert_eq!(changed.validate(), Err(EventError::InvalidEvent), "{field}");
    }
}

#[test]
fn literal_input_stream_requires_original_incarnation_and_protected_finite_history() {
    let config = config();
    let binding = &config.bindings[0];
    let selected = binding.transaction.as_ref().unwrap();
    let response = json!({"type":"io.nats.jetstream.api.v1.stream_info_response",
        "created":selected.qualification.stream_created, "config":{
            "name":"ORDERS", "subjects":["orders.new"], "storage":"file", "retention":"limits", "discard":"new",
            "num_replicas":1,"max_msgs":10_000,"max_bytes":64*1024*1024,"max_age":0,"max_msg_size":16_384,
            "duplicate_window":30_000_000_000u64,"deny_delete":true,"deny_purge":true}});
    let check = |value: &serde_json::Value| {
        qualification::validate_stream_response(
            &serde_json::to_vec(value).unwrap(),
            &selected.qualification,
            &binding.stream,
            &[&binding.filter_subject],
            selected.duplicate_window_millis,
        )
    };
    check(&response).unwrap();
    for (field, value) in [
        ("subjects", json!(["orders.>"])),
        ("storage", json!("memory")),
        ("retention", json!("workqueue")),
        ("discard", json!("old")),
        ("max_msgs", json!(-1)),
        ("deny_delete", json!(false)),
        ("deny_purge", json!(false)),
        ("max_age", json!(1)),
        ("sources", json!([])),
    ] {
        let mut changed = response.clone();
        changed["config"][field] = value;
        assert!(check(&changed).is_err(), "{field}");
    }
    let mut recreated = response;
    recreated["created"] = json!("2026-10-07T00:00:00Z");
    assert_eq!(check(&recreated), Err(EventError::PermissionDenied));
}

#[test]
fn broker_qualification_cannot_be_reused_for_a_different_configured_binding() {
    let mut config = config();
    let qualified = QualifiedStream {
        binding: binding_identity(&config.bindings[0]).unwrap(),
    };
    config.bindings[0]
        .transaction
        .as_mut()
        .unwrap()
        .processing_scope = "approved-replay".into();
    assert!(matches!(
        capture("input-broker", &config.bindings[0], qualified, 42, b"input"),
        Err(EventError::PermissionDenied)
    ));
}

#[test]
fn ordinary_activation_success_never_acknowledges_a_transactional_input() {
    let config = config();
    let input = delivery("input-broker", &config.bindings[0], 42, b"input");
    let receipt = latent_node::ActivationReceipt {
        activation_id: ActivationId("ordinary".into()),
        resolved_revision: None,
        outcome: ActivationOutcome::Succeeded(ActivationSuccess {
            output: b"success".to_vec().into(),
            output_media_type: "application/octet-stream".into(),
            consumption: BudgetConsumption::default(),
            committed_state_version: None,
            effect_ids: vec![],
            metadata: Metadata::new(),
        }),
    };
    assert!(matches!(receipt.outcome, ActivationOutcome::Succeeded(_)));
    assert_eq!(
        super::super::execution::transaction_outcome(None, &input).0,
        super::super::TriggerTerminal::RecoveryRequired
    );
}

#[test]
fn simultaneous_scope_cannot_claim_different_stream_origins() {
    let mut config = config();
    let mut duplicate = config.bindings[0].clone();
    duplicate.id = "second-binding".into();
    duplicate.consumer = "second-consumer".into();
    config.bindings.push(duplicate);
    assert!(config.validate().is_ok(), "same origin can share a scope");

    config.bindings[1].stream = "OTHER".into();
    assert_eq!(config.validate(), Err(EventError::InvalidEvent));
    config.bindings[1].stream = config.bindings[0].stream.clone();
    config.bindings[1]
        .transaction
        .as_mut()
        .unwrap()
        .qualification
        .stream_created = "2026-10-07T00:00:00Z".into();
    assert_eq!(config.validate(), Err(EventError::InvalidEvent));
    config.bindings[1]
        .transaction
        .as_mut()
        .unwrap()
        .processing_scope = "approved-replay".into();
    assert!(
        config.validate().is_ok(),
        "explicit new scope can use another origin"
    );
}
