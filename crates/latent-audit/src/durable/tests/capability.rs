use super::*;
use latent_core::{DeploymentId, ReleaseDigest, RevisionId, RouteGeneration};

fn required() -> AuditOperationAttempt {
    let mut value = attempt();
    value.action = AuditControlAction::CapabilityCall;
    value.preview_receipt_digest = None;
    value.expected_generation = None;
    value.identities = AuditIdentities {
        publication: Some(
            format!("publication:sha256:{}", "a".repeat(64))
                .parse()
                .unwrap(),
        ),
        component: Some(ReleaseDigest(digest().into_string())),
        deployment: Some(DeploymentId("deployed-echo".into())),
        revision: Some(RevisionId("revision-1".into())),
        route_generation: Some(RouteGeneration(1)),
        lifecycle_generation: Some(2),
        capability: Some(AuditCapabilityContext {
            activation: "activation-2".into(),
            parent_activation: Some("activation-1".into()),
            root_activation: "activation-1".into(),
            service: "echo".into(),
            binding_definition_digest: digest(),
            binding: AuditCapabilityRevision {
                id: "secrets-binding".into(),
                revision: 3,
                digest: digest(),
            },
            policies: vec![AuditCapabilityRevision {
                id: "secrets-policy".into(),
                revision: 4,
                digest: digest(),
            }],
            provider_profile: "local-secrets-v1".into(),
            provider_configuration_digest: digest(),
            provider_configuration_epoch: 5,
            capability: "latent:secrets/reader@0.1.0".into(),
            operation: "read".into(),
            resource_class: AuditCapabilityResourceClass::Secrets,
            request: Some(AuditCapabilityRequestDigest {
                scope: AuditCapabilityDigestScope::ProviderRequest,
                digest: digest(),
            }),
            required: true,
            provider_outcome: None,
        }),
        ..Default::default()
    };
    value
}
fn terminal(
    attempt: &AuditOperationAttempt,
    outcome: AuditProviderOutcome,
) -> AuditOperationConclusion {
    let mut value = conclusion();
    value.identities = attempt.identities.clone();
    value
        .identities
        .capability
        .as_mut()
        .unwrap()
        .provider_outcome = Some(outcome);
    value.result = match outcome {
        AuditProviderOutcome::Unknown => AuditOperationResult::Unknown,
        AuditProviderOutcome::NotStarted => AuditOperationResult::NotStarted,
        AuditProviderOutcome::Rejected => AuditOperationResult::Rejected,
        _ => AuditOperationResult::Committed,
    };
    value.receipt_digest = None;
    value
}

#[test]
fn closed_capability_records_require_exact_identity_and_terminal_association() {
    let value = required();
    codec::attempt(&value).unwrap();
    let done = terminal(&value, AuditProviderOutcome::SecretResolved);
    codec::conclusion(&done).unwrap();
    codec::capability_pair(&value, &done).unwrap();
    assert!(codec::conclusion(&terminal(&value, AuditProviderOutcome::BlobSealed)).is_err());
    let mut other = done.clone();
    other
        .identities
        .capability
        .as_mut()
        .unwrap()
        .binding
        .revision += 1;
    assert!(codec::capability_pair(&value, &other).is_err());
    other = done.clone();
    other.identities.deployment = Some(DeploymentId("another-deployment".into()));
    assert!(codec::capability_pair(&value, &other).is_err());
    let mut missing = value.clone();
    missing.identities.deployment = None;
    assert!(codec::attempt(&missing).is_err());
    missing = value.clone();
    missing
        .identities
        .capability
        .as_mut()
        .unwrap()
        .request
        .as_mut()
        .unwrap()
        .scope = AuditCapabilityDigestScope::ResourceSelection;
    assert!(codec::attempt(&missing).is_err());
    let mut json = serde_json::to_value(&value).unwrap();
    json["identities"]["capability"]["secretReference"] = "never-log-this".into();
    assert!(serde_json::from_value::<AuditOperationAttempt>(json).is_err());
    for field in ["capability", "publication", "component"] {
        let mut json = serde_json::to_value(&value).unwrap();
        json["identities"][field] = serde_json::Value::Null;
        assert!(serde_json::from_value::<AuditOperationAttempt>(json).is_err());
    }
    let bytes = codec::encode(&value, 16384).unwrap();
    assert!(!std::str::from_utf8(&bytes)
        .unwrap()
        .contains("secretReference"));
    let mut invalid = done;
    invalid.result = AuditOperationResult::NotStarted;
    assert!(codec::conclusion(&invalid).is_err());

    let mut runtime = value;
    let context = runtime.identities.capability.as_mut().unwrap();
    context.capability = "latent:runtime/activation@0.1.0".into();
    context.operation = "wait-for".into();
    context.provider_profile = "activation-owned-v1".into();
    context.resource_class = AuditCapabilityResourceClass::Clock;
    codec::attempt(&runtime).unwrap();
    let completed = terminal(&runtime, AuditProviderOutcome::HostCompleted);
    codec::conclusion(&completed).unwrap();
    codec::capability_pair(&runtime, &completed).unwrap();
    assert!(codec::conclusion(&terminal(&runtime, AuditProviderOutcome::BlobSealed)).is_err());
    runtime.identities.capability.as_mut().unwrap().capability =
        "latent:runtime/activation@0.2.0".into();
    assert!(codec::attempt(&runtime).is_err());
}

#[test]
fn preflight_denies_oversize_before_admission_and_unknown_survives_restart() {
    let directory = Directory::new();
    let path = directory.0.join("capability-audit");
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    let value = required();
    let mut too_large = terminal(&value, AuditProviderOutcome::SecretResolved);
    too_large.identities.capability.as_mut().unwrap().policies[0].id = "x".repeat(129);
    assert!(handle.preflight_conclusion(&value, &too_large).is_err());
    assert_eq!(handle.snapshot().reserved_records, 0);
    handle
        .preflight_conclusion(&value, &terminal(&value, AuditProviderOutcome::Unknown))
        .unwrap();
    let mut attempt = handle
        .try_reserve_critical(&value)
        .unwrap()
        .begin()
        .blocking_wait()
        .unwrap();
    attempt.mutation_started().unwrap();
    assert!(handle.try_reserve_critical(&value).is_err());
    drop(attempt);
    let deadline = Instant::now() + Duration::from_secs(2);
    while handle.snapshot().reserved_records != 0 && Instant::now() < deadline {
        std::thread::yield_now();
    }
    assert_eq!(handle.snapshot().unknown_outcomes, 1);
    stop(&handle, &mut worker);
    drop(worker);
    drop(handle);
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    let page = admitted_query(&handle, &query(value.scope))
        .unwrap()
        .blocking_wait()
        .unwrap();
    assert_eq!(page.records().len(), 2);
    let AuditRecordData::Outcome { conclusion, .. } = &page.records()[1].data else {
        panic!("terminal record")
    };
    assert_eq!(conclusion.result, AuditOperationResult::Unknown);
    assert_eq!(
        conclusion
            .identities
            .capability
            .as_ref()
            .unwrap()
            .provider_outcome,
        Some(AuditProviderOutcome::Unknown)
    );
    assert_eq!(
        conclusion.identities.deployment.as_ref().unwrap().0,
        "deployed-echo"
    );
    drop(page);
    stop(&handle, &mut worker);
}

#[test]
fn transaction_resource_selection_cannot_claim_generic_provider_or_commit_completion() {
    for (capability, operation) in [
        ("latent:state/key-value@0.2.0", "get"),
        ("latent:intents/staging@0.1.0", "stage"),
    ] {
        let mut value = required();
        let context = value.identities.capability.as_mut().unwrap();
        context.capability = capability.into();
        context.operation = operation.into();
        context.resource_class = AuditCapabilityResourceClass::State;
        context.required = false;
        context.request.as_mut().unwrap().scope = AuditCapabilityDigestScope::ResourceSelection;
        context.validate().unwrap();
        for outcome in [
            AuditProviderOutcome::HostCompleted,
            AuditProviderOutcome::BlobSealed,
            AuditProviderOutcome::HttpResponseReceived,
            AuditProviderOutcome::BrokerAcknowledged,
            AuditProviderOutcome::LocalDispatchAccepted,
            AuditProviderOutcome::SecretResolved,
        ] {
            assert!(!context.accepts_outcome(outcome));
            context.provider_outcome = Some(outcome);
            assert!(context.validate().is_err());
        }
        context.provider_outcome = None;
        // Selection evidence cannot stand in for a required durable provider
        // attempt with its independently captured complete request digest.
        assert!(codec::attempt(&value).is_err());
        let mut json = serde_json::to_value(&value).unwrap();
        json["identities"]["capability"]["resultPayload"] = "do-not-log-business-results".into();
        assert!(serde_json::from_value::<AuditOperationAttempt>(json).is_err());
        let context = value.identities.capability.as_mut().unwrap();
        context.resource_class = AuditCapabilityResourceClass::Secrets;
        assert!(context.validate().is_err());
        context.resource_class = AuditCapabilityResourceClass::State;
        context.capability = "latent:state/key-value@99.0.0".into();
        assert!(context.validate().is_err());
    }
}

fn native_thread_observation(provider_completed: bool) -> AuditObservation {
    let mut value = required();
    let context = value.identities.capability.as_mut().unwrap();
    context.capability = "latent:runtime-native/threads@0.1.0".into();
    context.operation = "start".into();
    context.resource_class = AuditCapabilityResourceClass::Context;
    context.provider_profile = "conservative-native-total-starts-v1".into();
    context.required = false;
    context.request.as_mut().unwrap().scope = if provider_completed {
        AuditCapabilityDigestScope::ProviderRequest
    } else {
        AuditCapabilityDigestScope::ResourceSelection
    };
    context.provider_outcome = provider_completed.then_some(AuditProviderOutcome::HostCompleted);
    AuditObservation {
        scope: value.scope,
        actor: value.actor,
        identities: value.identities,
        kind: if provider_completed {
            Phase2AuditEventKind::CapabilityProviderOutcome
        } else {
            Phase2AuditEventKind::CapabilityGrantAllowed
        },
        outcome: crate::AuditOutcome::Succeeded,
        reason: AuditReason::Admitted,
        cache_kind: None,
        occurred_at_unix_millis: 1,
    }
}

#[test]
fn native_thread_audit_encodes_exact_grant_and_host_completion_without_changing_default_abi() {
    assert_eq!(
        latent_core::PHASE3_HOST_ABI_CURRENT,
        latent_core::PHASE3_HOST_ABI_V5
    );
    assert!(latent_core::PHASE3_HOST_ABI_CURRENT
        .interface("latent:runtime-native/threads@0.1.0")
        .is_none());
    for completed in [false, true] {
        let event = native_thread_observation(completed);
        codec::observation(&event).unwrap();
        let normalized: AuditObservation = codec::normalize(&event, 16384).unwrap();
        codec::observation(&normalized).unwrap();
        assert_eq!(normalized, event);
        codec::envelope(
            &event.scope,
            &event.actor,
            AuditRecordData::Observation(event.clone()),
            16384,
        )
        .unwrap();
    }
}

#[test]
fn native_thread_audit_refuses_other_versions_operations_and_resource_classes() {
    for completed in [false, true] {
        let original = native_thread_observation(completed);
        for capability in [
            "latent:runtime-native/threads@0.2.0",
            "latent:runtime-native/other@0.1.0",
            "foreign:runtime-native/threads@0.1.0",
        ] {
            let mut bad = original.clone();
            bad.identities.capability.as_mut().unwrap().capability = capability.into();
            assert!(codec::observation(&bad).is_err(), "accepted {capability}");
        }
        for operation in ["register", "resume", "start-later", ""] {
            let mut bad = original.clone();
            bad.identities.capability.as_mut().unwrap().operation = operation.into();
            assert!(codec::observation(&bad).is_err(), "accepted {operation}");
        }
        for class in [
            AuditCapabilityResourceClass::Clock,
            AuditCapabilityResourceClass::Stream,
            AuditCapabilityResourceClass::Service,
            AuditCapabilityResourceClass::State,
        ] {
            let mut bad = original.clone();
            bad.identities.capability.as_mut().unwrap().resource_class = class;
            assert!(codec::observation(&bad).is_err(), "accepted {class:?}");
        }
    }
}

#[test]
fn native_thread_audit_retains_identity_outcome_and_redaction_boundaries() {
    let original = native_thread_observation(true);
    for outcome in [
        AuditProviderOutcome::HttpResponseReceived,
        AuditProviderOutcome::BlobSealed,
        AuditProviderOutcome::SecretResolved,
        AuditProviderOutcome::LocalDispatchAccepted,
        AuditProviderOutcome::BrokerAcknowledged,
    ] {
        let mut bad = original.clone();
        bad.identities.capability.as_mut().unwrap().provider_outcome = Some(outcome);
        assert!(codec::observation(&bad).is_err(), "accepted {outcome:?}");
    }
    let mut bad = original.clone();
    bad.identities.publication = None;
    assert!(codec::observation(&bad).is_err());
    let mut bad = original.clone();
    bad.identities.capability.as_mut().unwrap().binding.revision = 0;
    assert!(codec::observation(&bad).is_err());
    let mut bad = original.clone();
    let context = bad.identities.capability.as_mut().unwrap();
    context.parent_activation = Some(context.activation.clone());
    assert!(codec::observation(&bad).is_err());
    let mut json = serde_json::to_value(&original).unwrap();
    json["identities"]["capability"]["childPointer"] = "must-not-be-recorded".into();
    assert!(serde_json::from_value::<AuditObservation>(json).is_err());
}
