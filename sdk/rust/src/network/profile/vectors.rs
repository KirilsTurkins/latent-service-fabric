#![allow(clippy::too_many_lines)]

use crate::management::*;
use latent_rpc::{control::v1 as control, invocation::v1 as invocation};
use prost::Message;
use std::collections::BTreeMap;

#[test]
fn shared_vectors_roundtrip_through_actual_protobuf() {
    {
        let value = InvokeRequest {
            target: Some(InvocationTarget {
                tenant: "tenant-a".into(),
                service: "echo".into(),
                contract: "example:echo/api@1.0.0".into(),
                function: "echo".into(),
                ..Default::default()
            }),
            payload: vec![0, 1, 2, 255],
            media_type: "application/octet-stream".into(),
            priority: 0_u32,
            budget: Some(ResourceBudget {
                cpu_fuel: 18_446_744_073_709_551_615_u64,
                memory_bytes: 9_223_372_036_854_775_808_u64,
                child_calls: 0_u32,
                outbound_requests: 0_u32,
                state_read_bytes: 0_u64,
                state_write_bytes: 0_u64,
                blob_read_bytes: 0_u64,
                blob_write_bytes: 0_u64,
                log_bytes: 0_u64,
                effect_count: 0_u32,
                ..Default::default()
            }),
            metadata: BTreeMap::from([("trace".into(), "redacted".into())]),
            ..Default::default()
        };
        let encoded = invocation::InvokeRequest::from(value.clone()).encode_to_vec();
        let decoded = invocation::InvokeRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            InvokeRequest::from(decoded),
            value,
            "invoke-absent-identity-and-deadlines"
        );
    }
    {
        let value = InvokeRequest {
            activation_id: Some(String::new()),
            parent_activation_id: Some("parent-a".into()),
            root_activation_id: Some(String::new()),
            target: Some(InvocationTarget {
                tenant: String::new(),
                service: String::new(),
                contract: String::new(),
                function: String::new(),
                route: Some(String::new()),
            }),
            payload: vec![],
            media_type: String::new(),
            deadline_unix_millis: Some(0_u64),
            priority: 0_u32,
            idempotency_key: Some(String::new()),
            budget: Some(ResourceBudget {
                cpu_fuel: 0_u64,
                memory_bytes: 0_u64,
                child_calls: 0_u32,
                outbound_requests: 0_u32,
                state_read_bytes: 0_u64,
                state_write_bytes: 0_u64,
                blob_read_bytes: 0_u64,
                blob_write_bytes: 0_u64,
                log_bytes: 0_u64,
                effect_count: 0_u32,
                wall_time_limit_millis: Some(0_u64),
            }),
            metadata: BTreeMap::from([]),
        };
        let encoded = invocation::InvokeRequest::from(value.clone()).encode_to_vec();
        let decoded = invocation::InvokeRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            InvokeRequest::from(decoded),
            value,
            "invoke-present-invalid-and-zero-not-absence"
        );
    }
    {
        let value = InvokeRequest {
            activation_id: Some("activation-a".into()),
            parent_activation_id: Some("parent-a".into()),
            root_activation_id: Some("root-a".into()),
            payload: vec![],
            media_type: String::new(),
            deadline_unix_millis: Some(18_446_744_073_709_551_615_u64),
            priority: 4_294_967_295_u32,
            idempotency_key: Some("not-an-authority-or-retry-key".into()),
            metadata: BTreeMap::from([]),
            ..Default::default()
        };
        let encoded = invocation::InvokeRequest::from(value.clone()).encode_to_vec();
        let decoded = invocation::InvokeRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            InvokeRequest::from(decoded),
            value,
            "invoke-known-identity-full-width-deadline-and-priority"
        );
    }
    {
        let value = ResourceBudget {
            cpu_fuel: 18_446_744_073_709_551_615_u64,
            memory_bytes: 18_446_744_073_709_551_615_u64,
            child_calls: 4_294_967_295_u32,
            outbound_requests: 4_294_967_295_u32,
            state_read_bytes: 18_446_744_073_709_551_615_u64,
            state_write_bytes: 18_446_744_073_709_551_615_u64,
            blob_read_bytes: 18_446_744_073_709_551_615_u64,
            blob_write_bytes: 18_446_744_073_709_551_615_u64,
            log_bytes: 18_446_744_073_709_551_615_u64,
            effect_count: 4_294_967_295_u32,
            wall_time_limit_millis: Some(18_446_744_073_709_551_615_u64),
        };
        let encoded = control::ResourceBudget::from(value.clone()).encode_to_vec();
        let decoded = control::ResourceBudget::decode(encoded.as_slice()).unwrap();
        assert_eq!(ResourceBudget::from(decoded), value, "full-resource-budget");
    }
    {
        let value = InvokeResponse{activation_id: "activation-a".into(), revision_id: "revision-a".into(), release_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(), route_generation: 18_446_744_073_709_551_615_u64, success: Some(Success{payload: vec![0, 1, 2, 255], media_type: "application/octet-stream".into(), committed_state_version: Some(String::new()), effect_ids: vec!["effect-a".into(), "effect-b".into()], metadata: BTreeMap::from([("result".into(), "redacted".into())])}), consumption: Some(BudgetConsumption{cpu_fuel: 18_446_744_073_709_551_615_u64, peak_memory_bytes: 0_u64, wall_time_micros: 9_007_199_254_740_993_u64, child_calls: 0_u32, outbound_requests: 0_u32, state_read_bytes: 0_u64, state_write_bytes: 0_u64, blob_read_bytes: 0_u64, blob_write_bytes: 0_u64, log_bytes: 0_u64, effect_count: 0_u32}), publication_id: Some("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111".into()), ..Default::default()};
        let encoded = invocation::InvokeResponse::try_from(value.clone())
            .unwrap()
            .encode_to_vec();
        let decoded = invocation::InvokeResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            InvokeResponse::from(decoded),
            value,
            "invoke-success-retains-publication-and-component"
        );
    }
    {
        let value = InvokeResponse{activation_id: "activation-a".into(), revision_id: "revision-a".into(), release_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(), route_generation: 9_223_372_036_854_775_808_u64, declared_error: Some(DeclaredError{code: "uncertain".into(), message: "provider outcome unknown".into(), payload: vec![0, 1, 2, 255], media_type: "application/octet-stream".into(), metadata: BTreeMap::from([("contract".into(), "latent:http/streaming@0.3.0".into())])}), consumption: Some(BudgetConsumption{cpu_fuel: 0_u64, peak_memory_bytes: 0_u64, wall_time_micros: 0_u64, child_calls: 0_u32, outbound_requests: 0_u32, state_read_bytes: 0_u64, state_write_bytes: 0_u64, blob_read_bytes: 0_u64, blob_write_bytes: 18_446_744_073_709_551_615_u64, log_bytes: 0_u64, effect_count: 0_u32}), publication_id: Some("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111".into()), ..Default::default()};
        let encoded = invocation::InvokeResponse::try_from(value.clone())
            .unwrap()
            .encode_to_vec();
        let decoded = invocation::InvokeResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            InvokeResponse::from(decoded),
            value,
            "typed-declared-provider-uncertainty-retains-receipt"
        );
    }
    {
        let value = InvokeResponse {
            activation_id: "activation-a".into(),
            revision_id: String::new(),
            release_digest: String::new(),
            route_generation: 0_u64,
            platform_failure: Some(PlatformError {
                code: "permission-denied".into(),
                message: "capability-provider-failed".into(),
                retryable: false,
                detail_items: vec![
                    ErrorDetail {
                        kind: "capability-observation".into(),
                        fields: BTreeMap::from([
                            ("capability".into(), "latent:http/streaming@0.3.0".into()),
                            ("state".into(), "policy-revoked".into()),
                        ]),
                    },
                    ErrorDetail {
                        kind: "future-detail".into(),
                        fields: BTreeMap::from([("bounded".into(), "preserved".into())]),
                    },
                ],
            }),
            consumption: Some(BudgetConsumption {
                cpu_fuel: 0_u64,
                peak_memory_bytes: 0_u64,
                wall_time_micros: 0_u64,
                child_calls: 0_u32,
                outbound_requests: 0_u32,
                state_read_bytes: 0_u64,
                state_write_bytes: 0_u64,
                blob_read_bytes: 0_u64,
                blob_write_bytes: 0_u64,
                log_bytes: 18_446_744_073_709_551_615_u64,
                effect_count: 0_u32,
            }),
            ..Default::default()
        };
        let encoded = invocation::InvokeResponse::try_from(value.clone())
            .unwrap()
            .encode_to_vec();
        let decoded = invocation::InvokeResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            InvokeResponse::from(decoded),
            value,
            "typed-platform-capability-failure-retains-detail-items"
        );
    }
    {
        let value = InvokeResponse {
            activation_id: "activation-a".into(),
            revision_id: String::new(),
            release_digest: String::new(),
            route_generation: 0_u64,
            success: Some(Success {
                payload: vec![],
                media_type: String::new(),
                effect_ids: vec![],
                metadata: BTreeMap::from([]),
                ..Default::default()
            }),
            publication_id: Some(String::new()),
            ..Default::default()
        };
        let encoded = invocation::InvokeResponse::try_from(value.clone())
            .unwrap()
            .encode_to_vec();
        let decoded = invocation::InvokeResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            InvokeResponse::from(decoded),
            value,
            "present-invalid-publication-not-legacy"
        );
    }
    {
        let value = InvokeResponse {
            activation_id: "activation-a".into(),
            revision_id: String::new(),
            release_digest: String::new(),
            route_generation: 0_u64,
            success: Some(Success {
                payload: vec![],
                media_type: String::new(),
                effect_ids: vec![],
                metadata: BTreeMap::from([]),
                ..Default::default()
            }),
            platform_failure: Some(PlatformError {
                code: "internal".into(),
                message: String::new(),
                retryable: false,
                detail_items: vec![],
            }),
            ..Default::default()
        };
        assert!(
            invocation::InvokeResponse::try_from(value).is_err(),
            "contradictory-outcome-retained-for-rejection"
        );
    }
    {
        let value = CancelRequest {
            activation_id: "activation-a".into(),
            reason: "caller-requested".into(),
        };
        let encoded = invocation::CancelRequest::from(value.clone()).encode_to_vec();
        let decoded = invocation::CancelRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            CancelRequest::from(decoded),
            value,
            "cancel-request-known-id"
        );
    }
    {
        let value = CancelResponse {
            disposition: CancelDisposition(1),
            ..Default::default()
        };
        let encoded = invocation::CancelResponse::from(value.clone()).encode_to_vec();
        let decoded = invocation::CancelResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            CancelResponse::from(decoded),
            value,
            "cancel-accepted-not-cleanup"
        );
    }
    {
        let value = CancelResponse {
            disposition: CancelDisposition(2),
            terminal_state: Some("completed".into()),
        };
        let encoded = invocation::CancelResponse::from(value.clone()).encode_to_vec();
        let decoded = invocation::CancelResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            CancelResponse::from(decoded),
            value,
            "cancel-already-terminal"
        );
    }
    {
        let value = CancelResponse {
            disposition: CancelDisposition(3),
            ..Default::default()
        };
        let encoded = invocation::CancelResponse::from(value.clone()).encode_to_vec();
        let decoded = invocation::CancelResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            CancelResponse::from(decoded),
            value,
            "cancel-not-found-not-nonexecution"
        );
    }
    {
        let value = CancelResponse {
            disposition: CancelDisposition(0),
            terminal_state: Some(String::new()),
        };
        let encoded = invocation::CancelResponse::from(value.clone()).encode_to_vec();
        let decoded = invocation::CancelResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            CancelResponse::from(decoded),
            value,
            "cancel-unspecified-not-accepted"
        );
    }
    {
        let value = CancelResponse {
            disposition: CancelDisposition(91),
            terminal_state: Some("future-terminal-state".into()),
        };
        let encoded = invocation::CancelResponse::from(value.clone()).encode_to_vec();
        let decoded = invocation::CancelResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(CancelResponse::from(decoded), value, "cancel-unknown-enum");
    }
    {
        let value = CancelResponse {
            disposition: CancelDisposition(-2_147_483_648),
            ..Default::default()
        };
        let encoded = invocation::CancelResponse::from(value.clone()).encode_to_vec();
        let decoded = invocation::CancelResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(CancelResponse::from(decoded), value, "cancel-negative-enum");
    }
    {
        let value = GetActivationRequest {
            activation_id: "activation-a".into(),
        };
        let encoded = invocation::GetActivationRequest::from(value.clone()).encode_to_vec();
        let decoded = invocation::GetActivationRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            GetActivationRequest::from(decoded),
            value,
            "get-activation-recovery"
        );
    }
    {
        let value = ActivationStatus {
            activation_id: "activation-a".into(),
            phase: "running".into(),
            last_updated_unix_millis: 18_446_744_073_709_551_615_u64,
            metadata: BTreeMap::from([]),
            ..Default::default()
        };
        let encoded = invocation::ActivationStatus::try_from(value.clone())
            .unwrap()
            .encode_to_vec();
        let decoded = invocation::ActivationStatus::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ActivationStatus::from(decoded),
            value,
            "activation-running-absent-terminal"
        );
    }
    {
        let value = ActivationStatus {
            activation_id: "activation-a".into(),
            phase: "terminal".into(),
            terminal_state: Some("failed".into()),
            last_updated_unix_millis: 0_u64,
            metadata: BTreeMap::from([]),
            platform_failure: Some(PlatformError {
                code: "resource-exhausted".into(),
                message: "capability-capacity".into(),
                retryable: false,
                detail_items: vec![ErrorDetail {
                    kind: "budget".into(),
                    fields: BTreeMap::from([("resource".into(), "buffer-bytes".into())]),
                }],
            }),
            final_consumption: Some(BudgetConsumption {
                cpu_fuel: 0_u64,
                peak_memory_bytes: 18_446_744_073_709_551_615_u64,
                wall_time_micros: 0_u64,
                child_calls: 0_u32,
                outbound_requests: 0_u32,
                state_read_bytes: 0_u64,
                state_write_bytes: 0_u64,
                blob_read_bytes: 0_u64,
                blob_write_bytes: 0_u64,
                log_bytes: 0_u64,
                effect_count: 0_u32,
            }),
            terminal_at_unix_millis: Some(0_u64),
            ..Default::default()
        };
        let encoded = invocation::ActivationStatus::try_from(value.clone())
            .unwrap()
            .encode_to_vec();
        let decoded = invocation::ActivationStatus::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ActivationStatus::from(decoded),
            value,
            "activation-terminal-typed-failure"
        );
    }
    {
        let value = ActivationStatus {
            activation_id: "activation-a".into(),
            phase: "terminal".into(),
            terminal_state: Some("completed".into()),
            last_updated_unix_millis: 0_u64,
            metadata: BTreeMap::from([]),
            succeeded: Some(ActivationSuccessSummary {
                committed_state_version: Some("state-a".into()),
                effect_ids: vec!["effect-a".into()],
                metadata: BTreeMap::from([("retained".into(), "true".into())]),
            }),
            final_consumption: Some(BudgetConsumption {
                cpu_fuel: 0_u64,
                peak_memory_bytes: 0_u64,
                wall_time_micros: 0_u64,
                child_calls: 0_u32,
                outbound_requests: 0_u32,
                state_read_bytes: 0_u64,
                state_write_bytes: 0_u64,
                blob_read_bytes: 0_u64,
                blob_write_bytes: 0_u64,
                log_bytes: 0_u64,
                effect_count: 4_294_967_295_u32,
            }),
            terminal_at_unix_millis: Some(18_446_744_073_709_551_615_u64),
            ..Default::default()
        };
        let encoded = invocation::ActivationStatus::try_from(value.clone())
            .unwrap()
            .encode_to_vec();
        let decoded = invocation::ActivationStatus::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ActivationStatus::from(decoded),
            value,
            "activation-terminal-success-summary"
        );
    }
    {
        let value = GetPolicyResponse {
            ..Default::default()
        };
        let encoded = control::GetPolicyResponse::from(value.clone()).encode_to_vec();
        let decoded = control::GetPolicyResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(GetPolicyResponse::from(decoded), value, "policy-absence");
    }
    {
        let value = GetPolicyRequest {
            id: "policy-a".into(),
            record_kind: CapabilityPolicyRecordKind(1),
        };
        let encoded = control::GetPolicyRequest::from(value.clone()).encode_to_vec();
        let decoded = control::GetPolicyRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(GetPolicyRequest::from(decoded), value, "policy-record-kind");
    }
    {
        let value = GetPolicyRequest {
            id: "binding-a".into(),
            record_kind: CapabilityPolicyRecordKind(2),
        };
        let encoded = control::GetPolicyRequest::from(value.clone()).encode_to_vec();
        let decoded = control::GetPolicyRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            GetPolicyRequest::from(decoded),
            value,
            "provider-binding-record-kind"
        );
    }
    {
        let value = Policy {
            id: "future-record".into(),
            metadata: Some(ObjectMetadata {
                name: "future-record".into(),
                tenant: Some(String::new()),
                namespace: Some(String::new()),
                labels: BTreeMap::from([("sampled".into(), "true".into())]),
                annotations: BTreeMap::from([("descriptive".into(), "not-authority".into())]),
            }),
            document: String::new(),
            generation: 18_446_744_073_709_551_615_u64,
            language: String::new(),
            record_kind: CapabilityPolicyRecordKind(2_147_483_647),
            content_digest: String::new(),
            revoked: true,
        };
        let encoded = control::Policy::from(value.clone()).encode_to_vec();
        let decoded = control::Policy::decode(encoded.as_slice()).unwrap();
        assert_eq!(Policy::from(decoded), value, "unknown-policy-kind");
    }
    {
        let value = ApplyPolicyRequest {
            operation_id: "operation-a".into(),
            ..Default::default()
        };
        let encoded = control::ApplyPolicyRequest::from(value.clone()).encode_to_vec();
        let decoded = control::ApplyPolicyRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ApplyPolicyRequest::from(decoded),
            value,
            "apply-missing-generation"
        );
    }
    {
        let value = ApplyPolicyRequest {
            expected_generation: Some(0_u64),
            operation_id: String::new(),
            ..Default::default()
        };
        let encoded = control::ApplyPolicyRequest::from(value.clone()).encode_to_vec();
        let decoded = control::ApplyPolicyRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ApplyPolicyRequest::from(decoded),
            value,
            "apply-present-empty-operation"
        );
    }
    {
        let value = ApplyPolicyRequest{policy: Some(Policy{id: "policy-a".into(), metadata: Some(ObjectMetadata{name: "policy-a".into(), tenant: Some("tenant-a".into()), labels: BTreeMap::from([]), annotations: BTreeMap::from([]), ..Default::default()}), document: "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"rules\":[{\"id\":\"deny\",\"effect\":\"deny\",\"principals\":[{\"kind\":\"user\",\"subject\":\"fixture-user\"}],\"services\":[\"echo\"],\"publications\":[\"publication:sha256:1111111111111111111111111111111111111111111111111111111111111111\"],\"capability\":\"latent:secrets/reader@0.1.0\",\"operations\":[\"read\"],\"resources\":{\"kind\":\"secrets\",\"references\":[\"fixture-selector\"]},\"ceiling\":{\"operations\":0,\"inputBytes\":0,\"outputBytes\":0,\"wallTimeMillis\":0}}]}".into(), generation: 0_u64, language: "lsf-capability-policy-v1".into(), record_kind: CapabilityPolicyRecordKind(1), content_digest: String::new(), revoked: false}), expected_generation: Some(0_u64), operation_id: "operation-a".into()};
        let encoded = control::ApplyPolicyRequest::from(value.clone()).encode_to_vec();
        let decoded = control::ApplyPolicyRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ApplyPolicyRequest::from(decoded),
            value,
            "apply-create-policy-zero-generation"
        );
    }
    {
        let value = ApplyPolicyRequest{policy: Some(Policy{id: "binding-a".into(), metadata: Some(ObjectMetadata{name: "binding-a".into(), tenant: Some("tenant-a".into()), labels: BTreeMap::from([]), annotations: BTreeMap::from([]), ..Default::default()}), document: "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"capability\":\"latent:secrets/reader@0.1.0\",\"providerProfile\":\"local-secrets-v1\",\"configurationDigest\":\"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"configurationEpoch\":18446744073709551615,\"restriction\":{\"operations\":[],\"ceiling\":{\"operations\":0,\"inputBytes\":18446744073709551615,\"outputBytes\":0,\"wallTimeMillis\":0}}}".into(), generation: 0_u64, language: "lsf-provider-binding-v1".into(), record_kind: CapabilityPolicyRecordKind(2), content_digest: String::new(), revoked: false}), expected_generation: Some(18_446_744_073_709_551_615_u64), operation_id: "operation-binding".into()};
        let encoded = control::ApplyPolicyRequest::from(value.clone()).encode_to_vec();
        let decoded = control::ApplyPolicyRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ApplyPolicyRequest::from(decoded),
            value,
            "apply-binding-max-precondition-and-opaque-limit-document"
        );
    }
    {
        let value = ListPoliciesRequest {
            record_kind: CapabilityPolicyRecordKind(1),
            ..Default::default()
        };
        let encoded = control::ListPoliciesRequest::from(value.clone()).encode_to_vec();
        let decoded = control::ListPoliciesRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ListPoliciesRequest::from(decoded),
            value,
            "policy-page-absent"
        );
    }
    {
        let value = ListPoliciesRequest {
            record_kind: CapabilityPolicyRecordKind(2),
            page: Some(PageRequest {
                page_size: 0_u32,
                ..Default::default()
            }),
        };
        let encoded = control::ListPoliciesRequest::from(value.clone()).encode_to_vec();
        let decoded = control::ListPoliciesRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ListPoliciesRequest::from(decoded),
            value,
            "policy-page-zero-invalid"
        );
    }
    {
        let value = ListPoliciesRequest {
            record_kind: CapabilityPolicyRecordKind(1),
            page: Some(PageRequest {
                page_size: 1_u32,
                page_token: Some(String::new()),
            }),
        };
        let encoded = control::ListPoliciesRequest::from(value.clone()).encode_to_vec();
        let decoded = control::ListPoliciesRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ListPoliciesRequest::from(decoded),
            value,
            "policy-page-empty-token-invalid"
        );
    }
    {
        let value = ListPoliciesResponse {
            policies: vec![Policy {
                id: "policy-a".into(),
                document: String::new(),
                generation: 18_446_744_073_709_551_615_u64,
                language: String::new(),
                record_kind: CapabilityPolicyRecordKind(1),
                content_digest:
                    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(),
                revoked: true,
                ..Default::default()
            }],
            catalog_generation: 18_446_744_073_709_551_615_u64,
            page: Some(PageResponse {
                next_page_token: Some("opaque-policy-cursor".into()),
            }),
        };
        let encoded = control::ListPoliciesResponse::from(value.clone()).encode_to_vec();
        let decoded = control::ListPoliciesResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ListPoliciesResponse::from(decoded),
            value,
            "policy-page-first"
        );
    }
    {
        let value = ListPoliciesResponse {
            policies: vec![],
            catalog_generation: 18_446_744_073_709_551_615_u64,
            page: Some(PageResponse {
                ..Default::default()
            }),
        };
        let encoded = control::ListPoliciesResponse::from(value.clone()).encode_to_vec();
        let decoded = control::ListPoliciesResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ListPoliciesResponse::from(decoded),
            value,
            "policy-page-last"
        );
    }
    {
        let value = ListPoliciesRequest {
            record_kind: CapabilityPolicyRecordKind(1),
            page: Some(PageRequest {
                page_size: 1_u32,
                page_token: Some("opaque-policy-cursor".into()),
            }),
        };
        let encoded = control::ListPoliciesRequest::from(value.clone()).encode_to_vec();
        let decoded = control::ListPoliciesRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ListPoliciesRequest::from(decoded),
            value,
            "policy-next-page-request"
        );
    }
    {
        let value = ApplyPolicyResponse {
            policy: Some(Policy {
                id: "policy-a".into(),
                document: String::new(),
                generation: 18_446_744_073_709_551_615_u64,
                language: String::new(),
                record_kind: CapabilityPolicyRecordKind(1),
                content_digest:
                    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(),
                revoked: false,
                ..Default::default()
            }),
            receipt: Some(CapabilityPolicyOperation {
                operation_id: "operation-a".into(),
                tenant: "tenant-a".into(),
                id: "policy-a".into(),
                record_kind: CapabilityPolicyRecordKind(1),
                generation: 18_446_744_073_709_551_615_u64,
                content_digest:
                    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(),
                revoked: false,
            }),
        };
        let encoded = control::ApplyPolicyResponse::from(value.clone()).encode_to_vec();
        let decoded = control::ApplyPolicyResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ApplyPolicyResponse::from(decoded),
            value,
            "apply-retains-original-receipt"
        );
    }
    {
        let value = GetPolicyOperationRequest {
            operation_id: "operation-a".into(),
        };
        let encoded = control::GetPolicyOperationRequest::from(value.clone()).encode_to_vec();
        let decoded = control::GetPolicyOperationRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            GetPolicyOperationRequest::from(decoded),
            value,
            "get-policy-operation-known-id"
        );
    }
    {
        let value = GetPolicyOperationResponse {
            ..Default::default()
        };
        let encoded = control::GetPolicyOperationResponse::from(value.clone()).encode_to_vec();
        let decoded = control::GetPolicyOperationResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            GetPolicyOperationResponse::from(decoded),
            value,
            "operation-recovery-not-retained-is-unknown"
        );
    }
    {
        let value = GetPolicyOperationResponse {
            receipt: Some(CapabilityPolicyOperation {
                operation_id: "operation-a".into(),
                tenant: "tenant-a".into(),
                id: "policy-a".into(),
                record_kind: CapabilityPolicyRecordKind(1),
                generation: 18_446_744_073_709_551_615_u64,
                content_digest:
                    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(),
                revoked: false,
            }),
        };
        let encoded = control::GetPolicyOperationResponse::from(value.clone()).encode_to_vec();
        let decoded = control::GetPolicyOperationResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            GetPolicyOperationResponse::from(decoded),
            value,
            "operation-recovery-original-receipt"
        );
    }
    {
        let value = ListCapabilitiesRequest {
            deployment_id: "deployment-a".into(),
            include_node_usage: false,
            ..Default::default()
        };
        let encoded = control::ListCapabilitiesRequest::from(value.clone()).encode_to_vec();
        let decoded = control::ListCapabilitiesRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ListCapabilitiesRequest::from(decoded),
            value,
            "capabilities-absent-page-default"
        );
    }
    {
        let value = ListCapabilitiesRequest {
            page: Some(PageRequest {
                page_size: 0_u32,
                ..Default::default()
            }),
            deployment_id: "deployment-a".into(),
            include_node_usage: false,
            ..Default::default()
        };
        let encoded = control::ListCapabilitiesRequest::from(value.clone()).encode_to_vec();
        let decoded = control::ListCapabilitiesRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ListCapabilitiesRequest::from(decoded),
            value,
            "capabilities-zero-page-default"
        );
    }
    {
        let value = ListCapabilitiesRequest {
            contract_prefix: Some(String::new()),
            provider: Some(String::new()),
            page: Some(PageRequest {
                page_size: 128_u32,
                ..Default::default()
            }),
            deployment_id: "deployment-a".into(),
            include_node_usage: true,
        };
        let encoded = control::ListCapabilitiesRequest::from(value.clone()).encode_to_vec();
        let decoded = control::ListCapabilitiesRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ListCapabilitiesRequest::from(decoded),
            value,
            "capabilities-present-empty-filters"
        );
    }
    {
        let value = ListCapabilitiesRequest {
            page: Some(PageRequest {
                page_size: 1_u32,
                ..Default::default()
            }),
            deployment_id: String::new(),
            include_node_usage: false,
            ..Default::default()
        };
        let encoded = control::ListCapabilitiesRequest::from(value.clone()).encode_to_vec();
        let decoded = control::ListCapabilitiesRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ListCapabilitiesRequest::from(decoded),
            value,
            "capabilities-explicit-deployment-required"
        );
    }
    {
        let value = ListCapabilitiesRequest {
            page: Some(PageRequest {
                page_size: 4_294_967_295_u32,
                ..Default::default()
            }),
            deployment_id: "deployment-a".into(),
            include_node_usage: false,
            ..Default::default()
        };
        let encoded = control::ListCapabilitiesRequest::from(value.clone()).encode_to_vec();
        let decoded = control::ListCapabilitiesRequest::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ListCapabilitiesRequest::from(decoded),
            value,
            "capabilities-page-too-large"
        );
    }
    {
        let value = ListCapabilitiesResponse{capabilities: vec![CapabilityDescriptor{id: "latent:secrets/reader@0.1.0".into(), contract: "latent:secrets/reader@0.1.0".into(), provider: "local-secrets-v1".into(), operations: vec!["read".into()], attributes: BTreeMap::from([]), inspection: Some(CapabilityBindingInspection{definition_digest: Some(String::new()), provider_binding: Some(CapabilityInspectionPolicy{id: "binding-a".into(), revision: 18_446_744_073_709_551_615_u64, digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb".into()}), policies: vec![CapabilityInspectionPolicy{id: "policy-a".into(), revision: 9_223_372_036_854_775_808_u64, digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into()}], provider_profile: "local-secrets-v1".into(), provider_configuration_digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb".into(), provider_configuration_epoch: 18_446_744_073_709_551_615_u64, state: "provider-configuration-changed".into()})}, CapabilityDescriptor{id: "future-capability".into(), contract: "future-contract".into(), provider: "future-provider".into(), operations: vec![], attributes: BTreeMap::from([("descriptive".into(), "not-authority".into())]), ..Default::default()}], page: Some(PageResponse{next_page_token: Some("opaque-capability-cursor".into())}), revision: Some(CapabilityInspectionRevision{deployment_id: "deployment-a".into(), revision_id: "revision-a".into(), component_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(), publication_id: Some("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111".into()), route_generation: 18_446_744_073_709_551_615_u64, catalog_transaction: 9_223_372_036_854_775_808_u64}), tenant_usage: Some(CapabilityResourceUsage{scope: "tenant".into(), counters: BTreeMap::from([("sessions".into(), 18_446_744_073_709_551_615_u64), ("calls".into(), 0_u64)]), unavailable: vec!["fixture-owner-unavailable".into()]}), state: "sampled".into(), ..Default::default()};
        let encoded = control::ListCapabilitiesResponse::from(value.clone()).encode_to_vec();
        let decoded = control::ListCapabilitiesResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ListCapabilitiesResponse::from(decoded),
            value,
            "redacted-capability-provider-inspection"
        );
    }
    {
        let value = ListCapabilitiesResponse {
            capabilities: vec![],
            node_usage: Some(CapabilityResourceUsage {
                scope: "node".into(),
                counters: BTreeMap::from([]),
                unavailable: vec![
                    "provider-pools-no-retained-owner".into(),
                    "audit-owner-not-configured".into(),
                ],
            }),
            state: "binding-plan-unavailable".into(),
            ..Default::default()
        };
        let encoded = control::ListCapabilitiesResponse::from(value.clone()).encode_to_vec();
        let decoded = control::ListCapabilitiesResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            ListCapabilitiesResponse::from(decoded),
            value,
            "missing-provider-plan-not-zero-usage"
        );
    }
    {
        let value = CapabilityInspectionCeiling {
            operations: 0_u32,
            input_bytes: 18_446_744_073_709_551_615_u64,
            output_bytes: 0_u64,
            wall_time_millis: 18_446_744_073_709_551_615_u64,
        };
        let encoded = control::CapabilityInspectionCeiling::from(value.clone()).encode_to_vec();
        let decoded = control::CapabilityInspectionCeiling::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            CapabilityInspectionCeiling::from(decoded),
            value,
            "typed-ceiling-zero-and-max-not-grant"
        );
    }
    {
        let value = AuditAck {
            status: AuditAckStatus(1),
            ..Default::default()
        };
        let encoded = control::AuditAck::from(value.clone()).encode_to_vec();
        let decoded = control::AuditAck::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            AuditAck::from(decoded),
            value,
            "audit-durable-attempt-absent"
        );
    }
    {
        let value = AuditAck {
            status: AuditAckStatus(3),
            attempt_sequence: Some(0_u64),
        };
        let encoded = control::AuditAck::from(value.clone()).encode_to_vec();
        let decoded = control::AuditAck::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            AuditAck::from(decoded),
            value,
            "audit-unavailable-attempt-zero"
        );
    }
    {
        let value = AuditAck {
            status: AuditAckStatus(4),
            ..Default::default()
        };
        let encoded = control::AuditAck::from(value.clone()).encode_to_vec();
        let decoded = control::AuditAck::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            AuditAck::from(decoded),
            value,
            "audit-disabled-distinct-from-absence"
        );
    }
    println!("shared protobuf model vectors: 49");
}
