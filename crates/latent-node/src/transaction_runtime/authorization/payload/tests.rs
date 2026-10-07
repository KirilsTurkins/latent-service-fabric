//! These tests qualify the closed filter, not publication or broker execution.
use super::*;
use crate::transaction_runtime::command_completion::tests::fixture::Fixture;
use latent_capabilities::broker::{
    ActivationCapabilityBroker, ProviderConfiguration, ProviderRegistration,
};
use latent_policy::capability::GrantRestriction;
use sha2::{Digest, Sha256};

fn installed_reference(
    broker: &ActivationCapabilityBroker,
    profile: &str,
    epoch: u64,
) -> ProviderRegistration {
    // Actual broker registration owns the immutable reference, metadata and
    // provider slot. This fixture does not manufacture a capability/session or
    // claim an authenticated JetStream configuration observation.
    let configuration = serde_json::to_vec(&serde_json::json!({
        "profile": profile, "epoch": epoch, "topic": "aggregate-events"
    }))
    .unwrap();
    let digest = format!(
        "sha256:{:x}",
        latent_core::digest::HexDigest(Sha256::digest(configuration))
    );
    broker
        .register_provider(ProviderConfiguration {
            capability: EVENTS_CAPABILITY,
            profile,
            configuration_digest: &digest,
            configuration_epoch: epoch,
            restriction_json: br#"{"operations":["publish"]}"#,
            minimum_call_charges: &[],
        })
        .unwrap()
}
fn binding(reference: &ProviderReference) -> PolicyCallBinding {
    PolicyCallBinding {
        policies: vec!["original-policy".into()],
        binding: "original-binding".into(),
        profile: "nats-jetstream-effect-v1".into(),
        configuration_digest: reference.configuration_digest().into(),
        configuration_epoch: reference.configuration_epoch(),
        operations: vec!["stage".into()],
        deployment: GrantRestriction::parse(
            br#"{"operations":[]}"#,
            latent_capabilities::namespace::INTENT_CONTRACT,
        )
        .unwrap(),
        provider_configuration: GrantRestriction::parse(
            br#"{"operations":[]}"#,
            latent_capabilities::namespace::INTENT_CONTRACT,
        )
        .unwrap(),
    }
}
fn aggregate(count: u64) -> Value {
    Value {
        bytes: count.to_le_bytes().to_vec(),
        media_type: "application/vnd.lsf.aggregate-v1".into(),
        metadata: vec![],
    }
}

#[tokio::test]
async fn captured_event_value_filter_keeps_actual_reference_and_refuses_size_media_metadata_or_binding_drift(
) {
    let fixture = Fixture::new().await;
    let broker = fixture.broker();
    let registration = installed_reference(&broker, "nats-jetstream-publish-v1", 1);
    let reference = registration.reference();
    let captured = binding(&reference);
    let constraint =
        IntentPayloadConstraint::bounded_event(reference, 8, aggregate(0).media_type).unwrap();
    for count in [0, 1, u64::MAX] {
        constraint.check(&captured, &aggregate(count)).unwrap();
    }
    for changed in 0..3 {
        let mut value = aggregate(1);
        match changed {
            0 => value.bytes.push(0),
            1 => value.media_type = "application/octet-stream".into(),
            _ => value
                .metadata
                .push(("ordering-key".into(), "forbidden".into())),
        }
        assert!(constraint.check(&captured, &value).is_err());
    }
    for changed in 0..3 {
        let mut current = binding(&registration.reference());
        match changed {
            0 => current.profile = "nats-jetstream-publish-v1".into(),
            1 => current.configuration_epoch += 1,
            _ => current.configuration_digest = format!("sha256:{}", "0".repeat(64)),
        }
        assert!(constraint.check(&current, &aggregate(1)).is_err());
    }
    let rotated = installed_reference(&broker, "nats-jetstream-publish-v1", 2);
    assert!(constraint
        .check(&binding(&rotated.reference()), &aggregate(1))
        .is_err());
    let incompatible = installed_reference(&broker, "unsupported-event-profile", 3);
    assert!(IntentPayloadConstraint::bounded_event(
        incompatible.reference(),
        8,
        aggregate(0).media_type
    )
    .is_err());
    for maximum in [0, 65_537] {
        assert!(IntentPayloadConstraint::bounded_event(
            registration.reference(),
            maximum,
            aggregate(0).media_type
        )
        .is_err());
    }
    drop((
        constraint,
        captured,
        rotated,
        incompatible,
        registration,
        broker,
    ));
    fixture.shutdown().await;
}

#[tokio::test]
async fn original_http_payload_filter_retains_exact_digest_and_never_accepts_an_event_or_changed_value(
) {
    let fixture = Fixture::new().await;
    let broker = fixture.broker();
    let registration = installed_reference(&broker, "nats-jetstream-publish-v1", 1);
    let captured = binding(&registration.reference());
    let original = Value {
        bytes: b"original-put-once".to_vec(),
        media_type: "application/octet-stream".into(),
        metadata: vec![],
    };
    let constraint = IntentPayloadConstraint::exact_digest(
        latent_effects::payload::payload_digest(&original).unwrap(),
    );
    constraint.check(&captured, &original).unwrap();
    for changed in 0..3 {
        let mut value = original.clone();
        match changed {
            0 => value.bytes.push(0),
            1 => value.media_type = "application/vnd.lsf.aggregate-v1".into(),
            _ => value.metadata.push(("extra".into(), "value".into())),
        }
        assert!(constraint.check(&captured, &value).is_err());
    }
    assert!(constraint.check(&captured, &aggregate(1)).is_err());
    for malformed in [
        "sha256:unknown".into(),
        format!("sha256:{}", "a".repeat(64)),
        "A".repeat(64),
        "a".repeat(63),
        "a".repeat(65),
    ] {
        assert!(IntentPayloadConstraint::exact_digest(malformed)
            .require_binding(&captured)
            .is_err());
    }
    drop((constraint, captured, registration, broker));
    fixture.shutdown().await;
}
