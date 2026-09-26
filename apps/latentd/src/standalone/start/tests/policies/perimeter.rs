use super::*;
use crate::standalone::transport::TransportCredential;
use latent_core::{InvocationPrincipal, Metadata, PrincipalKind, TenantId};
fn authenticated<T>(value: T, token: &str) -> tonic::Request<T> {
    let mut result = request(value);
    result
        .metadata_mut()
        .insert("authorization", format!("Bearer {token}").parse().unwrap());
    result
}
#[tokio::test]
async fn omitted_policy_owner_authenticates_before_reporting_unimplemented() {
    let directory = TempDir::new().unwrap();
    let node = super::super::super::StandaloneNode::start(
        settings(&directory),
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
    let get = proto::GetPolicyRequest {
        id: "p".into(),
        record_kind: proto::CapabilityPolicyRecordKind::Policy as i32,
    };
    assert_eq!(
        client.get_policy(get.clone()).await.unwrap_err().code(),
        tonic::Code::Unauthenticated
    );
    assert_eq!(
        client.get_policy(request(get)).await.unwrap_err().code(),
        tonic::Code::Unimplemented
    );
    drop(client);
    assert!(node.shutdown().await.unwrap().clean);
}
#[tokio::test]
#[allow(
    clippy::too_many_lines,
    reason = "one real node verifies authentication, scope, invalid mutations and cursor isolation"
)]
async fn policy_mutations_reject_foreign_scope_unsafe_legacy_requests_and_forged_cursors() {
    let directory = TempDir::new().unwrap();
    let mut settings = configured(&directory);
    for (token, tenant, kind) in [
        (
            "foreign-token-000000000000000000000000000",
            "foreign",
            PrincipalKind::Administrator,
        ),
        (
            "invoke-token-0000000000000000000000000000",
            "tests",
            PrincipalKind::Service,
        ),
    ] {
        settings.transport.credentials.push(TransportCredential {
            token: token.into(),
            principal: InvocationPrincipal {
                subject: "actor".into(),
                kind,
                tenant: Some(TenantId(tenant.into())),
                service: (kind == PrincipalKind::Service)
                    .then(|| latent_core::ServiceId("caller".into())),
                claims: Metadata::new(),
            },
        });
    }
    let node = super::super::super::StandaloneNode::start(
        settings,
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
    let original = apply(
        "p",
        proto::CapabilityPolicyRecordKind::Policy,
        &serde_json::json!({"formatVersion":1,"tenant":"tests","rules":[]}),
    );
    assert_eq!(
        client
            .apply_policy(authenticated(
                original.clone(),
                "invoke-token-0000000000000000000000000000"
            ))
            .await
            .unwrap_err()
            .code(),
        tonic::Code::PermissionDenied
    );
    assert!(client
        .apply_policy(authenticated(
            original.clone(),
            "foreign-token-000000000000000000000000000"
        ))
        .await
        .is_err());
    for field in 0..4 {
        let mut value = original.clone();
        match field {
            0 => value.expected_generation = None,
            1 => value.operation_id.clear(),
            2 => {
                value.policy.as_mut().unwrap().document =
                    "{\"formatVersion\":1,\"formatVersion\":1,\"tenant\":\"tests\",\"rules\":[]}"
                        .into();
            }
            _ => value.policy.as_mut().unwrap().language = "latent-policy/v1".into(),
        }
        assert_eq!(
            client
                .apply_policy(request(value))
                .await
                .unwrap_err()
                .code(),
            tonic::Code::InvalidArgument
        );
    }
    assert!(client
        .get_policy_operation(request(proto::GetPolicyOperationRequest {
            operation_id: "create-p".into()
        }))
        .await
        .unwrap()
        .into_inner()
        .receipt
        .is_none());
    client.apply_policy(request(original)).await.unwrap();
    client
        .apply_policy(request(apply(
            "q",
            proto::CapabilityPolicyRecordKind::Policy,
            &serde_json::json!({"formatVersion":1,"tenant":"tests","rules":[]}),
        )))
        .await
        .unwrap();
    let page = proto::ListPoliciesRequest {
        record_kind: proto::CapabilityPolicyRecordKind::Policy as i32,
        page: Some(proto::PageRequest {
            page_size: 1,
            page_token: None,
        }),
    };
    let token = client
        .list_policies(request(page.clone()))
        .await
        .unwrap()
        .into_inner()
        .page
        .unwrap()
        .next_page_token
        .unwrap();
    let mut next = page;
    next.page.as_mut().unwrap().page_token = Some(token);
    assert!(client
        .list_policies(authenticated(
            next,
            "foreign-token-000000000000000000000000000"
        ))
        .await
        .is_err());
    let foreign = client
        .get_policy(authenticated(
            proto::GetPolicyRequest {
                id: "p".into(),
                record_kind: proto::CapabilityPolicyRecordKind::Policy as i32,
            },
            "foreign-token-000000000000000000000000000",
        ))
        .await
        .unwrap()
        .into_inner();
    assert!(foreign.policy.is_none());
    drop(client);
    assert!(node.shutdown().await.unwrap().clean);
}
#[tokio::test]
async fn policy_response_limit_rejects_apply_before_a_record_or_receipt_is_persisted() {
    let directory = TempDir::new().unwrap();
    let mut settings = configured(&directory);
    settings.management = latent_wire::management::ManagementLimits {
        max_response_bytes: 512,
        max_metadata_bytes: 512,
        max_string_bytes: 512,
        max_id_bytes: 512,
        max_page_token_bytes: 512,
        max_collection_entries: 512,
        max_route_services: 512,
        max_route_revisions: 512,
        ..settings.management
    };
    let catalogs = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    let owner = catalogs.policies.as_ref().unwrap().handle();
    let node = Box::pin(super::super::super::StandaloneNode::start_with_catalogs(
        settings,
        catalogs,
        tokio::runtime::Handle::current(),
        crate::standalone::RuntimeThreads::default(),
    ))
    .await
    .unwrap();
    let mut client = proto::policy_service_client::PolicyServiceClient::connect(format!(
        "http://{}",
        node.endpoint()
    ))
    .await
    .unwrap();
    let id = "p".repeat(128);
    let value = apply(
        &id,
        proto::CapabilityPolicyRecordKind::Policy,
        &serde_json::json!({"formatVersion":1,"tenant":"tests","rules":[]}),
    );
    assert_eq!(
        client
            .apply_policy(request(value))
            .await
            .unwrap_err()
            .code(),
        tonic::Code::ResourceExhausted
    );
    assert!(owner
        .store()
        .outcome(
            "tests",
            &format!("create-{id}"),
            std::time::Instant::now() + Duration::from_secs(5)
        )
        .unwrap()
        .value()
        .is_none());
    assert!(owner
        .store()
        .get(
            "tests",
            latent_policy::capability::RecordKind::Policy,
            &id,
            4096,
            std::time::Instant::now() + Duration::from_secs(5)
        )
        .unwrap()
        .value()
        .is_none());
    drop(client);
    drop(owner);
    assert!(node.shutdown().await.unwrap().clean);
}
