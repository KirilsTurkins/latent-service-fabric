use super::*;
use crate::config::CapabilityPolicyConfig;
mod perimeter;
use latent_policy::capability::{PolicyStoreLimits, LANGUAGE, PROVIDER_BINDING_LANGUAGE};
use latent_wire::management::proto;
use std::time::Duration;

fn configured(directory: &TempDir) -> NodeSettings {
    let mut settings = settings(directory);
    settings.capability_policies = Some(CapabilityPolicyConfig {
        format_version: 1,
        store: PolicyStoreLimits::default(),
        maximum_control_jobs: 2,
    });
    settings.shutdown_grace = Duration::from_secs(5);
    settings
}
fn request<T>(value: T) -> tonic::Request<T> {
    let mut request = tonic::Request::new(value);
    request.metadata_mut().insert(
        "authorization",
        "Bearer test-token-000000000000000000000000000000"
            .parse()
            .unwrap(),
    );
    request.set_timeout(Duration::from_secs(5));
    request
}
fn apply(
    id: &str,
    kind: proto::CapabilityPolicyRecordKind,
    document: &serde_json::Value,
) -> proto::ApplyPolicyRequest {
    proto::ApplyPolicyRequest {
        policy: Some(proto::Policy {
            id: id.into(),
            metadata: Some(proto::ObjectMetadata {
                name: id.into(),
                tenant: Some("tests".into()),
                ..proto::ObjectMetadata::default()
            }),
            document: document.to_string(),
            generation: 0,
            language: if kind == proto::CapabilityPolicyRecordKind::Policy {
                LANGUAGE
            } else {
                PROVIDER_BINDING_LANGUAGE
            }
            .into(),
            record_kind: kind as i32,
            content_digest: String::new(),
            revoked: false,
        }),
        expected_generation: Some(0),
        operation_id: format!("create-{id}"),
    }
}
#[tokio::test]
#[allow(
    clippy::too_many_lines,
    reason = "one real authenticated node transaction covers policy replay, explanation, revocation and restart"
)]
async fn authenticated_policy_service_replays_and_reopens_without_reviving_revoked_authority() {
    let directory = TempDir::new().unwrap();
    let node = super::super::StandaloneNode::start(
        configured(&directory),
        tokio::runtime::Handle::current(),
        crate::standalone::RuntimeThreads::default(),
    )
    .await
    .unwrap();
    let endpoint = format!("http://{}", node.endpoint());
    let mut client = proto::policy_service_client::PolicyServiceClient::connect(endpoint)
        .await
        .unwrap();
    let policy = apply(
        "p",
        proto::CapabilityPolicyRecordKind::Policy,
        &serde_json::json!({"formatVersion":1,"tenant":"tests","rules":[]}),
    );
    assert_eq!(
        client
            .apply_policy(policy.clone())
            .await
            .unwrap_err()
            .code(),
        tonic::Code::Unauthenticated
    );
    let first = client
        .apply_policy(request(policy.clone()))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(first.receipt.as_ref().unwrap().generation, 2);
    assert_eq!(
        client
            .apply_policy(request(policy))
            .await
            .unwrap()
            .into_inner(),
        first
    );
    let binding = apply(
        "binding",
        proto::CapabilityPolicyRecordKind::ProviderBinding,
        &serde_json::json!({
        "formatVersion":1,"tenant":"tests","capability":"latent:secrets/reader@0.1.0","providerProfile":"local-secrets-v1",
        "configurationDigest":format!("sha256:{}","1".repeat(64)),"configurationEpoch":1,"restriction":{"operations":[]}}),
    );
    client.apply_policy(request(binding)).await.unwrap();
    let explanation = proto::EvaluatePolicyRequest {
        policy_id: "p".into(),
        service: "echo".into(),
        publication_id: format!("publication:sha256:{}", "1".repeat(64)),
        capability: "latent:secrets/reader@0.1.0".into(),
        operation: "read".into(),
        resource_document: "{\"kind\":\"secrets\",\"reference\":\"test-key\"}".into(),
        provider_binding_id: "binding".into(),
        ..proto::EvaluatePolicyRequest::default()
    };
    assert_eq!(
        client
            .evaluate_policy(request(explanation.clone()))
            .await
            .unwrap()
            .into_inner()
            .decision,
        "deny"
    );
    let mut forged = explanation;
    forged.subject = "another-user".into();
    assert_eq!(
        client
            .evaluate_policy(request(forged))
            .await
            .unwrap_err()
            .code(),
        tonic::Code::InvalidArgument
    );
    let listed = client
        .list_policies(request(proto::ListPoliciesRequest {
            record_kind: proto::CapabilityPolicyRecordKind::Policy as i32,
            page: Some(proto::PageRequest {
                page_size: 1,
                page_token: None,
            }),
        }))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(listed.policies.len(), 1);
    assert_eq!(listed.policies[0].id, "p");
    client
        .delete_policy(request(proto::DeletePolicyRequest {
            id: "p".into(),
            expected_generation: Some(2),
            operation_id: "revoke".into(),
            record_kind: proto::CapabilityPolicyRecordKind::Policy as i32,
        }))
        .await
        .unwrap();
    let receipt = client
        .get_policy_operation(request(proto::GetPolicyOperationRequest {
            operation_id: "revoke".into(),
        }))
        .await
        .unwrap()
        .into_inner()
        .receipt
        .unwrap();
    assert!(receipt.revoked);
    assert_eq!(receipt.generation, 4);
    let inventory = node.inventory().unwrap();
    assert!(inventory
        .topology
        .entries
        .iter()
        .any(|row| row.name == "capability-policy-control-jobs"));
    drop(client);
    let report = node.shutdown().await.unwrap();
    assert!(report.clean);
    assert!(report.policies.unwrap().clean());
    assert!(settings(&directory).check_config().is_err());
    assert!(super::super::StandaloneNode::start(
        settings(&directory),
        tokio::runtime::Handle::current(),
        crate::standalone::RuntimeThreads::default()
    )
    .await
    .is_err());
    let node = super::super::StandaloneNode::start(
        configured(&directory),
        tokio::runtime::Handle::current(),
        crate::standalone::RuntimeThreads::default(),
    )
    .await
    .unwrap();
    let mut client = proto::policy_service_client::PolicyServiceClient::connect(format!(
        "http://{}",
        node.endpoint()
    ))
    .await
    .unwrap();
    assert_eq!(
        client
            .get_policy_operation(request(proto::GetPolicyOperationRequest {
                operation_id: "revoke".into()
            }))
            .await
            .unwrap()
            .into_inner()
            .receipt,
        Some(receipt)
    );
    let row = client
        .get_policy(request(proto::GetPolicyRequest {
            id: "p".into(),
            record_kind: proto::CapabilityPolicyRecordKind::Policy as i32,
        }))
        .await
        .unwrap()
        .into_inner()
        .policy
        .unwrap();
    assert!(row.revoked);
    assert!(row.document.is_empty());
    drop(client);
    assert!(node.shutdown().await.unwrap().clean);
}
#[tokio::test]
async fn missing_or_foreign_policy_owner_is_rejected_before_service_composition() {
    let directory = TempDir::new().unwrap();
    let mut settings = configured(&directory);
    let mut catalogs = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    settings
        .capability_policies
        .as_mut()
        .unwrap()
        .maximum_control_jobs = 3;
    assert!(catalogs
        .validate_composition(&settings, &catalogs.clock)
        .is_err());
    settings
        .capability_policies
        .as_mut()
        .unwrap()
        .maximum_control_jobs = 2;
    settings
        .capability_policies
        .as_mut()
        .unwrap()
        .store
        .maximum_records = 127;
    assert!(catalogs
        .validate_composition(&settings, &catalogs.clock)
        .is_err());
    settings
        .capability_policies
        .as_mut()
        .unwrap()
        .store
        .maximum_records = 128;
    assert!(catalogs
        .validate_composition(&settings, &catalogs.clock)
        .is_ok());
    let policy = catalogs.policies.take();
    assert!(super::super::StandaloneNode::compose(
        &mut settings,
        &catalogs,
        Arc::new(SystemActivationClock)
    )
    .is_err());
    drop(policy);
    let other = TempDir::new().unwrap();
    let other_settings = configured(&other);
    let mut other_catalogs =
        Catalogs::open_with_control(&other_settings, &tokio::runtime::Handle::current())
            .await
            .unwrap();
    catalogs.policies = other_catalogs.policies.take();
    assert!(super::super::StandaloneNode::compose(
        &mut settings,
        &catalogs,
        Arc::new(SystemActivationClock)
    )
    .is_err());
}

#[tokio::test]
async fn capability_composition_requires_the_exact_policy_owner_even_with_the_same_catalog() {
    use latent_capabilities::broker::{
        ActivationCapabilityBroker, ActivationCapabilityRuntime, CapabilityBrokerLimits,
        CapabilityPlanSource, CompiledCapabilityPlan,
    };
    struct NoPlans;
    impl CapabilityPlanSource for NoPlans {
        fn plan(
            &self,
            _: &latent_routing::ResolvedRevision,
        ) -> Result<Arc<CompiledCapabilityPlan>, latent_core::PlatformError> {
            panic!("composition must not look up or execute an activation")
        }
    }
    let directory = TempDir::new().unwrap();
    let settings = configured(&directory);
    let mut catalogs = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    let foreign = Arc::new(
        latent_policy::capability::PolicyStore::open(
            &directory.path().join("other-policies"),
            PolicyStoreLimits::default(),
            catalogs.artifacts.lifecycle_authority(),
        )
        .unwrap(),
    );
    let runtime = |policies| {
        Arc::new(ActivationCapabilityRuntime::new(
            Arc::new(
                ActivationCapabilityBroker::new(
                    catalogs.artifacts.lifecycle_authority(),
                    policies,
                    catalogs.clock.clone(),
                    CapabilityBrokerLimits::default(),
                )
                .unwrap(),
            ),
            Arc::new(NoPlans),
        ))
    };
    catalogs.capabilities = Some(runtime(foreign));
    assert!(catalogs
        .validate_composition(&settings, &catalogs.clock)
        .is_err());
    catalogs.capabilities = Some(runtime(
        catalogs.policies.as_ref().unwrap().handle().store().clone(),
    ));
    assert!(catalogs
        .validate_composition(&settings, &catalogs.clock)
        .is_ok());
    let handle = catalogs.policies.take();
    assert!(catalogs
        .validate_composition(&settings, &catalogs.clock)
        .is_err());
    drop(handle);
}
