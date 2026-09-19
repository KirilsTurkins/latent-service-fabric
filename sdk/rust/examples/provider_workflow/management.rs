use super::{
    config::{field, options, Configuration},
    require, Assertions, ClientProfile, Result, RpcClient,
};
use latent_sdk::management::{
    ApplyPolicyRequest, AuditAckStatus, CapabilityPolicyRecordKind, FailureCategory,
    GetPolicyOperationRequest, GetPolicyRequest, ListCapabilitiesRequest, ListPoliciesRequest,
    ObjectMetadata, OutcomeKnowledge, PageRequest, Policy,
};

fn create_request(
    config: &Configuration,
    operation_id: &str,
    id: &str,
) -> Result<ApplyPolicyRequest> {
    Ok(ApplyPolicyRequest {
        operation_id: operation_id.into(),
        expected_generation: Some(0),
        policy: Some(Policy {
            id: id.into(),
            metadata: Some(ObjectMetadata {
                name: id.into(),
                tenant: Some("tests".into()),
                ..Default::default()
            }),
            document: config.field("policyDocument")?.into(),
            language: "lsf-capability-policy-v1".into(),
            record_kind: CapabilityPolicyRecordKind::POLICY,
            ..Default::default()
        }),
    })
}

pub async fn run(
    config: &Configuration,
    client: &RpcClient,
    assertions: &mut Assertions,
) -> Result<(String, u64)> {
    inspect(config, client).await?;
    assertions.insert("boundedPages", true);
    assertions.insert("providerInspection", true);
    let operation_id = "rust-policy-create".to_owned();
    let id = "rust-example-policy";
    let request = create_request(config, &operation_id, id)?;
    let created = client
        .apply_policy(request.clone(), options())
        .await
        .map_err(|_| "policy-mutation-rpc")?;
    let audit = created
        .metadata
        .audit_ack
        .ok_or("audit-acknowledgement-absent")?;
    require(audit.status == AuditAckStatus::DURABLE, "audit-not-durable")?;
    let attempt = audit
        .attempt_sequence
        .filter(|value| *value > 0)
        .ok_or("audit-attempt-absent")?;
    let receipt = created.value.receipt.ok_or("mutation-receipt-absent")?;
    require(receipt.operation_id == operation_id, "mutation-identity")?;
    let inspected = client
        .get_policy(
            GetPolicyRequest {
                id: id.into(),
                record_kind: CapabilityPolicyRecordKind::POLICY,
            },
            options(),
        )
        .await
        .map_err(|_| "policy-inspection-rpc")?;
    require(
        inspected
            .value
            .policy
            .is_some_and(|value| value.generation == receipt.generation),
        "policy-generation",
    )?;
    let known = client
        .get_policy_operation(
            GetPolicyOperationRequest {
                operation_id: operation_id.clone(),
            },
            options(),
        )
        .await
        .map_err(|_| "policy-operation-rpc")?;
    require(
        known.value.receipt.as_ref() == Some(&receipt),
        "operation-recovery-receipt",
    )?;
    let absent = client
        .get_policy_operation(
            GetPolicyOperationRequest {
                operation_id: "rust-unknown-operation".into(),
            },
            options(),
        )
        .await
        .map_err(|_| "unknown-operation-rpc")?;
    require(
        absent.value.receipt.is_none() && absent.metadata.outcome == OutcomeKnowledge::UNKNOWN,
        "absent-operation-not-unknown",
    )?;
    assertions.insert("mutationReceipt", true);
    let replay = client
        .apply_policy(request.clone(), options())
        .await
        .map_err(|_| "policy-replay-rpc")?;
    require(
        replay.value.receipt.as_ref() == Some(&receipt),
        "exact-replay-receipt",
    )?;
    assertions.insert("exactReplay", true);
    let conflicting = ApplyPolicyRequest {
        operation_id: "rust-stale-precondition".into(),
        ..request
    };
    let failure = client
        .apply_policy(conflicting, options())
        .await
        .err()
        .ok_or("policy-precondition-not-enforced")?;
    require(
        failure.category == FailureCategory::RPC && failure.outcome == OutcomeKnowledge::OBSERVED,
        "policy-precondition-facts",
    )?;
    assertions.insert("preconditionConflict", true);
    Ok((operation_id, attempt))
}

async fn inspect(config: &Configuration, client: &RpcClient) -> Result<()> {
    let request = ListPoliciesRequest {
        record_kind: CapabilityPolicyRecordKind::POLICY,
        page: Some(PageRequest {
            page_size: 1,
            page_token: None,
        }),
    };
    let first = client
        .list_policies(request.clone(), options())
        .await
        .map_err(|_| "policy-first-page-rpc")?;
    require(first.value.policies.len() == 1, "policy-first-page-size")?;
    let token = first
        .value
        .page
        .and_then(|value| value.next_page_token)
        .ok_or("policy-next-token-absent")?;
    let next = client
        .list_policies(
            ListPoliciesRequest {
                page: Some(PageRequest {
                    page_size: 1,
                    page_token: Some(token),
                }),
                ..request
            },
            options(),
        )
        .await
        .map_err(|_| "policy-next-page-rpc")?;
    require(
        next.value.policies.len() == 1 && next.value.policies[0].id != first.value.policies[0].id,
        "policy-page-identity",
    )?;
    let providers = client
        .list_capabilities(
            ListCapabilitiesRequest {
                deployment_id: field(config.target("http"), "route")?.into(),
                page: Some(PageRequest {
                    page_size: 1,
                    page_token: None,
                }),
                ..Default::default()
            },
            options(),
        )
        .await
        .map_err(|_| "capability-inspection-rpc")?;
    require(
        providers.value.capabilities.len() == 1
            && providers.value.capabilities[0].contract == "latent:http/client@0.2.0",
        "provider-inspection-value",
    )
}
