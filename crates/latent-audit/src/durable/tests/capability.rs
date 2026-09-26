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
