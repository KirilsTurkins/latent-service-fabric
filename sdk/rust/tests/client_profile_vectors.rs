#![allow(clippy::too_many_lines)]

use latent_sdk::management::*;
use std::collections::BTreeMap;

#[test]
fn shared_profile_vectors() {
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
        assert!(
            value.activation_id.is_none(),
            "invoke-absent-identity-and-deadlines.activation_id.presence"
        );
        assert!(
            value.parent_activation_id.is_none(),
            "invoke-absent-identity-and-deadlines.parent_activation_id.presence"
        );
        assert!(
            value.root_activation_id.is_none(),
            "invoke-absent-identity-and-deadlines.root_activation_id.presence"
        );
        assert!(
            value.target.is_some(),
            "invoke-absent-identity-and-deadlines.target.presence"
        );
        assert_eq!(
            value.target.as_ref().unwrap().tenant,
            "tenant-a",
            "invoke-absent-identity-and-deadlines.target.tenant"
        );
        assert_eq!(
            value.target.as_ref().unwrap().service,
            "echo",
            "invoke-absent-identity-and-deadlines.target.service"
        );
        assert_eq!(
            value.target.as_ref().unwrap().contract,
            "example:echo/api@1.0.0",
            "invoke-absent-identity-and-deadlines.target.contract"
        );
        assert_eq!(
            value.target.as_ref().unwrap().function,
            "echo",
            "invoke-absent-identity-and-deadlines.target.function"
        );
        assert!(
            value.target.as_ref().unwrap().route.is_none(),
            "invoke-absent-identity-and-deadlines.target.route.presence"
        );
        assert_eq!(
            value.payload.len(),
            4,
            "invoke-absent-identity-and-deadlines.payload.length"
        );
        assert_eq!(
            value.payload[0], 0,
            "invoke-absent-identity-and-deadlines.payload.0"
        );
        assert_eq!(
            value.payload[1], 1,
            "invoke-absent-identity-and-deadlines.payload.1"
        );
        assert_eq!(
            value.payload[2], 2,
            "invoke-absent-identity-and-deadlines.payload.2"
        );
        assert_eq!(
            value.payload[3], 255,
            "invoke-absent-identity-and-deadlines.payload.3"
        );
        assert_eq!(
            value.media_type, "application/octet-stream",
            "invoke-absent-identity-and-deadlines.media_type"
        );
        assert!(
            value.deadline_unix_millis.is_none(),
            "invoke-absent-identity-and-deadlines.deadline_unix_millis.presence"
        );
        assert_eq!(
            value.priority, 0_u32,
            "invoke-absent-identity-and-deadlines.priority"
        );
        assert!(
            value.idempotency_key.is_none(),
            "invoke-absent-identity-and-deadlines.idempotency_key.presence"
        );
        assert!(
            value.budget.is_some(),
            "invoke-absent-identity-and-deadlines.budget.presence"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().cpu_fuel,
            18_446_744_073_709_551_615_u64,
            "invoke-absent-identity-and-deadlines.budget.cpu_fuel"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().memory_bytes,
            9_223_372_036_854_775_808_u64,
            "invoke-absent-identity-and-deadlines.budget.memory_bytes"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().child_calls,
            0_u32,
            "invoke-absent-identity-and-deadlines.budget.child_calls"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().outbound_requests,
            0_u32,
            "invoke-absent-identity-and-deadlines.budget.outbound_requests"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().state_read_bytes,
            0_u64,
            "invoke-absent-identity-and-deadlines.budget.state_read_bytes"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().state_write_bytes,
            0_u64,
            "invoke-absent-identity-and-deadlines.budget.state_write_bytes"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().blob_read_bytes,
            0_u64,
            "invoke-absent-identity-and-deadlines.budget.blob_read_bytes"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().blob_write_bytes,
            0_u64,
            "invoke-absent-identity-and-deadlines.budget.blob_write_bytes"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().log_bytes,
            0_u64,
            "invoke-absent-identity-and-deadlines.budget.log_bytes"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().effect_count,
            0_u32,
            "invoke-absent-identity-and-deadlines.budget.effect_count"
        );
        assert!(
            value
                .budget
                .as_ref()
                .unwrap()
                .wall_time_limit_millis
                .is_none(),
            "invoke-absent-identity-and-deadlines.budget.wall_time_limit_millis.presence"
        );
        assert_eq!(
            value.metadata.len(),
            1,
            "invoke-absent-identity-and-deadlines.metadata.count"
        );
        assert_eq!(
            value.metadata["trace"], "redacted",
            "invoke-absent-identity-and-deadlines.metadata.0"
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
        assert!(
            value.activation_id.is_some(),
            "invoke-present-invalid-and-zero-not-absence.activation_id.presence"
        );
        assert_eq!(
            value.activation_id.as_deref().unwrap(),
            "",
            "invoke-present-invalid-and-zero-not-absence.activation_id"
        );
        assert!(
            value.parent_activation_id.is_some(),
            "invoke-present-invalid-and-zero-not-absence.parent_activation_id.presence"
        );
        assert_eq!(
            value.parent_activation_id.as_deref().unwrap(),
            "parent-a",
            "invoke-present-invalid-and-zero-not-absence.parent_activation_id"
        );
        assert!(
            value.root_activation_id.is_some(),
            "invoke-present-invalid-and-zero-not-absence.root_activation_id.presence"
        );
        assert_eq!(
            value.root_activation_id.as_deref().unwrap(),
            "",
            "invoke-present-invalid-and-zero-not-absence.root_activation_id"
        );
        assert!(
            value.target.is_some(),
            "invoke-present-invalid-and-zero-not-absence.target.presence"
        );
        assert_eq!(
            value.target.as_ref().unwrap().tenant,
            "",
            "invoke-present-invalid-and-zero-not-absence.target.tenant"
        );
        assert_eq!(
            value.target.as_ref().unwrap().service,
            "",
            "invoke-present-invalid-and-zero-not-absence.target.service"
        );
        assert_eq!(
            value.target.as_ref().unwrap().contract,
            "",
            "invoke-present-invalid-and-zero-not-absence.target.contract"
        );
        assert_eq!(
            value.target.as_ref().unwrap().function,
            "",
            "invoke-present-invalid-and-zero-not-absence.target.function"
        );
        assert!(
            value.target.as_ref().unwrap().route.is_some(),
            "invoke-present-invalid-and-zero-not-absence.target.route.presence"
        );
        assert_eq!(
            value.target.as_ref().unwrap().route.as_deref().unwrap(),
            "",
            "invoke-present-invalid-and-zero-not-absence.target.route"
        );
        assert_eq!(
            value.payload.len(),
            0,
            "invoke-present-invalid-and-zero-not-absence.payload.length"
        );
        assert_eq!(
            value.media_type, "",
            "invoke-present-invalid-and-zero-not-absence.media_type"
        );
        assert!(
            value.deadline_unix_millis.is_some(),
            "invoke-present-invalid-and-zero-not-absence.deadline_unix_millis.presence"
        );
        assert_eq!(
            value.deadline_unix_millis.unwrap(),
            0_u64,
            "invoke-present-invalid-and-zero-not-absence.deadline_unix_millis"
        );
        assert_eq!(
            value.priority, 0_u32,
            "invoke-present-invalid-and-zero-not-absence.priority"
        );
        assert!(
            value.idempotency_key.is_some(),
            "invoke-present-invalid-and-zero-not-absence.idempotency_key.presence"
        );
        assert_eq!(
            value.idempotency_key.as_deref().unwrap(),
            "",
            "invoke-present-invalid-and-zero-not-absence.idempotency_key"
        );
        assert!(
            value.budget.is_some(),
            "invoke-present-invalid-and-zero-not-absence.budget.presence"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().cpu_fuel,
            0_u64,
            "invoke-present-invalid-and-zero-not-absence.budget.cpu_fuel"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().memory_bytes,
            0_u64,
            "invoke-present-invalid-and-zero-not-absence.budget.memory_bytes"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().child_calls,
            0_u32,
            "invoke-present-invalid-and-zero-not-absence.budget.child_calls"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().outbound_requests,
            0_u32,
            "invoke-present-invalid-and-zero-not-absence.budget.outbound_requests"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().state_read_bytes,
            0_u64,
            "invoke-present-invalid-and-zero-not-absence.budget.state_read_bytes"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().state_write_bytes,
            0_u64,
            "invoke-present-invalid-and-zero-not-absence.budget.state_write_bytes"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().blob_read_bytes,
            0_u64,
            "invoke-present-invalid-and-zero-not-absence.budget.blob_read_bytes"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().blob_write_bytes,
            0_u64,
            "invoke-present-invalid-and-zero-not-absence.budget.blob_write_bytes"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().log_bytes,
            0_u64,
            "invoke-present-invalid-and-zero-not-absence.budget.log_bytes"
        );
        assert_eq!(
            value.budget.as_ref().unwrap().effect_count,
            0_u32,
            "invoke-present-invalid-and-zero-not-absence.budget.effect_count"
        );
        assert!(
            value
                .budget
                .as_ref()
                .unwrap()
                .wall_time_limit_millis
                .is_some(),
            "invoke-present-invalid-and-zero-not-absence.budget.wall_time_limit_millis.presence"
        );
        assert_eq!(
            value
                .budget
                .as_ref()
                .unwrap()
                .wall_time_limit_millis
                .unwrap(),
            0_u64,
            "invoke-present-invalid-and-zero-not-absence.budget.wall_time_limit_millis"
        );
        assert_eq!(
            value.metadata.len(),
            0,
            "invoke-present-invalid-and-zero-not-absence.metadata.count"
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
        assert!(
            value.activation_id.is_some(),
            "invoke-known-identity-full-width-deadline-and-priority.activation_id.presence"
        );
        assert_eq!(
            value.activation_id.as_deref().unwrap(),
            "activation-a",
            "invoke-known-identity-full-width-deadline-and-priority.activation_id"
        );
        assert!(
            value.parent_activation_id.is_some(),
            "invoke-known-identity-full-width-deadline-and-priority.parent_activation_id.presence"
        );
        assert_eq!(
            value.parent_activation_id.as_deref().unwrap(),
            "parent-a",
            "invoke-known-identity-full-width-deadline-and-priority.parent_activation_id"
        );
        assert!(
            value.root_activation_id.is_some(),
            "invoke-known-identity-full-width-deadline-and-priority.root_activation_id.presence"
        );
        assert_eq!(
            value.root_activation_id.as_deref().unwrap(),
            "root-a",
            "invoke-known-identity-full-width-deadline-and-priority.root_activation_id"
        );
        assert!(
            value.target.is_none(),
            "invoke-known-identity-full-width-deadline-and-priority.target.presence"
        );
        assert_eq!(
            value.payload.len(),
            0,
            "invoke-known-identity-full-width-deadline-and-priority.payload.length"
        );
        assert_eq!(
            value.media_type, "",
            "invoke-known-identity-full-width-deadline-and-priority.media_type"
        );
        assert!(
            value.deadline_unix_millis.is_some(),
            "invoke-known-identity-full-width-deadline-and-priority.deadline_unix_millis.presence"
        );
        assert_eq!(
            value.deadline_unix_millis.unwrap(),
            18_446_744_073_709_551_615_u64,
            "invoke-known-identity-full-width-deadline-and-priority.deadline_unix_millis"
        );
        assert_eq!(
            value.priority, 4_294_967_295_u32,
            "invoke-known-identity-full-width-deadline-and-priority.priority"
        );
        assert!(
            value.idempotency_key.is_some(),
            "invoke-known-identity-full-width-deadline-and-priority.idempotency_key.presence"
        );
        assert_eq!(
            value.idempotency_key.as_deref().unwrap(),
            "not-an-authority-or-retry-key",
            "invoke-known-identity-full-width-deadline-and-priority.idempotency_key"
        );
        assert!(
            value.budget.is_none(),
            "invoke-known-identity-full-width-deadline-and-priority.budget.presence"
        );
        assert_eq!(
            value.metadata.len(),
            0,
            "invoke-known-identity-full-width-deadline-and-priority.metadata.count"
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
        assert_eq!(
            value.cpu_fuel, 18_446_744_073_709_551_615_u64,
            "full-resource-budget.cpu_fuel"
        );
        assert_eq!(
            value.memory_bytes, 18_446_744_073_709_551_615_u64,
            "full-resource-budget.memory_bytes"
        );
        assert_eq!(
            value.child_calls, 4_294_967_295_u32,
            "full-resource-budget.child_calls"
        );
        assert_eq!(
            value.outbound_requests, 4_294_967_295_u32,
            "full-resource-budget.outbound_requests"
        );
        assert_eq!(
            value.state_read_bytes, 18_446_744_073_709_551_615_u64,
            "full-resource-budget.state_read_bytes"
        );
        assert_eq!(
            value.state_write_bytes, 18_446_744_073_709_551_615_u64,
            "full-resource-budget.state_write_bytes"
        );
        assert_eq!(
            value.blob_read_bytes, 18_446_744_073_709_551_615_u64,
            "full-resource-budget.blob_read_bytes"
        );
        assert_eq!(
            value.blob_write_bytes, 18_446_744_073_709_551_615_u64,
            "full-resource-budget.blob_write_bytes"
        );
        assert_eq!(
            value.log_bytes, 18_446_744_073_709_551_615_u64,
            "full-resource-budget.log_bytes"
        );
        assert_eq!(
            value.effect_count, 4_294_967_295_u32,
            "full-resource-budget.effect_count"
        );
        assert!(
            value.wall_time_limit_millis.is_some(),
            "full-resource-budget.wall_time_limit_millis.presence"
        );
        assert_eq!(
            value.wall_time_limit_millis.unwrap(),
            18_446_744_073_709_551_615_u64,
            "full-resource-budget.wall_time_limit_millis"
        );
    }
    {
        let value = InvokeResponse{activation_id: "activation-a".into(), revision_id: "revision-a".into(), release_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(), route_generation: 18_446_744_073_709_551_615_u64, success: Some(Success{payload: vec![0, 1, 2, 255], media_type: "application/octet-stream".into(), committed_state_version: Some(String::new()), effect_ids: vec!["effect-a".into(), "effect-b".into()], metadata: BTreeMap::from([("result".into(), "redacted".into())])}), consumption: Some(BudgetConsumption{cpu_fuel: 18_446_744_073_709_551_615_u64, peak_memory_bytes: 0_u64, wall_time_micros: 9_007_199_254_740_993_u64, child_calls: 0_u32, outbound_requests: 0_u32, state_read_bytes: 0_u64, state_write_bytes: 0_u64, blob_read_bytes: 0_u64, blob_write_bytes: 0_u64, log_bytes: 0_u64, effect_count: 0_u32}), publication_id: Some("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111".into()), ..Default::default()};
        assert_eq!(
            value.activation_id, "activation-a",
            "invoke-success-retains-publication-and-component.activation_id"
        );
        assert_eq!(
            value.revision_id, "revision-a",
            "invoke-success-retains-publication-and-component.revision_id"
        );
        assert_eq!(
            value.release_digest,
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "invoke-success-retains-publication-and-component.release_digest"
        );
        assert_eq!(
            value.route_generation, 18_446_744_073_709_551_615_u64,
            "invoke-success-retains-publication-and-component.route_generation"
        );
        assert!(
            value.success.is_some(),
            "invoke-success-retains-publication-and-component.success.presence"
        );
        assert_eq!(
            value.success.as_ref().unwrap().payload.len(),
            4,
            "invoke-success-retains-publication-and-component.success.payload.length"
        );
        assert_eq!(
            value.success.as_ref().unwrap().payload[0],
            0,
            "invoke-success-retains-publication-and-component.success.payload.0"
        );
        assert_eq!(
            value.success.as_ref().unwrap().payload[1],
            1,
            "invoke-success-retains-publication-and-component.success.payload.1"
        );
        assert_eq!(
            value.success.as_ref().unwrap().payload[2],
            2,
            "invoke-success-retains-publication-and-component.success.payload.2"
        );
        assert_eq!(
            value.success.as_ref().unwrap().payload[3],
            255,
            "invoke-success-retains-publication-and-component.success.payload.3"
        );
        assert_eq!(
            value.success.as_ref().unwrap().media_type,
            "application/octet-stream",
            "invoke-success-retains-publication-and-component.success.media_type"
        );
        assert!(value.success.as_ref().unwrap().committed_state_version.is_some(), "invoke-success-retains-publication-and-component.success.committed_state_version.presence");
        assert_eq!(
            value
                .success
                .as_ref()
                .unwrap()
                .committed_state_version
                .as_deref()
                .unwrap(),
            "",
            "invoke-success-retains-publication-and-component.success.committed_state_version"
        );
        assert_eq!(
            value.success.as_ref().unwrap().effect_ids.len(),
            2,
            "invoke-success-retains-publication-and-component.success.effect_ids.count"
        );
        assert_eq!(
            value.success.as_ref().unwrap().effect_ids[0],
            "effect-a",
            "invoke-success-retains-publication-and-component.success.effect_ids.0"
        );
        assert_eq!(
            value.success.as_ref().unwrap().effect_ids[1],
            "effect-b",
            "invoke-success-retains-publication-and-component.success.effect_ids.1"
        );
        assert_eq!(
            value.success.as_ref().unwrap().metadata.len(),
            1,
            "invoke-success-retains-publication-and-component.success.metadata.count"
        );
        assert_eq!(
            value.success.as_ref().unwrap().metadata["result"],
            "redacted",
            "invoke-success-retains-publication-and-component.success.metadata.0"
        );
        assert!(
            value.declared_error.is_none(),
            "invoke-success-retains-publication-and-component.declared_error.presence"
        );
        assert!(
            value.platform_failure.is_none(),
            "invoke-success-retains-publication-and-component.platform_failure.presence"
        );
        assert!(
            value.consumption.is_some(),
            "invoke-success-retains-publication-and-component.consumption.presence"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().cpu_fuel,
            18_446_744_073_709_551_615_u64,
            "invoke-success-retains-publication-and-component.consumption.cpu_fuel"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().peak_memory_bytes,
            0_u64,
            "invoke-success-retains-publication-and-component.consumption.peak_memory_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().wall_time_micros,
            9_007_199_254_740_993_u64,
            "invoke-success-retains-publication-and-component.consumption.wall_time_micros"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().child_calls,
            0_u32,
            "invoke-success-retains-publication-and-component.consumption.child_calls"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().outbound_requests,
            0_u32,
            "invoke-success-retains-publication-and-component.consumption.outbound_requests"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().state_read_bytes,
            0_u64,
            "invoke-success-retains-publication-and-component.consumption.state_read_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().state_write_bytes,
            0_u64,
            "invoke-success-retains-publication-and-component.consumption.state_write_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().blob_read_bytes,
            0_u64,
            "invoke-success-retains-publication-and-component.consumption.blob_read_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().blob_write_bytes,
            0_u64,
            "invoke-success-retains-publication-and-component.consumption.blob_write_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().log_bytes,
            0_u64,
            "invoke-success-retains-publication-and-component.consumption.log_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().effect_count,
            0_u32,
            "invoke-success-retains-publication-and-component.consumption.effect_count"
        );
        assert!(
            value.publication_id.is_some(),
            "invoke-success-retains-publication-and-component.publication_id.presence"
        );
        assert_eq!(
            value.publication_id.as_deref().unwrap(),
            "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111",
            "invoke-success-retains-publication-and-component.publication_id"
        );
    }
    {
        let value = InvokeResponse{activation_id: "activation-a".into(), revision_id: "revision-a".into(), release_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(), route_generation: 9_223_372_036_854_775_808_u64, declared_error: Some(DeclaredError{code: "uncertain".into(), message: "provider outcome unknown".into(), payload: vec![0, 1, 2, 255], media_type: "application/octet-stream".into(), metadata: BTreeMap::from([("contract".into(), "latent:http/streaming@0.3.0".into())])}), consumption: Some(BudgetConsumption{cpu_fuel: 0_u64, peak_memory_bytes: 0_u64, wall_time_micros: 0_u64, child_calls: 0_u32, outbound_requests: 0_u32, state_read_bytes: 0_u64, state_write_bytes: 0_u64, blob_read_bytes: 0_u64, blob_write_bytes: 18_446_744_073_709_551_615_u64, log_bytes: 0_u64, effect_count: 0_u32}), publication_id: Some("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111".into()), ..Default::default()};
        assert_eq!(
            value.activation_id, "activation-a",
            "typed-declared-provider-uncertainty-retains-receipt.activation_id"
        );
        assert_eq!(
            value.revision_id, "revision-a",
            "typed-declared-provider-uncertainty-retains-receipt.revision_id"
        );
        assert_eq!(
            value.release_digest,
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "typed-declared-provider-uncertainty-retains-receipt.release_digest"
        );
        assert_eq!(
            value.route_generation, 9_223_372_036_854_775_808_u64,
            "typed-declared-provider-uncertainty-retains-receipt.route_generation"
        );
        assert!(
            value.success.is_none(),
            "typed-declared-provider-uncertainty-retains-receipt.success.presence"
        );
        assert!(
            value.declared_error.is_some(),
            "typed-declared-provider-uncertainty-retains-receipt.declared_error.presence"
        );
        assert_eq!(
            value.declared_error.as_ref().unwrap().code,
            "uncertain",
            "typed-declared-provider-uncertainty-retains-receipt.declared_error.code"
        );
        assert_eq!(
            value.declared_error.as_ref().unwrap().message,
            "provider outcome unknown",
            "typed-declared-provider-uncertainty-retains-receipt.declared_error.message"
        );
        assert_eq!(
            value.declared_error.as_ref().unwrap().payload.len(),
            4,
            "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.length"
        );
        assert_eq!(
            value.declared_error.as_ref().unwrap().payload[0],
            0,
            "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.0"
        );
        assert_eq!(
            value.declared_error.as_ref().unwrap().payload[1],
            1,
            "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.1"
        );
        assert_eq!(
            value.declared_error.as_ref().unwrap().payload[2],
            2,
            "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.2"
        );
        assert_eq!(
            value.declared_error.as_ref().unwrap().payload[3],
            255,
            "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.3"
        );
        assert_eq!(
            value.declared_error.as_ref().unwrap().media_type,
            "application/octet-stream",
            "typed-declared-provider-uncertainty-retains-receipt.declared_error.media_type"
        );
        assert_eq!(
            value.declared_error.as_ref().unwrap().metadata.len(),
            1,
            "typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.count"
        );
        assert_eq!(
            value.declared_error.as_ref().unwrap().metadata["contract"],
            "latent:http/streaming@0.3.0",
            "typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.0"
        );
        assert!(
            value.platform_failure.is_none(),
            "typed-declared-provider-uncertainty-retains-receipt.platform_failure.presence"
        );
        assert!(
            value.consumption.is_some(),
            "typed-declared-provider-uncertainty-retains-receipt.consumption.presence"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().cpu_fuel,
            0_u64,
            "typed-declared-provider-uncertainty-retains-receipt.consumption.cpu_fuel"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().peak_memory_bytes,
            0_u64,
            "typed-declared-provider-uncertainty-retains-receipt.consumption.peak_memory_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().wall_time_micros,
            0_u64,
            "typed-declared-provider-uncertainty-retains-receipt.consumption.wall_time_micros"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().child_calls,
            0_u32,
            "typed-declared-provider-uncertainty-retains-receipt.consumption.child_calls"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().outbound_requests,
            0_u32,
            "typed-declared-provider-uncertainty-retains-receipt.consumption.outbound_requests"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().state_read_bytes,
            0_u64,
            "typed-declared-provider-uncertainty-retains-receipt.consumption.state_read_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().state_write_bytes,
            0_u64,
            "typed-declared-provider-uncertainty-retains-receipt.consumption.state_write_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().blob_read_bytes,
            0_u64,
            "typed-declared-provider-uncertainty-retains-receipt.consumption.blob_read_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().blob_write_bytes,
            18_446_744_073_709_551_615_u64,
            "typed-declared-provider-uncertainty-retains-receipt.consumption.blob_write_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().log_bytes,
            0_u64,
            "typed-declared-provider-uncertainty-retains-receipt.consumption.log_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().effect_count,
            0_u32,
            "typed-declared-provider-uncertainty-retains-receipt.consumption.effect_count"
        );
        assert!(
            value.publication_id.is_some(),
            "typed-declared-provider-uncertainty-retains-receipt.publication_id.presence"
        );
        assert_eq!(
            value.publication_id.as_deref().unwrap(),
            "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111",
            "typed-declared-provider-uncertainty-retains-receipt.publication_id"
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
        assert_eq!(
            value.activation_id, "activation-a",
            "typed-platform-capability-failure-retains-detail-items.activation_id"
        );
        assert_eq!(
            value.revision_id, "",
            "typed-platform-capability-failure-retains-detail-items.revision_id"
        );
        assert_eq!(
            value.release_digest, "",
            "typed-platform-capability-failure-retains-detail-items.release_digest"
        );
        assert_eq!(
            value.route_generation, 0_u64,
            "typed-platform-capability-failure-retains-detail-items.route_generation"
        );
        assert!(
            value.success.is_none(),
            "typed-platform-capability-failure-retains-detail-items.success.presence"
        );
        assert!(
            value.declared_error.is_none(),
            "typed-platform-capability-failure-retains-detail-items.declared_error.presence"
        );
        assert!(
            value.platform_failure.is_some(),
            "typed-platform-capability-failure-retains-detail-items.platform_failure.presence"
        );
        assert_eq!(
            value.platform_failure.as_ref().unwrap().code,
            "permission-denied",
            "typed-platform-capability-failure-retains-detail-items.platform_failure.code"
        );
        assert_eq!(
            value.platform_failure.as_ref().unwrap().message,
            "capability-provider-failed",
            "typed-platform-capability-failure-retains-detail-items.platform_failure.message"
        );
        assert!(
            !value.platform_failure.as_ref().unwrap().retryable,
            "typed-platform-capability-failure-retains-detail-items.platform_failure.retryable"
        );
        assert_eq!(value.platform_failure.as_ref().unwrap().detail_items.len(), 2, "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.count");
        assert_eq!(value.platform_failure.as_ref().unwrap().detail_items[0].kind, "capability-observation", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.kind");
        assert_eq!(value.platform_failure.as_ref().unwrap().detail_items[0].fields.len(), 2, "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.count");
        assert_eq!(value.platform_failure.as_ref().unwrap().detail_items[0].fields["capability"], "latent:http/streaming@0.3.0", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.0");
        assert_eq!(value.platform_failure.as_ref().unwrap().detail_items[0].fields["state"], "policy-revoked", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.1");
        assert_eq!(value.platform_failure.as_ref().unwrap().detail_items[1].kind, "future-detail", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.kind");
        assert_eq!(value.platform_failure.as_ref().unwrap().detail_items[1].fields.len(), 1, "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.count");
        assert_eq!(value.platform_failure.as_ref().unwrap().detail_items[1].fields["bounded"], "preserved", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.0");
        assert!(
            value.consumption.is_some(),
            "typed-platform-capability-failure-retains-detail-items.consumption.presence"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().cpu_fuel,
            0_u64,
            "typed-platform-capability-failure-retains-detail-items.consumption.cpu_fuel"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().peak_memory_bytes,
            0_u64,
            "typed-platform-capability-failure-retains-detail-items.consumption.peak_memory_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().wall_time_micros,
            0_u64,
            "typed-platform-capability-failure-retains-detail-items.consumption.wall_time_micros"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().child_calls,
            0_u32,
            "typed-platform-capability-failure-retains-detail-items.consumption.child_calls"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().outbound_requests,
            0_u32,
            "typed-platform-capability-failure-retains-detail-items.consumption.outbound_requests"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().state_read_bytes,
            0_u64,
            "typed-platform-capability-failure-retains-detail-items.consumption.state_read_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().state_write_bytes,
            0_u64,
            "typed-platform-capability-failure-retains-detail-items.consumption.state_write_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().blob_read_bytes,
            0_u64,
            "typed-platform-capability-failure-retains-detail-items.consumption.blob_read_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().blob_write_bytes,
            0_u64,
            "typed-platform-capability-failure-retains-detail-items.consumption.blob_write_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().log_bytes,
            18_446_744_073_709_551_615_u64,
            "typed-platform-capability-failure-retains-detail-items.consumption.log_bytes"
        );
        assert_eq!(
            value.consumption.as_ref().unwrap().effect_count,
            0_u32,
            "typed-platform-capability-failure-retains-detail-items.consumption.effect_count"
        );
        assert!(
            value.publication_id.is_none(),
            "typed-platform-capability-failure-retains-detail-items.publication_id.presence"
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
        assert_eq!(
            value.activation_id, "activation-a",
            "present-invalid-publication-not-legacy.activation_id"
        );
        assert_eq!(
            value.revision_id, "",
            "present-invalid-publication-not-legacy.revision_id"
        );
        assert_eq!(
            value.release_digest, "",
            "present-invalid-publication-not-legacy.release_digest"
        );
        assert_eq!(
            value.route_generation, 0_u64,
            "present-invalid-publication-not-legacy.route_generation"
        );
        assert!(
            value.success.is_some(),
            "present-invalid-publication-not-legacy.success.presence"
        );
        assert_eq!(
            value.success.as_ref().unwrap().payload.len(),
            0,
            "present-invalid-publication-not-legacy.success.payload.length"
        );
        assert_eq!(
            value.success.as_ref().unwrap().media_type,
            "",
            "present-invalid-publication-not-legacy.success.media_type"
        );
        assert!(
            value
                .success
                .as_ref()
                .unwrap()
                .committed_state_version
                .is_none(),
            "present-invalid-publication-not-legacy.success.committed_state_version.presence"
        );
        assert_eq!(
            value.success.as_ref().unwrap().effect_ids.len(),
            0,
            "present-invalid-publication-not-legacy.success.effect_ids.count"
        );
        assert_eq!(
            value.success.as_ref().unwrap().metadata.len(),
            0,
            "present-invalid-publication-not-legacy.success.metadata.count"
        );
        assert!(
            value.declared_error.is_none(),
            "present-invalid-publication-not-legacy.declared_error.presence"
        );
        assert!(
            value.platform_failure.is_none(),
            "present-invalid-publication-not-legacy.platform_failure.presence"
        );
        assert!(
            value.consumption.is_none(),
            "present-invalid-publication-not-legacy.consumption.presence"
        );
        assert!(
            value.publication_id.is_some(),
            "present-invalid-publication-not-legacy.publication_id.presence"
        );
        assert_eq!(
            value.publication_id.as_deref().unwrap(),
            "",
            "present-invalid-publication-not-legacy.publication_id"
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
        assert_eq!(
            value.activation_id, "activation-a",
            "contradictory-outcome-retained-for-rejection.activation_id"
        );
        assert_eq!(
            value.revision_id, "",
            "contradictory-outcome-retained-for-rejection.revision_id"
        );
        assert_eq!(
            value.release_digest, "",
            "contradictory-outcome-retained-for-rejection.release_digest"
        );
        assert_eq!(
            value.route_generation, 0_u64,
            "contradictory-outcome-retained-for-rejection.route_generation"
        );
        assert!(
            value.success.is_some(),
            "contradictory-outcome-retained-for-rejection.success.presence"
        );
        assert_eq!(
            value.success.as_ref().unwrap().payload.len(),
            0,
            "contradictory-outcome-retained-for-rejection.success.payload.length"
        );
        assert_eq!(
            value.success.as_ref().unwrap().media_type,
            "",
            "contradictory-outcome-retained-for-rejection.success.media_type"
        );
        assert!(
            value
                .success
                .as_ref()
                .unwrap()
                .committed_state_version
                .is_none(),
            "contradictory-outcome-retained-for-rejection.success.committed_state_version.presence"
        );
        assert_eq!(
            value.success.as_ref().unwrap().effect_ids.len(),
            0,
            "contradictory-outcome-retained-for-rejection.success.effect_ids.count"
        );
        assert_eq!(
            value.success.as_ref().unwrap().metadata.len(),
            0,
            "contradictory-outcome-retained-for-rejection.success.metadata.count"
        );
        assert!(
            value.declared_error.is_none(),
            "contradictory-outcome-retained-for-rejection.declared_error.presence"
        );
        assert!(
            value.platform_failure.is_some(),
            "contradictory-outcome-retained-for-rejection.platform_failure.presence"
        );
        assert_eq!(
            value.platform_failure.as_ref().unwrap().code,
            "internal",
            "contradictory-outcome-retained-for-rejection.platform_failure.code"
        );
        assert_eq!(
            value.platform_failure.as_ref().unwrap().message,
            "",
            "contradictory-outcome-retained-for-rejection.platform_failure.message"
        );
        assert!(
            !value.platform_failure.as_ref().unwrap().retryable,
            "contradictory-outcome-retained-for-rejection.platform_failure.retryable"
        );
        assert_eq!(
            value.platform_failure.as_ref().unwrap().detail_items.len(),
            0,
            "contradictory-outcome-retained-for-rejection.platform_failure.detail_items.count"
        );
        assert!(
            value.consumption.is_none(),
            "contradictory-outcome-retained-for-rejection.consumption.presence"
        );
        assert!(
            value.publication_id.is_none(),
            "contradictory-outcome-retained-for-rejection.publication_id.presence"
        );
    }
    {
        let value = CancelRequest {
            activation_id: "activation-a".into(),
            reason: "caller-requested".into(),
        };
        assert_eq!(
            value.activation_id, "activation-a",
            "cancel-request-known-id.activation_id"
        );
        assert_eq!(
            value.reason, "caller-requested",
            "cancel-request-known-id.reason"
        );
    }
    {
        let value = CancelResponse {
            disposition: CancelDisposition(1),
            ..Default::default()
        };
        assert_eq!(
            value.disposition.0, 1,
            "cancel-accepted-not-cleanup.disposition"
        );
        assert!(
            value.terminal_state.is_none(),
            "cancel-accepted-not-cleanup.terminal_state.presence"
        );
    }
    {
        let value = CancelResponse {
            disposition: CancelDisposition(2),
            terminal_state: Some("completed".into()),
        };
        assert_eq!(
            value.disposition.0, 2,
            "cancel-already-terminal.disposition"
        );
        assert!(
            value.terminal_state.is_some(),
            "cancel-already-terminal.terminal_state.presence"
        );
        assert_eq!(
            value.terminal_state.as_deref().unwrap(),
            "completed",
            "cancel-already-terminal.terminal_state"
        );
    }
    {
        let value = CancelResponse {
            disposition: CancelDisposition(3),
            ..Default::default()
        };
        assert_eq!(
            value.disposition.0, 3,
            "cancel-not-found-not-nonexecution.disposition"
        );
        assert!(
            value.terminal_state.is_none(),
            "cancel-not-found-not-nonexecution.terminal_state.presence"
        );
    }
    {
        let value = CancelResponse {
            disposition: CancelDisposition(0),
            terminal_state: Some(String::new()),
        };
        assert_eq!(
            value.disposition.0, 0,
            "cancel-unspecified-not-accepted.disposition"
        );
        assert!(
            value.terminal_state.is_some(),
            "cancel-unspecified-not-accepted.terminal_state.presence"
        );
        assert_eq!(
            value.terminal_state.as_deref().unwrap(),
            "",
            "cancel-unspecified-not-accepted.terminal_state"
        );
    }
    {
        let value = CancelResponse {
            disposition: CancelDisposition(91),
            terminal_state: Some("future-terminal-state".into()),
        };
        assert_eq!(value.disposition.0, 91, "cancel-unknown-enum.disposition");
        assert!(
            value.terminal_state.is_some(),
            "cancel-unknown-enum.terminal_state.presence"
        );
        assert_eq!(
            value.terminal_state.as_deref().unwrap(),
            "future-terminal-state",
            "cancel-unknown-enum.terminal_state"
        );
    }
    {
        let value = CancelResponse {
            disposition: CancelDisposition(-2_147_483_648),
            ..Default::default()
        };
        assert_eq!(
            value.disposition.0, -2_147_483_648,
            "cancel-negative-enum.disposition"
        );
        assert!(
            value.terminal_state.is_none(),
            "cancel-negative-enum.terminal_state.presence"
        );
    }
    {
        let value = GetActivationRequest {
            activation_id: "activation-a".into(),
        };
        assert_eq!(
            value.activation_id, "activation-a",
            "get-activation-recovery.activation_id"
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
        assert_eq!(
            value.activation_id, "activation-a",
            "activation-running-absent-terminal.activation_id"
        );
        assert_eq!(
            value.phase, "running",
            "activation-running-absent-terminal.phase"
        );
        assert!(
            value.terminal_state.is_none(),
            "activation-running-absent-terminal.terminal_state.presence"
        );
        assert_eq!(
            value.last_updated_unix_millis, 18_446_744_073_709_551_615_u64,
            "activation-running-absent-terminal.last_updated_unix_millis"
        );
        assert_eq!(
            value.metadata.len(),
            0,
            "activation-running-absent-terminal.metadata.count"
        );
        assert!(
            value.succeeded.is_none(),
            "activation-running-absent-terminal.succeeded.presence"
        );
        assert!(
            value.declared_error.is_none(),
            "activation-running-absent-terminal.declared_error.presence"
        );
        assert!(
            value.platform_failure.is_none(),
            "activation-running-absent-terminal.platform_failure.presence"
        );
        assert!(
            value.final_consumption.is_none(),
            "activation-running-absent-terminal.final_consumption.presence"
        );
        assert!(
            value.terminal_at_unix_millis.is_none(),
            "activation-running-absent-terminal.terminal_at_unix_millis.presence"
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
        assert_eq!(
            value.activation_id, "activation-a",
            "activation-terminal-typed-failure.activation_id"
        );
        assert_eq!(
            value.phase, "terminal",
            "activation-terminal-typed-failure.phase"
        );
        assert!(
            value.terminal_state.is_some(),
            "activation-terminal-typed-failure.terminal_state.presence"
        );
        assert_eq!(
            value.terminal_state.as_deref().unwrap(),
            "failed",
            "activation-terminal-typed-failure.terminal_state"
        );
        assert_eq!(
            value.last_updated_unix_millis, 0_u64,
            "activation-terminal-typed-failure.last_updated_unix_millis"
        );
        assert_eq!(
            value.metadata.len(),
            0,
            "activation-terminal-typed-failure.metadata.count"
        );
        assert!(
            value.succeeded.is_none(),
            "activation-terminal-typed-failure.succeeded.presence"
        );
        assert!(
            value.declared_error.is_none(),
            "activation-terminal-typed-failure.declared_error.presence"
        );
        assert!(
            value.platform_failure.is_some(),
            "activation-terminal-typed-failure.platform_failure.presence"
        );
        assert_eq!(
            value.platform_failure.as_ref().unwrap().code,
            "resource-exhausted",
            "activation-terminal-typed-failure.platform_failure.code"
        );
        assert_eq!(
            value.platform_failure.as_ref().unwrap().message,
            "capability-capacity",
            "activation-terminal-typed-failure.platform_failure.message"
        );
        assert!(
            !value.platform_failure.as_ref().unwrap().retryable,
            "activation-terminal-typed-failure.platform_failure.retryable"
        );
        assert_eq!(
            value.platform_failure.as_ref().unwrap().detail_items.len(),
            1,
            "activation-terminal-typed-failure.platform_failure.detail_items.count"
        );
        assert_eq!(
            value.platform_failure.as_ref().unwrap().detail_items[0].kind,
            "budget",
            "activation-terminal-typed-failure.platform_failure.detail_items.0.kind"
        );
        assert_eq!(
            value.platform_failure.as_ref().unwrap().detail_items[0]
                .fields
                .len(),
            1,
            "activation-terminal-typed-failure.platform_failure.detail_items.0.fields.count"
        );
        assert_eq!(
            value.platform_failure.as_ref().unwrap().detail_items[0].fields["resource"],
            "buffer-bytes",
            "activation-terminal-typed-failure.platform_failure.detail_items.0.fields.0"
        );
        assert!(
            value.final_consumption.is_some(),
            "activation-terminal-typed-failure.final_consumption.presence"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().cpu_fuel,
            0_u64,
            "activation-terminal-typed-failure.final_consumption.cpu_fuel"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().peak_memory_bytes,
            18_446_744_073_709_551_615_u64,
            "activation-terminal-typed-failure.final_consumption.peak_memory_bytes"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().wall_time_micros,
            0_u64,
            "activation-terminal-typed-failure.final_consumption.wall_time_micros"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().child_calls,
            0_u32,
            "activation-terminal-typed-failure.final_consumption.child_calls"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().outbound_requests,
            0_u32,
            "activation-terminal-typed-failure.final_consumption.outbound_requests"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().state_read_bytes,
            0_u64,
            "activation-terminal-typed-failure.final_consumption.state_read_bytes"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().state_write_bytes,
            0_u64,
            "activation-terminal-typed-failure.final_consumption.state_write_bytes"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().blob_read_bytes,
            0_u64,
            "activation-terminal-typed-failure.final_consumption.blob_read_bytes"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().blob_write_bytes,
            0_u64,
            "activation-terminal-typed-failure.final_consumption.blob_write_bytes"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().log_bytes,
            0_u64,
            "activation-terminal-typed-failure.final_consumption.log_bytes"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().effect_count,
            0_u32,
            "activation-terminal-typed-failure.final_consumption.effect_count"
        );
        assert!(
            value.terminal_at_unix_millis.is_some(),
            "activation-terminal-typed-failure.terminal_at_unix_millis.presence"
        );
        assert_eq!(
            value.terminal_at_unix_millis.unwrap(),
            0_u64,
            "activation-terminal-typed-failure.terminal_at_unix_millis"
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
        assert_eq!(
            value.activation_id, "activation-a",
            "activation-terminal-success-summary.activation_id"
        );
        assert_eq!(
            value.phase, "terminal",
            "activation-terminal-success-summary.phase"
        );
        assert!(
            value.terminal_state.is_some(),
            "activation-terminal-success-summary.terminal_state.presence"
        );
        assert_eq!(
            value.terminal_state.as_deref().unwrap(),
            "completed",
            "activation-terminal-success-summary.terminal_state"
        );
        assert_eq!(
            value.last_updated_unix_millis, 0_u64,
            "activation-terminal-success-summary.last_updated_unix_millis"
        );
        assert_eq!(
            value.metadata.len(),
            0,
            "activation-terminal-success-summary.metadata.count"
        );
        assert!(
            value.succeeded.is_some(),
            "activation-terminal-success-summary.succeeded.presence"
        );
        assert!(
            value
                .succeeded
                .as_ref()
                .unwrap()
                .committed_state_version
                .is_some(),
            "activation-terminal-success-summary.succeeded.committed_state_version.presence"
        );
        assert_eq!(
            value
                .succeeded
                .as_ref()
                .unwrap()
                .committed_state_version
                .as_deref()
                .unwrap(),
            "state-a",
            "activation-terminal-success-summary.succeeded.committed_state_version"
        );
        assert_eq!(
            value.succeeded.as_ref().unwrap().effect_ids.len(),
            1,
            "activation-terminal-success-summary.succeeded.effect_ids.count"
        );
        assert_eq!(
            value.succeeded.as_ref().unwrap().effect_ids[0],
            "effect-a",
            "activation-terminal-success-summary.succeeded.effect_ids.0"
        );
        assert_eq!(
            value.succeeded.as_ref().unwrap().metadata.len(),
            1,
            "activation-terminal-success-summary.succeeded.metadata.count"
        );
        assert_eq!(
            value.succeeded.as_ref().unwrap().metadata["retained"],
            "true",
            "activation-terminal-success-summary.succeeded.metadata.0"
        );
        assert!(
            value.declared_error.is_none(),
            "activation-terminal-success-summary.declared_error.presence"
        );
        assert!(
            value.platform_failure.is_none(),
            "activation-terminal-success-summary.platform_failure.presence"
        );
        assert!(
            value.final_consumption.is_some(),
            "activation-terminal-success-summary.final_consumption.presence"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().cpu_fuel,
            0_u64,
            "activation-terminal-success-summary.final_consumption.cpu_fuel"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().peak_memory_bytes,
            0_u64,
            "activation-terminal-success-summary.final_consumption.peak_memory_bytes"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().wall_time_micros,
            0_u64,
            "activation-terminal-success-summary.final_consumption.wall_time_micros"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().child_calls,
            0_u32,
            "activation-terminal-success-summary.final_consumption.child_calls"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().outbound_requests,
            0_u32,
            "activation-terminal-success-summary.final_consumption.outbound_requests"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().state_read_bytes,
            0_u64,
            "activation-terminal-success-summary.final_consumption.state_read_bytes"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().state_write_bytes,
            0_u64,
            "activation-terminal-success-summary.final_consumption.state_write_bytes"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().blob_read_bytes,
            0_u64,
            "activation-terminal-success-summary.final_consumption.blob_read_bytes"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().blob_write_bytes,
            0_u64,
            "activation-terminal-success-summary.final_consumption.blob_write_bytes"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().log_bytes,
            0_u64,
            "activation-terminal-success-summary.final_consumption.log_bytes"
        );
        assert_eq!(
            value.final_consumption.as_ref().unwrap().effect_count,
            4_294_967_295_u32,
            "activation-terminal-success-summary.final_consumption.effect_count"
        );
        assert!(
            value.terminal_at_unix_millis.is_some(),
            "activation-terminal-success-summary.terminal_at_unix_millis.presence"
        );
        assert_eq!(
            value.terminal_at_unix_millis.unwrap(),
            18_446_744_073_709_551_615_u64,
            "activation-terminal-success-summary.terminal_at_unix_millis"
        );
    }
    {
        let value = GetPolicyResponse {
            ..Default::default()
        };
        assert!(value.policy.is_none(), "policy-absence.policy.presence");
    }
    {
        let value = GetPolicyRequest {
            id: "policy-a".into(),
            record_kind: CapabilityPolicyRecordKind(1),
        };
        assert_eq!(value.id, "policy-a", "policy-record-kind.id");
        assert_eq!(value.record_kind.0, 1, "policy-record-kind.record_kind");
    }
    {
        let value = GetPolicyRequest {
            id: "binding-a".into(),
            record_kind: CapabilityPolicyRecordKind(2),
        };
        assert_eq!(value.id, "binding-a", "provider-binding-record-kind.id");
        assert_eq!(
            value.record_kind.0, 2,
            "provider-binding-record-kind.record_kind"
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
        assert_eq!(value.id, "future-record", "unknown-policy-kind.id");
        assert!(
            value.metadata.is_some(),
            "unknown-policy-kind.metadata.presence"
        );
        assert_eq!(
            value.metadata.as_ref().unwrap().name,
            "future-record",
            "unknown-policy-kind.metadata.name"
        );
        assert!(
            value.metadata.as_ref().unwrap().tenant.is_some(),
            "unknown-policy-kind.metadata.tenant.presence"
        );
        assert_eq!(
            value.metadata.as_ref().unwrap().tenant.as_deref().unwrap(),
            "",
            "unknown-policy-kind.metadata.tenant"
        );
        assert!(
            value.metadata.as_ref().unwrap().namespace.is_some(),
            "unknown-policy-kind.metadata.namespace.presence"
        );
        assert_eq!(
            value
                .metadata
                .as_ref()
                .unwrap()
                .namespace
                .as_deref()
                .unwrap(),
            "",
            "unknown-policy-kind.metadata.namespace"
        );
        assert_eq!(
            value.metadata.as_ref().unwrap().labels.len(),
            1,
            "unknown-policy-kind.metadata.labels.count"
        );
        assert_eq!(
            value.metadata.as_ref().unwrap().labels["sampled"],
            "true",
            "unknown-policy-kind.metadata.labels.0"
        );
        assert_eq!(
            value.metadata.as_ref().unwrap().annotations.len(),
            1,
            "unknown-policy-kind.metadata.annotations.count"
        );
        assert_eq!(
            value.metadata.as_ref().unwrap().annotations["descriptive"],
            "not-authority",
            "unknown-policy-kind.metadata.annotations.0"
        );
        assert_eq!(value.document, "", "unknown-policy-kind.document");
        assert_eq!(
            value.generation, 18_446_744_073_709_551_615_u64,
            "unknown-policy-kind.generation"
        );
        assert_eq!(value.language, "", "unknown-policy-kind.language");
        assert_eq!(
            value.record_kind.0, 2_147_483_647,
            "unknown-policy-kind.record_kind"
        );
        assert_eq!(
            value.content_digest, "",
            "unknown-policy-kind.content_digest"
        );
        assert!(value.revoked, "unknown-policy-kind.revoked");
    }
    {
        let value = ApplyPolicyRequest {
            operation_id: "operation-a".into(),
            ..Default::default()
        };
        assert!(
            value.policy.is_none(),
            "apply-missing-generation.policy.presence"
        );
        assert!(
            value.expected_generation.is_none(),
            "apply-missing-generation.expected_generation.presence"
        );
        assert_eq!(
            value.operation_id, "operation-a",
            "apply-missing-generation.operation_id"
        );
    }
    {
        let value = ApplyPolicyRequest {
            expected_generation: Some(0_u64),
            operation_id: String::new(),
            ..Default::default()
        };
        assert!(
            value.policy.is_none(),
            "apply-present-empty-operation.policy.presence"
        );
        assert!(
            value.expected_generation.is_some(),
            "apply-present-empty-operation.expected_generation.presence"
        );
        assert_eq!(
            value.expected_generation.unwrap(),
            0_u64,
            "apply-present-empty-operation.expected_generation"
        );
        assert_eq!(
            value.operation_id, "",
            "apply-present-empty-operation.operation_id"
        );
    }
    {
        let value = ApplyPolicyRequest{policy: Some(Policy{id: "policy-a".into(), metadata: Some(ObjectMetadata{name: "policy-a".into(), tenant: Some("tenant-a".into()), labels: BTreeMap::from([]), annotations: BTreeMap::from([]), ..Default::default()}), document: "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"rules\":[{\"id\":\"deny\",\"effect\":\"deny\",\"principals\":[{\"kind\":\"user\",\"subject\":\"fixture-user\"}],\"services\":[\"echo\"],\"publications\":[\"publication:sha256:1111111111111111111111111111111111111111111111111111111111111111\"],\"capability\":\"latent:secrets/reader@0.1.0\",\"operations\":[\"read\"],\"resources\":{\"kind\":\"secrets\",\"references\":[\"fixture-selector\"]},\"ceiling\":{\"operations\":0,\"inputBytes\":0,\"outputBytes\":0,\"wallTimeMillis\":0}}]}".into(), generation: 0_u64, language: "lsf-capability-policy-v1".into(), record_kind: CapabilityPolicyRecordKind(1), content_digest: String::new(), revoked: false}), expected_generation: Some(0_u64), operation_id: "operation-a".into()};
        assert!(
            value.policy.is_some(),
            "apply-create-policy-zero-generation.policy.presence"
        );
        assert_eq!(
            value.policy.as_ref().unwrap().id,
            "policy-a",
            "apply-create-policy-zero-generation.policy.id"
        );
        assert!(
            value.policy.as_ref().unwrap().metadata.is_some(),
            "apply-create-policy-zero-generation.policy.metadata.presence"
        );
        assert_eq!(
            value
                .policy
                .as_ref()
                .unwrap()
                .metadata
                .as_ref()
                .unwrap()
                .name,
            "policy-a",
            "apply-create-policy-zero-generation.policy.metadata.name"
        );
        assert!(
            value
                .policy
                .as_ref()
                .unwrap()
                .metadata
                .as_ref()
                .unwrap()
                .tenant
                .is_some(),
            "apply-create-policy-zero-generation.policy.metadata.tenant.presence"
        );
        assert_eq!(
            value
                .policy
                .as_ref()
                .unwrap()
                .metadata
                .as_ref()
                .unwrap()
                .tenant
                .as_deref()
                .unwrap(),
            "tenant-a",
            "apply-create-policy-zero-generation.policy.metadata.tenant"
        );
        assert!(
            value
                .policy
                .as_ref()
                .unwrap()
                .metadata
                .as_ref()
                .unwrap()
                .namespace
                .is_none(),
            "apply-create-policy-zero-generation.policy.metadata.namespace.presence"
        );
        assert_eq!(
            value
                .policy
                .as_ref()
                .unwrap()
                .metadata
                .as_ref()
                .unwrap()
                .labels
                .len(),
            0,
            "apply-create-policy-zero-generation.policy.metadata.labels.count"
        );
        assert_eq!(
            value
                .policy
                .as_ref()
                .unwrap()
                .metadata
                .as_ref()
                .unwrap()
                .annotations
                .len(),
            0,
            "apply-create-policy-zero-generation.policy.metadata.annotations.count"
        );
        assert_eq!(value.policy.as_ref().unwrap().document, "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"rules\":[{\"id\":\"deny\",\"effect\":\"deny\",\"principals\":[{\"kind\":\"user\",\"subject\":\"fixture-user\"}],\"services\":[\"echo\"],\"publications\":[\"publication:sha256:1111111111111111111111111111111111111111111111111111111111111111\"],\"capability\":\"latent:secrets/reader@0.1.0\",\"operations\":[\"read\"],\"resources\":{\"kind\":\"secrets\",\"references\":[\"fixture-selector\"]},\"ceiling\":{\"operations\":0,\"inputBytes\":0,\"outputBytes\":0,\"wallTimeMillis\":0}}]}", "apply-create-policy-zero-generation.policy.document");
        assert_eq!(
            value.policy.as_ref().unwrap().generation,
            0_u64,
            "apply-create-policy-zero-generation.policy.generation"
        );
        assert_eq!(
            value.policy.as_ref().unwrap().language,
            "lsf-capability-policy-v1",
            "apply-create-policy-zero-generation.policy.language"
        );
        assert_eq!(
            value.policy.as_ref().unwrap().record_kind.0,
            1,
            "apply-create-policy-zero-generation.policy.record_kind"
        );
        assert_eq!(
            value.policy.as_ref().unwrap().content_digest,
            "",
            "apply-create-policy-zero-generation.policy.content_digest"
        );
        assert!(
            !value.policy.as_ref().unwrap().revoked,
            "apply-create-policy-zero-generation.policy.revoked"
        );
        assert!(
            value.expected_generation.is_some(),
            "apply-create-policy-zero-generation.expected_generation.presence"
        );
        assert_eq!(
            value.expected_generation.unwrap(),
            0_u64,
            "apply-create-policy-zero-generation.expected_generation"
        );
        assert_eq!(
            value.operation_id, "operation-a",
            "apply-create-policy-zero-generation.operation_id"
        );
    }
    {
        let value = ApplyPolicyRequest{policy: Some(Policy{id: "binding-a".into(), metadata: Some(ObjectMetadata{name: "binding-a".into(), tenant: Some("tenant-a".into()), labels: BTreeMap::from([]), annotations: BTreeMap::from([]), ..Default::default()}), document: "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"capability\":\"latent:secrets/reader@0.1.0\",\"providerProfile\":\"local-secrets-v1\",\"configurationDigest\":\"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"configurationEpoch\":18446744073709551615,\"restriction\":{\"operations\":[],\"ceiling\":{\"operations\":0,\"inputBytes\":18446744073709551615,\"outputBytes\":0,\"wallTimeMillis\":0}}}".into(), generation: 0_u64, language: "lsf-provider-binding-v1".into(), record_kind: CapabilityPolicyRecordKind(2), content_digest: String::new(), revoked: false}), expected_generation: Some(18_446_744_073_709_551_615_u64), operation_id: "operation-binding".into()};
        assert!(
            value.policy.is_some(),
            "apply-binding-max-precondition-and-opaque-limit-document.policy.presence"
        );
        assert_eq!(
            value.policy.as_ref().unwrap().id,
            "binding-a",
            "apply-binding-max-precondition-and-opaque-limit-document.policy.id"
        );
        assert!(
            value.policy.as_ref().unwrap().metadata.is_some(),
            "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.presence"
        );
        assert_eq!(
            value
                .policy
                .as_ref()
                .unwrap()
                .metadata
                .as_ref()
                .unwrap()
                .name,
            "binding-a",
            "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.name"
        );
        assert!(value.policy.as_ref().unwrap().metadata.as_ref().unwrap().tenant.is_some(), "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.tenant.presence");
        assert_eq!(
            value
                .policy
                .as_ref()
                .unwrap()
                .metadata
                .as_ref()
                .unwrap()
                .tenant
                .as_deref()
                .unwrap(),
            "tenant-a",
            "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.tenant"
        );
        assert!(value.policy.as_ref().unwrap().metadata.as_ref().unwrap().namespace.is_none(), "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.namespace.presence");
        assert_eq!(
            value
                .policy
                .as_ref()
                .unwrap()
                .metadata
                .as_ref()
                .unwrap()
                .labels
                .len(),
            0,
            "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.labels.count"
        );
        assert_eq!(value.policy.as_ref().unwrap().metadata.as_ref().unwrap().annotations.len(), 0, "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.annotations.count");
        assert_eq!(value.policy.as_ref().unwrap().document, "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"capability\":\"latent:secrets/reader@0.1.0\",\"providerProfile\":\"local-secrets-v1\",\"configurationDigest\":\"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"configurationEpoch\":18446744073709551615,\"restriction\":{\"operations\":[],\"ceiling\":{\"operations\":0,\"inputBytes\":18446744073709551615,\"outputBytes\":0,\"wallTimeMillis\":0}}}", "apply-binding-max-precondition-and-opaque-limit-document.policy.document");
        assert_eq!(
            value.policy.as_ref().unwrap().generation,
            0_u64,
            "apply-binding-max-precondition-and-opaque-limit-document.policy.generation"
        );
        assert_eq!(
            value.policy.as_ref().unwrap().language,
            "lsf-provider-binding-v1",
            "apply-binding-max-precondition-and-opaque-limit-document.policy.language"
        );
        assert_eq!(
            value.policy.as_ref().unwrap().record_kind.0,
            2,
            "apply-binding-max-precondition-and-opaque-limit-document.policy.record_kind"
        );
        assert_eq!(
            value.policy.as_ref().unwrap().content_digest,
            "",
            "apply-binding-max-precondition-and-opaque-limit-document.policy.content_digest"
        );
        assert!(
            !value.policy.as_ref().unwrap().revoked,
            "apply-binding-max-precondition-and-opaque-limit-document.policy.revoked"
        );
        assert!(
            value.expected_generation.is_some(),
            "apply-binding-max-precondition-and-opaque-limit-document.expected_generation.presence"
        );
        assert_eq!(
            value.expected_generation.unwrap(),
            18_446_744_073_709_551_615_u64,
            "apply-binding-max-precondition-and-opaque-limit-document.expected_generation"
        );
        assert_eq!(
            value.operation_id, "operation-binding",
            "apply-binding-max-precondition-and-opaque-limit-document.operation_id"
        );
    }
    {
        let value = ListPoliciesRequest {
            record_kind: CapabilityPolicyRecordKind(1),
            ..Default::default()
        };
        assert_eq!(value.record_kind.0, 1, "policy-page-absent.record_kind");
        assert!(value.page.is_none(), "policy-page-absent.page.presence");
    }
    {
        let value = ListPoliciesRequest {
            record_kind: CapabilityPolicyRecordKind(2),
            page: Some(PageRequest {
                page_size: 0_u32,
                ..Default::default()
            }),
        };
        assert_eq!(
            value.record_kind.0, 2,
            "policy-page-zero-invalid.record_kind"
        );
        assert!(
            value.page.is_some(),
            "policy-page-zero-invalid.page.presence"
        );
        assert_eq!(
            value.page.as_ref().unwrap().page_size,
            0_u32,
            "policy-page-zero-invalid.page.page_size"
        );
        assert!(
            value.page.as_ref().unwrap().page_token.is_none(),
            "policy-page-zero-invalid.page.page_token.presence"
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
        assert_eq!(
            value.record_kind.0, 1,
            "policy-page-empty-token-invalid.record_kind"
        );
        assert!(
            value.page.is_some(),
            "policy-page-empty-token-invalid.page.presence"
        );
        assert_eq!(
            value.page.as_ref().unwrap().page_size,
            1_u32,
            "policy-page-empty-token-invalid.page.page_size"
        );
        assert!(
            value.page.as_ref().unwrap().page_token.is_some(),
            "policy-page-empty-token-invalid.page.page_token.presence"
        );
        assert_eq!(
            value.page.as_ref().unwrap().page_token.as_deref().unwrap(),
            "",
            "policy-page-empty-token-invalid.page.page_token"
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
        assert_eq!(value.policies.len(), 1, "policy-page-first.policies.count");
        assert_eq!(
            value.policies[0].id, "policy-a",
            "policy-page-first.policies.0.id"
        );
        assert!(
            value.policies[0].metadata.is_none(),
            "policy-page-first.policies.0.metadata.presence"
        );
        assert_eq!(
            value.policies[0].document, "",
            "policy-page-first.policies.0.document"
        );
        assert_eq!(
            value.policies[0].generation, 18_446_744_073_709_551_615_u64,
            "policy-page-first.policies.0.generation"
        );
        assert_eq!(
            value.policies[0].language, "",
            "policy-page-first.policies.0.language"
        );
        assert_eq!(
            value.policies[0].record_kind.0, 1,
            "policy-page-first.policies.0.record_kind"
        );
        assert_eq!(
            value.policies[0].content_digest,
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "policy-page-first.policies.0.content_digest"
        );
        assert!(
            value.policies[0].revoked,
            "policy-page-first.policies.0.revoked"
        );
        assert_eq!(
            value.catalog_generation, 18_446_744_073_709_551_615_u64,
            "policy-page-first.catalog_generation"
        );
        assert!(value.page.is_some(), "policy-page-first.page.presence");
        assert!(
            value.page.as_ref().unwrap().next_page_token.is_some(),
            "policy-page-first.page.next_page_token.presence"
        );
        assert_eq!(
            value
                .page
                .as_ref()
                .unwrap()
                .next_page_token
                .as_deref()
                .unwrap(),
            "opaque-policy-cursor",
            "policy-page-first.page.next_page_token"
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
        assert_eq!(value.policies.len(), 0, "policy-page-last.policies.count");
        assert_eq!(
            value.catalog_generation, 18_446_744_073_709_551_615_u64,
            "policy-page-last.catalog_generation"
        );
        assert!(value.page.is_some(), "policy-page-last.page.presence");
        assert!(
            value.page.as_ref().unwrap().next_page_token.is_none(),
            "policy-page-last.page.next_page_token.presence"
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
        assert_eq!(
            value.record_kind.0, 1,
            "policy-next-page-request.record_kind"
        );
        assert!(
            value.page.is_some(),
            "policy-next-page-request.page.presence"
        );
        assert_eq!(
            value.page.as_ref().unwrap().page_size,
            1_u32,
            "policy-next-page-request.page.page_size"
        );
        assert!(
            value.page.as_ref().unwrap().page_token.is_some(),
            "policy-next-page-request.page.page_token.presence"
        );
        assert_eq!(
            value.page.as_ref().unwrap().page_token.as_deref().unwrap(),
            "opaque-policy-cursor",
            "policy-next-page-request.page.page_token"
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
        assert!(
            value.policy.is_some(),
            "apply-retains-original-receipt.policy.presence"
        );
        assert_eq!(
            value.policy.as_ref().unwrap().id,
            "policy-a",
            "apply-retains-original-receipt.policy.id"
        );
        assert!(
            value.policy.as_ref().unwrap().metadata.is_none(),
            "apply-retains-original-receipt.policy.metadata.presence"
        );
        assert_eq!(
            value.policy.as_ref().unwrap().document,
            "",
            "apply-retains-original-receipt.policy.document"
        );
        assert_eq!(
            value.policy.as_ref().unwrap().generation,
            18_446_744_073_709_551_615_u64,
            "apply-retains-original-receipt.policy.generation"
        );
        assert_eq!(
            value.policy.as_ref().unwrap().language,
            "",
            "apply-retains-original-receipt.policy.language"
        );
        assert_eq!(
            value.policy.as_ref().unwrap().record_kind.0,
            1,
            "apply-retains-original-receipt.policy.record_kind"
        );
        assert_eq!(
            value.policy.as_ref().unwrap().content_digest,
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "apply-retains-original-receipt.policy.content_digest"
        );
        assert!(
            !value.policy.as_ref().unwrap().revoked,
            "apply-retains-original-receipt.policy.revoked"
        );
        assert!(
            value.receipt.is_some(),
            "apply-retains-original-receipt.receipt.presence"
        );
        assert_eq!(
            value.receipt.as_ref().unwrap().operation_id,
            "operation-a",
            "apply-retains-original-receipt.receipt.operation_id"
        );
        assert_eq!(
            value.receipt.as_ref().unwrap().tenant,
            "tenant-a",
            "apply-retains-original-receipt.receipt.tenant"
        );
        assert_eq!(
            value.receipt.as_ref().unwrap().id,
            "policy-a",
            "apply-retains-original-receipt.receipt.id"
        );
        assert_eq!(
            value.receipt.as_ref().unwrap().record_kind.0,
            1,
            "apply-retains-original-receipt.receipt.record_kind"
        );
        assert_eq!(
            value.receipt.as_ref().unwrap().generation,
            18_446_744_073_709_551_615_u64,
            "apply-retains-original-receipt.receipt.generation"
        );
        assert_eq!(
            value.receipt.as_ref().unwrap().content_digest,
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "apply-retains-original-receipt.receipt.content_digest"
        );
        assert!(
            !value.receipt.as_ref().unwrap().revoked,
            "apply-retains-original-receipt.receipt.revoked"
        );
    }
    {
        let value = GetPolicyOperationRequest {
            operation_id: "operation-a".into(),
        };
        assert_eq!(
            value.operation_id, "operation-a",
            "get-policy-operation-known-id.operation_id"
        );
    }
    {
        let value = GetPolicyOperationResponse {
            ..Default::default()
        };
        assert!(
            value.receipt.is_none(),
            "operation-recovery-not-retained-is-unknown.receipt.presence"
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
        assert!(
            value.receipt.is_some(),
            "operation-recovery-original-receipt.receipt.presence"
        );
        assert_eq!(
            value.receipt.as_ref().unwrap().operation_id,
            "operation-a",
            "operation-recovery-original-receipt.receipt.operation_id"
        );
        assert_eq!(
            value.receipt.as_ref().unwrap().tenant,
            "tenant-a",
            "operation-recovery-original-receipt.receipt.tenant"
        );
        assert_eq!(
            value.receipt.as_ref().unwrap().id,
            "policy-a",
            "operation-recovery-original-receipt.receipt.id"
        );
        assert_eq!(
            value.receipt.as_ref().unwrap().record_kind.0,
            1,
            "operation-recovery-original-receipt.receipt.record_kind"
        );
        assert_eq!(
            value.receipt.as_ref().unwrap().generation,
            18_446_744_073_709_551_615_u64,
            "operation-recovery-original-receipt.receipt.generation"
        );
        assert_eq!(
            value.receipt.as_ref().unwrap().content_digest,
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "operation-recovery-original-receipt.receipt.content_digest"
        );
        assert!(
            !value.receipt.as_ref().unwrap().revoked,
            "operation-recovery-original-receipt.receipt.revoked"
        );
    }
    {
        let value = ListCapabilitiesRequest {
            deployment_id: "deployment-a".into(),
            include_node_usage: false,
            ..Default::default()
        };
        assert!(
            value.contract_prefix.is_none(),
            "capabilities-absent-page-default.contract_prefix.presence"
        );
        assert!(
            value.provider.is_none(),
            "capabilities-absent-page-default.provider.presence"
        );
        assert!(
            value.page.is_none(),
            "capabilities-absent-page-default.page.presence"
        );
        assert_eq!(
            value.deployment_id, "deployment-a",
            "capabilities-absent-page-default.deployment_id"
        );
        assert!(
            !value.include_node_usage,
            "capabilities-absent-page-default.include_node_usage"
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
        assert!(
            value.contract_prefix.is_none(),
            "capabilities-zero-page-default.contract_prefix.presence"
        );
        assert!(
            value.provider.is_none(),
            "capabilities-zero-page-default.provider.presence"
        );
        assert!(
            value.page.is_some(),
            "capabilities-zero-page-default.page.presence"
        );
        assert_eq!(
            value.page.as_ref().unwrap().page_size,
            0_u32,
            "capabilities-zero-page-default.page.page_size"
        );
        assert!(
            value.page.as_ref().unwrap().page_token.is_none(),
            "capabilities-zero-page-default.page.page_token.presence"
        );
        assert_eq!(
            value.deployment_id, "deployment-a",
            "capabilities-zero-page-default.deployment_id"
        );
        assert!(
            !value.include_node_usage,
            "capabilities-zero-page-default.include_node_usage"
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
        assert!(
            value.contract_prefix.is_some(),
            "capabilities-present-empty-filters.contract_prefix.presence"
        );
        assert_eq!(
            value.contract_prefix.as_deref().unwrap(),
            "",
            "capabilities-present-empty-filters.contract_prefix"
        );
        assert!(
            value.provider.is_some(),
            "capabilities-present-empty-filters.provider.presence"
        );
        assert_eq!(
            value.provider.as_deref().unwrap(),
            "",
            "capabilities-present-empty-filters.provider"
        );
        assert!(
            value.page.is_some(),
            "capabilities-present-empty-filters.page.presence"
        );
        assert_eq!(
            value.page.as_ref().unwrap().page_size,
            128_u32,
            "capabilities-present-empty-filters.page.page_size"
        );
        assert!(
            value.page.as_ref().unwrap().page_token.is_none(),
            "capabilities-present-empty-filters.page.page_token.presence"
        );
        assert_eq!(
            value.deployment_id, "deployment-a",
            "capabilities-present-empty-filters.deployment_id"
        );
        assert!(
            value.include_node_usage,
            "capabilities-present-empty-filters.include_node_usage"
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
        assert!(
            value.contract_prefix.is_none(),
            "capabilities-explicit-deployment-required.contract_prefix.presence"
        );
        assert!(
            value.provider.is_none(),
            "capabilities-explicit-deployment-required.provider.presence"
        );
        assert!(
            value.page.is_some(),
            "capabilities-explicit-deployment-required.page.presence"
        );
        assert_eq!(
            value.page.as_ref().unwrap().page_size,
            1_u32,
            "capabilities-explicit-deployment-required.page.page_size"
        );
        assert!(
            value.page.as_ref().unwrap().page_token.is_none(),
            "capabilities-explicit-deployment-required.page.page_token.presence"
        );
        assert_eq!(
            value.deployment_id, "",
            "capabilities-explicit-deployment-required.deployment_id"
        );
        assert!(
            !value.include_node_usage,
            "capabilities-explicit-deployment-required.include_node_usage"
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
        assert!(
            value.contract_prefix.is_none(),
            "capabilities-page-too-large.contract_prefix.presence"
        );
        assert!(
            value.provider.is_none(),
            "capabilities-page-too-large.provider.presence"
        );
        assert!(
            value.page.is_some(),
            "capabilities-page-too-large.page.presence"
        );
        assert_eq!(
            value.page.as_ref().unwrap().page_size,
            4_294_967_295_u32,
            "capabilities-page-too-large.page.page_size"
        );
        assert!(
            value.page.as_ref().unwrap().page_token.is_none(),
            "capabilities-page-too-large.page.page_token.presence"
        );
        assert_eq!(
            value.deployment_id, "deployment-a",
            "capabilities-page-too-large.deployment_id"
        );
        assert!(
            !value.include_node_usage,
            "capabilities-page-too-large.include_node_usage"
        );
    }
    {
        let value = ListCapabilitiesResponse{capabilities: vec![CapabilityDescriptor{id: "latent:secrets/reader@0.1.0".into(), contract: "latent:secrets/reader@0.1.0".into(), provider: "local-secrets-v1".into(), operations: vec!["read".into()], attributes: BTreeMap::from([]), inspection: Some(CapabilityBindingInspection{definition_digest: Some(String::new()), provider_binding: Some(CapabilityInspectionPolicy{id: "binding-a".into(), revision: 18_446_744_073_709_551_615_u64, digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb".into()}), policies: vec![CapabilityInspectionPolicy{id: "policy-a".into(), revision: 9_223_372_036_854_775_808_u64, digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into()}], provider_profile: "local-secrets-v1".into(), provider_configuration_digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb".into(), provider_configuration_epoch: 18_446_744_073_709_551_615_u64, state: "provider-configuration-changed".into()})}, CapabilityDescriptor{id: "future-capability".into(), contract: "future-contract".into(), provider: "future-provider".into(), operations: vec![], attributes: BTreeMap::from([("descriptive".into(), "not-authority".into())]), ..Default::default()}], page: Some(PageResponse{next_page_token: Some("opaque-capability-cursor".into())}), revision: Some(CapabilityInspectionRevision{deployment_id: "deployment-a".into(), revision_id: "revision-a".into(), component_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(), publication_id: Some("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111".into()), route_generation: 18_446_744_073_709_551_615_u64, catalog_transaction: 9_223_372_036_854_775_808_u64}), tenant_usage: Some(CapabilityResourceUsage{scope: "tenant".into(), counters: BTreeMap::from([("sessions".into(), 18_446_744_073_709_551_615_u64), ("calls".into(), 0_u64)]), unavailable: vec!["fixture-owner-unavailable".into()]}), state: "sampled".into(), ..Default::default()};
        assert_eq!(
            value.capabilities.len(),
            2,
            "redacted-capability-provider-inspection.capabilities.count"
        );
        assert_eq!(
            value.capabilities[0].id, "latent:secrets/reader@0.1.0",
            "redacted-capability-provider-inspection.capabilities.0.id"
        );
        assert_eq!(
            value.capabilities[0].contract, "latent:secrets/reader@0.1.0",
            "redacted-capability-provider-inspection.capabilities.0.contract"
        );
        assert_eq!(
            value.capabilities[0].provider, "local-secrets-v1",
            "redacted-capability-provider-inspection.capabilities.0.provider"
        );
        assert_eq!(
            value.capabilities[0].operations.len(),
            1,
            "redacted-capability-provider-inspection.capabilities.0.operations.count"
        );
        assert_eq!(
            value.capabilities[0].operations[0], "read",
            "redacted-capability-provider-inspection.capabilities.0.operations.0"
        );
        assert_eq!(
            value.capabilities[0].attributes.len(),
            0,
            "redacted-capability-provider-inspection.capabilities.0.attributes.count"
        );
        assert!(
            value.capabilities[0].inspection.is_some(),
            "redacted-capability-provider-inspection.capabilities.0.inspection.presence"
        );
        assert!(value.capabilities[0].inspection.as_ref().unwrap().definition_digest.is_some(), "redacted-capability-provider-inspection.capabilities.0.inspection.definition_digest.presence");
        assert_eq!(
            value.capabilities[0]
                .inspection
                .as_ref()
                .unwrap()
                .definition_digest
                .as_deref()
                .unwrap(),
            "",
            "redacted-capability-provider-inspection.capabilities.0.inspection.definition_digest"
        );
        assert!(value.capabilities[0].inspection.as_ref().unwrap().provider_binding.is_some(), "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.presence");
        assert_eq!(
            value.capabilities[0]
                .inspection
                .as_ref()
                .unwrap()
                .provider_binding
                .as_ref()
                .unwrap()
                .id,
            "binding-a",
            "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.id"
        );
        assert_eq!(value.capabilities[0].inspection.as_ref().unwrap().provider_binding.as_ref().unwrap().revision, 18_446_744_073_709_551_615_u64, "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.revision");
        assert_eq!(value.capabilities[0].inspection.as_ref().unwrap().provider_binding.as_ref().unwrap().digest, "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.digest");
        assert_eq!(
            value.capabilities[0]
                .inspection
                .as_ref()
                .unwrap()
                .policies
                .len(),
            1,
            "redacted-capability-provider-inspection.capabilities.0.inspection.policies.count"
        );
        assert_eq!(
            value.capabilities[0].inspection.as_ref().unwrap().policies[0].id,
            "policy-a",
            "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.id"
        );
        assert_eq!(
            value.capabilities[0].inspection.as_ref().unwrap().policies[0].revision,
            9_223_372_036_854_775_808_u64,
            "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.revision"
        );
        assert_eq!(
            value.capabilities[0].inspection.as_ref().unwrap().policies[0].digest,
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.digest"
        );
        assert_eq!(
            value.capabilities[0]
                .inspection
                .as_ref()
                .unwrap()
                .provider_profile,
            "local-secrets-v1",
            "redacted-capability-provider-inspection.capabilities.0.inspection.provider_profile"
        );
        assert_eq!(value.capabilities[0].inspection.as_ref().unwrap().provider_configuration_digest, "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "redacted-capability-provider-inspection.capabilities.0.inspection.provider_configuration_digest");
        assert_eq!(value.capabilities[0].inspection.as_ref().unwrap().provider_configuration_epoch, 18_446_744_073_709_551_615_u64, "redacted-capability-provider-inspection.capabilities.0.inspection.provider_configuration_epoch");
        assert_eq!(
            value.capabilities[0].inspection.as_ref().unwrap().state,
            "provider-configuration-changed",
            "redacted-capability-provider-inspection.capabilities.0.inspection.state"
        );
        assert_eq!(
            value.capabilities[1].id, "future-capability",
            "redacted-capability-provider-inspection.capabilities.1.id"
        );
        assert_eq!(
            value.capabilities[1].contract, "future-contract",
            "redacted-capability-provider-inspection.capabilities.1.contract"
        );
        assert_eq!(
            value.capabilities[1].provider, "future-provider",
            "redacted-capability-provider-inspection.capabilities.1.provider"
        );
        assert_eq!(
            value.capabilities[1].operations.len(),
            0,
            "redacted-capability-provider-inspection.capabilities.1.operations.count"
        );
        assert_eq!(
            value.capabilities[1].attributes.len(),
            1,
            "redacted-capability-provider-inspection.capabilities.1.attributes.count"
        );
        assert_eq!(
            value.capabilities[1].attributes["descriptive"], "not-authority",
            "redacted-capability-provider-inspection.capabilities.1.attributes.0"
        );
        assert!(
            value.capabilities[1].inspection.is_none(),
            "redacted-capability-provider-inspection.capabilities.1.inspection.presence"
        );
        assert!(
            value.page.is_some(),
            "redacted-capability-provider-inspection.page.presence"
        );
        assert!(
            value.page.as_ref().unwrap().next_page_token.is_some(),
            "redacted-capability-provider-inspection.page.next_page_token.presence"
        );
        assert_eq!(
            value
                .page
                .as_ref()
                .unwrap()
                .next_page_token
                .as_deref()
                .unwrap(),
            "opaque-capability-cursor",
            "redacted-capability-provider-inspection.page.next_page_token"
        );
        assert!(
            value.revision.is_some(),
            "redacted-capability-provider-inspection.revision.presence"
        );
        assert_eq!(
            value.revision.as_ref().unwrap().deployment_id,
            "deployment-a",
            "redacted-capability-provider-inspection.revision.deployment_id"
        );
        assert_eq!(
            value.revision.as_ref().unwrap().revision_id,
            "revision-a",
            "redacted-capability-provider-inspection.revision.revision_id"
        );
        assert_eq!(
            value.revision.as_ref().unwrap().component_digest,
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "redacted-capability-provider-inspection.revision.component_digest"
        );
        assert!(
            value.revision.as_ref().unwrap().publication_id.is_some(),
            "redacted-capability-provider-inspection.revision.publication_id.presence"
        );
        assert_eq!(
            value
                .revision
                .as_ref()
                .unwrap()
                .publication_id
                .as_deref()
                .unwrap(),
            "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111",
            "redacted-capability-provider-inspection.revision.publication_id"
        );
        assert_eq!(
            value.revision.as_ref().unwrap().route_generation,
            18_446_744_073_709_551_615_u64,
            "redacted-capability-provider-inspection.revision.route_generation"
        );
        assert_eq!(
            value.revision.as_ref().unwrap().catalog_transaction,
            9_223_372_036_854_775_808_u64,
            "redacted-capability-provider-inspection.revision.catalog_transaction"
        );
        assert!(
            value.tenant_usage.is_some(),
            "redacted-capability-provider-inspection.tenant_usage.presence"
        );
        assert_eq!(
            value.tenant_usage.as_ref().unwrap().scope,
            "tenant",
            "redacted-capability-provider-inspection.tenant_usage.scope"
        );
        assert_eq!(
            value.tenant_usage.as_ref().unwrap().counters.len(),
            2,
            "redacted-capability-provider-inspection.tenant_usage.counters.count"
        );
        assert_eq!(
            value.tenant_usage.as_ref().unwrap().counters["sessions"],
            18_446_744_073_709_551_615_u64,
            "redacted-capability-provider-inspection.tenant_usage.counters.0"
        );
        assert_eq!(
            value.tenant_usage.as_ref().unwrap().counters["calls"],
            0_u64,
            "redacted-capability-provider-inspection.tenant_usage.counters.1"
        );
        assert_eq!(
            value.tenant_usage.as_ref().unwrap().unavailable.len(),
            1,
            "redacted-capability-provider-inspection.tenant_usage.unavailable.count"
        );
        assert_eq!(
            value.tenant_usage.as_ref().unwrap().unavailable[0],
            "fixture-owner-unavailable",
            "redacted-capability-provider-inspection.tenant_usage.unavailable.0"
        );
        assert!(
            value.node_usage.is_none(),
            "redacted-capability-provider-inspection.node_usage.presence"
        );
        assert_eq!(
            value.state, "sampled",
            "redacted-capability-provider-inspection.state"
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
        assert_eq!(
            value.capabilities.len(),
            0,
            "missing-provider-plan-not-zero-usage.capabilities.count"
        );
        assert!(
            value.page.is_none(),
            "missing-provider-plan-not-zero-usage.page.presence"
        );
        assert!(
            value.revision.is_none(),
            "missing-provider-plan-not-zero-usage.revision.presence"
        );
        assert!(
            value.tenant_usage.is_none(),
            "missing-provider-plan-not-zero-usage.tenant_usage.presence"
        );
        assert!(
            value.node_usage.is_some(),
            "missing-provider-plan-not-zero-usage.node_usage.presence"
        );
        assert_eq!(
            value.node_usage.as_ref().unwrap().scope,
            "node",
            "missing-provider-plan-not-zero-usage.node_usage.scope"
        );
        assert_eq!(
            value.node_usage.as_ref().unwrap().counters.len(),
            0,
            "missing-provider-plan-not-zero-usage.node_usage.counters.count"
        );
        assert_eq!(
            value.node_usage.as_ref().unwrap().unavailable.len(),
            2,
            "missing-provider-plan-not-zero-usage.node_usage.unavailable.count"
        );
        assert_eq!(
            value.node_usage.as_ref().unwrap().unavailable[0],
            "provider-pools-no-retained-owner",
            "missing-provider-plan-not-zero-usage.node_usage.unavailable.0"
        );
        assert_eq!(
            value.node_usage.as_ref().unwrap().unavailable[1],
            "audit-owner-not-configured",
            "missing-provider-plan-not-zero-usage.node_usage.unavailable.1"
        );
        assert_eq!(
            value.state, "binding-plan-unavailable",
            "missing-provider-plan-not-zero-usage.state"
        );
    }
    {
        let value = CapabilityInspectionCeiling {
            operations: 0_u32,
            input_bytes: 18_446_744_073_709_551_615_u64,
            output_bytes: 0_u64,
            wall_time_millis: 18_446_744_073_709_551_615_u64,
        };
        assert_eq!(
            value.operations, 0_u32,
            "typed-ceiling-zero-and-max-not-grant.operations"
        );
        assert_eq!(
            value.input_bytes, 18_446_744_073_709_551_615_u64,
            "typed-ceiling-zero-and-max-not-grant.input_bytes"
        );
        assert_eq!(
            value.output_bytes, 0_u64,
            "typed-ceiling-zero-and-max-not-grant.output_bytes"
        );
        assert_eq!(
            value.wall_time_millis, 18_446_744_073_709_551_615_u64,
            "typed-ceiling-zero-and-max-not-grant.wall_time_millis"
        );
    }
    {
        let value = CallOptions {
            ..Default::default()
        };
        assert!(
            value.timeout_millis.is_none(),
            "local-timeout-absent.timeout_millis.presence"
        );
    }
    {
        let value = CallOptions {
            timeout_millis: Some(0_u64),
        };
        assert!(
            value.timeout_millis.is_some(),
            "local-timeout-zero.timeout_millis.presence"
        );
        assert_eq!(
            value.timeout_millis.unwrap(),
            0_u64,
            "local-timeout-zero.timeout_millis"
        );
    }
    {
        let value = CallOptions {
            timeout_millis: Some(18_446_744_073_709_551_615_u64),
        };
        assert!(
            value.timeout_millis.is_some(),
            "local-timeout-max-not-wrapped.timeout_millis.presence"
        );
        assert_eq!(
            value.timeout_millis.unwrap(),
            18_446_744_073_709_551_615_u64,
            "local-timeout-max-not-wrapped.timeout_millis"
        );
    }
    {
        let value = ClientFailure {
            category: FailureCategory(1),
            message: "local-cancelled".into(),
            dispatched: false,
            outcome: OutcomeKnowledge(1),
            identity: RequestIdentity {
                activation_id: Some("activation-a".into()),
                ..Default::default()
            },
            ..Default::default()
        };
        assert_eq!(value.category.0, 1, "local-cancel-before-dispatch.category");
        assert_eq!(
            value.message, "local-cancelled",
            "local-cancel-before-dispatch.message"
        );
        assert!(
            value.grpc_status.is_none(),
            "local-cancel-before-dispatch.grpc_status.presence"
        );
        assert!(
            value.platform_error.is_none(),
            "local-cancel-before-dispatch.platform_error.presence"
        );
        assert!(!value.dispatched, "local-cancel-before-dispatch.dispatched");
        assert_eq!(value.outcome.0, 1, "local-cancel-before-dispatch.outcome");
        assert!(
            value.identity.activation_id.is_some(),
            "local-cancel-before-dispatch.identity.activation_id.presence"
        );
        assert_eq!(
            value.identity.activation_id.as_deref().unwrap(),
            "activation-a",
            "local-cancel-before-dispatch.identity.activation_id"
        );
        assert!(
            value.identity.operation_id.is_none(),
            "local-cancel-before-dispatch.identity.operation_id.presence"
        );
        assert!(
            value.audit_ack.is_none(),
            "local-cancel-before-dispatch.audit_ack.presence"
        );
        assert!(
            value.audit_status.is_none(),
            "local-cancel-before-dispatch.audit_status.presence"
        );
        assert!(
            value.unsupported_wire_value.is_none(),
            "local-cancel-before-dispatch.unsupported_wire_value.presence"
        );
        assert!(
            value.audit_attempt_sequence.is_none(),
            "local-cancel-before-dispatch.audit_attempt_sequence.presence"
        );
    }
    {
        let value = ClientFailure {
            category: FailureCategory(2),
            message: "deadline".into(),
            grpc_status: Some(4_i32),
            dispatched: true,
            outcome: OutcomeKnowledge(2),
            identity: RequestIdentity {
                operation_id: Some("operation-a".into()),
                ..Default::default()
            },
            audit_ack: Some(AuditAck {
                status: AuditAckStatus(2),
                attempt_sequence: Some(18_446_744_073_709_551_615_u64),
            }),
            audit_status: Some("outcome-unknown".into()),
            audit_attempt_sequence: Some(18_446_744_073_709_551_615_u64),
            ..Default::default()
        };
        assert_eq!(
            value.category.0, 2,
            "deadline-after-dispatch-is-uncertain.category"
        );
        assert_eq!(
            value.message, "deadline",
            "deadline-after-dispatch-is-uncertain.message"
        );
        assert!(
            value.grpc_status.is_some(),
            "deadline-after-dispatch-is-uncertain.grpc_status.presence"
        );
        assert_eq!(
            value.grpc_status.unwrap(),
            4_i32,
            "deadline-after-dispatch-is-uncertain.grpc_status"
        );
        assert!(
            value.platform_error.is_none(),
            "deadline-after-dispatch-is-uncertain.platform_error.presence"
        );
        assert!(
            value.dispatched,
            "deadline-after-dispatch-is-uncertain.dispatched"
        );
        assert_eq!(
            value.outcome.0, 2,
            "deadline-after-dispatch-is-uncertain.outcome"
        );
        assert!(
            value.identity.activation_id.is_none(),
            "deadline-after-dispatch-is-uncertain.identity.activation_id.presence"
        );
        assert!(
            value.identity.operation_id.is_some(),
            "deadline-after-dispatch-is-uncertain.identity.operation_id.presence"
        );
        assert_eq!(
            value.identity.operation_id.as_deref().unwrap(),
            "operation-a",
            "deadline-after-dispatch-is-uncertain.identity.operation_id"
        );
        assert!(
            value.audit_ack.is_some(),
            "deadline-after-dispatch-is-uncertain.audit_ack.presence"
        );
        assert_eq!(
            value.audit_ack.as_ref().unwrap().status.0,
            2,
            "deadline-after-dispatch-is-uncertain.audit_ack.status"
        );
        assert!(
            value.audit_ack.as_ref().unwrap().attempt_sequence.is_some(),
            "deadline-after-dispatch-is-uncertain.audit_ack.attempt_sequence.presence"
        );
        assert_eq!(
            value.audit_ack.as_ref().unwrap().attempt_sequence.unwrap(),
            18_446_744_073_709_551_615_u64,
            "deadline-after-dispatch-is-uncertain.audit_ack.attempt_sequence"
        );
        assert!(
            value.audit_status.is_some(),
            "deadline-after-dispatch-is-uncertain.audit_status.presence"
        );
        assert_eq!(
            value.audit_status.as_deref().unwrap(),
            "outcome-unknown",
            "deadline-after-dispatch-is-uncertain.audit_status"
        );
        assert!(
            value.unsupported_wire_value.is_none(),
            "deadline-after-dispatch-is-uncertain.unsupported_wire_value.presence"
        );
        assert!(
            value.audit_attempt_sequence.is_some(),
            "deadline-after-dispatch-is-uncertain.audit_attempt_sequence.presence"
        );
        assert_eq!(
            value.audit_attempt_sequence.unwrap(),
            18_446_744_073_709_551_615_u64,
            "deadline-after-dispatch-is-uncertain.audit_attempt_sequence"
        );
    }
    {
        let value = ClientFailure {
            category: FailureCategory(4),
            message: "capability-policy-conflict".into(),
            grpc_status: Some(9_i32),
            platform_error: Some(PlatformError {
                code: "state-conflict".into(),
                message: "capability-policy-conflict".into(),
                retryable: false,
                detail_items: vec![ErrorDetail {
                    kind: "future-detail".into(),
                    fields: BTreeMap::from([("value".into(), "retained".into())]),
                }],
            }),
            dispatched: true,
            outcome: OutcomeKnowledge(3),
            identity: RequestIdentity {
                operation_id: Some("operation-a".into()),
                ..Default::default()
            },
            ..Default::default()
        };
        assert_eq!(
            value.category.0, 4,
            "rpc-conflict-retains-request-identity.category"
        );
        assert_eq!(
            value.message, "capability-policy-conflict",
            "rpc-conflict-retains-request-identity.message"
        );
        assert!(
            value.grpc_status.is_some(),
            "rpc-conflict-retains-request-identity.grpc_status.presence"
        );
        assert_eq!(
            value.grpc_status.unwrap(),
            9_i32,
            "rpc-conflict-retains-request-identity.grpc_status"
        );
        assert!(
            value.platform_error.is_some(),
            "rpc-conflict-retains-request-identity.platform_error.presence"
        );
        assert_eq!(
            value.platform_error.as_ref().unwrap().code,
            "state-conflict",
            "rpc-conflict-retains-request-identity.platform_error.code"
        );
        assert_eq!(
            value.platform_error.as_ref().unwrap().message,
            "capability-policy-conflict",
            "rpc-conflict-retains-request-identity.platform_error.message"
        );
        assert!(
            !value.platform_error.as_ref().unwrap().retryable,
            "rpc-conflict-retains-request-identity.platform_error.retryable"
        );
        assert_eq!(
            value.platform_error.as_ref().unwrap().detail_items.len(),
            1,
            "rpc-conflict-retains-request-identity.platform_error.detail_items.count"
        );
        assert_eq!(
            value.platform_error.as_ref().unwrap().detail_items[0].kind,
            "future-detail",
            "rpc-conflict-retains-request-identity.platform_error.detail_items.0.kind"
        );
        assert_eq!(
            value.platform_error.as_ref().unwrap().detail_items[0]
                .fields
                .len(),
            1,
            "rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.count"
        );
        assert_eq!(
            value.platform_error.as_ref().unwrap().detail_items[0].fields["value"],
            "retained",
            "rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.0"
        );
        assert!(
            value.dispatched,
            "rpc-conflict-retains-request-identity.dispatched"
        );
        assert_eq!(
            value.outcome.0, 3,
            "rpc-conflict-retains-request-identity.outcome"
        );
        assert!(
            value.identity.activation_id.is_none(),
            "rpc-conflict-retains-request-identity.identity.activation_id.presence"
        );
        assert!(
            value.identity.operation_id.is_some(),
            "rpc-conflict-retains-request-identity.identity.operation_id.presence"
        );
        assert_eq!(
            value.identity.operation_id.as_deref().unwrap(),
            "operation-a",
            "rpc-conflict-retains-request-identity.identity.operation_id"
        );
        assert!(
            value.audit_ack.is_none(),
            "rpc-conflict-retains-request-identity.audit_ack.presence"
        );
        assert!(
            value.audit_status.is_none(),
            "rpc-conflict-retains-request-identity.audit_status.presence"
        );
        assert!(
            value.unsupported_wire_value.is_none(),
            "rpc-conflict-retains-request-identity.unsupported_wire_value.presence"
        );
        assert!(
            value.audit_attempt_sequence.is_none(),
            "rpc-conflict-retains-request-identity.audit_attempt_sequence.presence"
        );
    }
    {
        let value = ClientFailure {
            category: FailureCategory(5),
            message: "invalid-response".into(),
            dispatched: true,
            outcome: OutcomeKnowledge(2),
            identity: RequestIdentity {
                activation_id: Some("activation-a".into()),
                operation_id: Some("operation-a".into()),
            },
            unsupported_wire_value: Some(UnsupportedWireValue {
                field: "phase".into(),
                value: "future-phase-not-authority".into(),
            }),
            ..Default::default()
        };
        assert_eq!(
            value.category.0, 5,
            "decode-failure-retains-known-identity.category"
        );
        assert_eq!(
            value.message, "invalid-response",
            "decode-failure-retains-known-identity.message"
        );
        assert!(
            value.grpc_status.is_none(),
            "decode-failure-retains-known-identity.grpc_status.presence"
        );
        assert!(
            value.platform_error.is_none(),
            "decode-failure-retains-known-identity.platform_error.presence"
        );
        assert!(
            value.dispatched,
            "decode-failure-retains-known-identity.dispatched"
        );
        assert_eq!(
            value.outcome.0, 2,
            "decode-failure-retains-known-identity.outcome"
        );
        assert!(
            value.identity.activation_id.is_some(),
            "decode-failure-retains-known-identity.identity.activation_id.presence"
        );
        assert_eq!(
            value.identity.activation_id.as_deref().unwrap(),
            "activation-a",
            "decode-failure-retains-known-identity.identity.activation_id"
        );
        assert!(
            value.identity.operation_id.is_some(),
            "decode-failure-retains-known-identity.identity.operation_id.presence"
        );
        assert_eq!(
            value.identity.operation_id.as_deref().unwrap(),
            "operation-a",
            "decode-failure-retains-known-identity.identity.operation_id"
        );
        assert!(
            value.audit_ack.is_none(),
            "decode-failure-retains-known-identity.audit_ack.presence"
        );
        assert!(
            value.audit_status.is_none(),
            "decode-failure-retains-known-identity.audit_status.presence"
        );
        assert!(
            value.unsupported_wire_value.is_some(),
            "decode-failure-retains-known-identity.unsupported_wire_value.presence"
        );
        assert_eq!(
            value.unsupported_wire_value.as_ref().unwrap().field,
            "phase",
            "decode-failure-retains-known-identity.unsupported_wire_value.field"
        );
        assert_eq!(
            value.unsupported_wire_value.as_ref().unwrap().value,
            "future-phase-not-authority",
            "decode-failure-retains-known-identity.unsupported_wire_value.value"
        );
        assert!(
            value.audit_attempt_sequence.is_none(),
            "decode-failure-retains-known-identity.audit_attempt_sequence.presence"
        );
    }
    {
        let value = ResponseMetadata {
            identity: RequestIdentity {
                operation_id: Some("operation-a".into()),
                ..Default::default()
            },
            outcome: OutcomeKnowledge(3),
            audit_ack: Some(AuditAck {
                status: AuditAckStatus(2),
                attempt_sequence: Some(18_446_744_073_709_551_615_u64),
            }),
            audit_status: Some("outcome-unknown".into()),
            audit_attempt_sequence: Some(18_446_744_073_709_551_615_u64),
        };
        assert!(
            value.identity.activation_id.is_none(),
            "observed-receipt-audit-outcome-independent.identity.activation_id.presence"
        );
        assert!(
            value.identity.operation_id.is_some(),
            "observed-receipt-audit-outcome-independent.identity.operation_id.presence"
        );
        assert_eq!(
            value.identity.operation_id.as_deref().unwrap(),
            "operation-a",
            "observed-receipt-audit-outcome-independent.identity.operation_id"
        );
        assert_eq!(
            value.outcome.0, 3,
            "observed-receipt-audit-outcome-independent.outcome"
        );
        assert!(
            value.audit_ack.is_some(),
            "observed-receipt-audit-outcome-independent.audit_ack.presence"
        );
        assert_eq!(
            value.audit_ack.as_ref().unwrap().status.0,
            2,
            "observed-receipt-audit-outcome-independent.audit_ack.status"
        );
        assert!(
            value.audit_ack.as_ref().unwrap().attempt_sequence.is_some(),
            "observed-receipt-audit-outcome-independent.audit_ack.attempt_sequence.presence"
        );
        assert_eq!(
            value.audit_ack.as_ref().unwrap().attempt_sequence.unwrap(),
            18_446_744_073_709_551_615_u64,
            "observed-receipt-audit-outcome-independent.audit_ack.attempt_sequence"
        );
        assert!(
            value.audit_status.is_some(),
            "observed-receipt-audit-outcome-independent.audit_status.presence"
        );
        assert_eq!(
            value.audit_status.as_deref().unwrap(),
            "outcome-unknown",
            "observed-receipt-audit-outcome-independent.audit_status"
        );
        assert!(
            value.audit_attempt_sequence.is_some(),
            "observed-receipt-audit-outcome-independent.audit_attempt_sequence.presence"
        );
        assert_eq!(
            value.audit_attempt_sequence.unwrap(),
            18_446_744_073_709_551_615_u64,
            "observed-receipt-audit-outcome-independent.audit_attempt_sequence"
        );
    }
    {
        let value = ResponseMetadata {
            identity: RequestIdentity {
                operation_id: Some("operation-a".into()),
                ..Default::default()
            },
            outcome: OutcomeKnowledge(3),
            ..Default::default()
        };
        assert!(
            value.identity.activation_id.is_none(),
            "policy-response-has-no-fabricated-audit.identity.activation_id.presence"
        );
        assert!(
            value.identity.operation_id.is_some(),
            "policy-response-has-no-fabricated-audit.identity.operation_id.presence"
        );
        assert_eq!(
            value.identity.operation_id.as_deref().unwrap(),
            "operation-a",
            "policy-response-has-no-fabricated-audit.identity.operation_id"
        );
        assert_eq!(
            value.outcome.0, 3,
            "policy-response-has-no-fabricated-audit.outcome"
        );
        assert!(
            value.audit_ack.is_none(),
            "policy-response-has-no-fabricated-audit.audit_ack.presence"
        );
        assert!(
            value.audit_status.is_none(),
            "policy-response-has-no-fabricated-audit.audit_status.presence"
        );
        assert!(
            value.audit_attempt_sequence.is_none(),
            "policy-response-has-no-fabricated-audit.audit_attempt_sequence.presence"
        );
    }
    {
        let value = ResponseMetadata {
            identity: RequestIdentity {
                operation_id: Some("operation-a".into()),
                ..Default::default()
            },
            outcome: OutcomeKnowledge(2),
            ..Default::default()
        };
        assert!(
            value.identity.activation_id.is_none(),
            "missing-recovery-keeps-outcome-unknown.identity.activation_id.presence"
        );
        assert!(
            value.identity.operation_id.is_some(),
            "missing-recovery-keeps-outcome-unknown.identity.operation_id.presence"
        );
        assert_eq!(
            value.identity.operation_id.as_deref().unwrap(),
            "operation-a",
            "missing-recovery-keeps-outcome-unknown.identity.operation_id"
        );
        assert_eq!(
            value.outcome.0, 2,
            "missing-recovery-keeps-outcome-unknown.outcome"
        );
        assert!(
            value.audit_ack.is_none(),
            "missing-recovery-keeps-outcome-unknown.audit_ack.presence"
        );
        assert!(
            value.audit_status.is_none(),
            "missing-recovery-keeps-outcome-unknown.audit_status.presence"
        );
        assert!(
            value.audit_attempt_sequence.is_none(),
            "missing-recovery-keeps-outcome-unknown.audit_attempt_sequence.presence"
        );
    }
    {
        let value = ResponseMetadata {
            identity: RequestIdentity {
                operation_id: Some("operation-a".into()),
                ..Default::default()
            },
            outcome: OutcomeKnowledge(91),
            audit_ack: Some(AuditAck {
                status: AuditAckStatus(91),
                attempt_sequence: Some(0_u64),
            }),
            audit_status: Some("future-audit-status".into()),
            audit_attempt_sequence: Some(0_u64),
        };
        assert!(
            value.identity.activation_id.is_none(),
            "unknown-audit-enum-and-status.identity.activation_id.presence"
        );
        assert!(
            value.identity.operation_id.is_some(),
            "unknown-audit-enum-and-status.identity.operation_id.presence"
        );
        assert_eq!(
            value.identity.operation_id.as_deref().unwrap(),
            "operation-a",
            "unknown-audit-enum-and-status.identity.operation_id"
        );
        assert_eq!(value.outcome.0, 91, "unknown-audit-enum-and-status.outcome");
        assert!(
            value.audit_ack.is_some(),
            "unknown-audit-enum-and-status.audit_ack.presence"
        );
        assert_eq!(
            value.audit_ack.as_ref().unwrap().status.0,
            91,
            "unknown-audit-enum-and-status.audit_ack.status"
        );
        assert!(
            value.audit_ack.as_ref().unwrap().attempt_sequence.is_some(),
            "unknown-audit-enum-and-status.audit_ack.attempt_sequence.presence"
        );
        assert_eq!(
            value.audit_ack.as_ref().unwrap().attempt_sequence.unwrap(),
            0_u64,
            "unknown-audit-enum-and-status.audit_ack.attempt_sequence"
        );
        assert!(
            value.audit_status.is_some(),
            "unknown-audit-enum-and-status.audit_status.presence"
        );
        assert_eq!(
            value.audit_status.as_deref().unwrap(),
            "future-audit-status",
            "unknown-audit-enum-and-status.audit_status"
        );
        assert!(
            value.audit_attempt_sequence.is_some(),
            "unknown-audit-enum-and-status.audit_attempt_sequence.presence"
        );
        assert_eq!(
            value.audit_attempt_sequence.unwrap(),
            0_u64,
            "unknown-audit-enum-and-status.audit_attempt_sequence"
        );
    }
    {
        let value = ResponseMetadata {
            identity: RequestIdentity {
                operation_id: Some("operation-a".into()),
                ..Default::default()
            },
            outcome: OutcomeKnowledge(3),
            audit_status: Some("future-state".into()),
            audit_attempt_sequence: Some(18_446_744_073_709_551_615_u64),
            ..Default::default()
        };
        assert!(
            value.identity.activation_id.is_none(),
            "unknown-audit-header-and-max-attempt.identity.activation_id.presence"
        );
        assert!(
            value.identity.operation_id.is_some(),
            "unknown-audit-header-and-max-attempt.identity.operation_id.presence"
        );
        assert_eq!(
            value.identity.operation_id.as_deref().unwrap(),
            "operation-a",
            "unknown-audit-header-and-max-attempt.identity.operation_id"
        );
        assert_eq!(
            value.outcome.0, 3,
            "unknown-audit-header-and-max-attempt.outcome"
        );
        assert!(
            value.audit_ack.is_none(),
            "unknown-audit-header-and-max-attempt.audit_ack.presence"
        );
        assert!(
            value.audit_status.is_some(),
            "unknown-audit-header-and-max-attempt.audit_status.presence"
        );
        assert_eq!(
            value.audit_status.as_deref().unwrap(),
            "future-state",
            "unknown-audit-header-and-max-attempt.audit_status"
        );
        assert!(
            value.audit_attempt_sequence.is_some(),
            "unknown-audit-header-and-max-attempt.audit_attempt_sequence.presence"
        );
        assert_eq!(
            value.audit_attempt_sequence.unwrap(),
            18_446_744_073_709_551_615_u64,
            "unknown-audit-header-and-max-attempt.audit_attempt_sequence"
        );
    }
    {
        let value = ClientFailure {
            category: FailureCategory(4),
            message: "rpc-failure".into(),
            grpc_status: Some(13_i32),
            dispatched: true,
            outcome: OutcomeKnowledge(2),
            identity: RequestIdentity {
                operation_id: Some("operation-a".into()),
                ..Default::default()
            },
            audit_status: Some("future-state".into()),
            audit_attempt_sequence: Some(18_446_744_073_709_551_615_u64),
            ..Default::default()
        };
        assert_eq!(
            value.category.0, 4,
            "failed-rpc-unknown-audit-header-and-max-attempt.category"
        );
        assert_eq!(
            value.message, "rpc-failure",
            "failed-rpc-unknown-audit-header-and-max-attempt.message"
        );
        assert!(
            value.grpc_status.is_some(),
            "failed-rpc-unknown-audit-header-and-max-attempt.grpc_status.presence"
        );
        assert_eq!(
            value.grpc_status.unwrap(),
            13_i32,
            "failed-rpc-unknown-audit-header-and-max-attempt.grpc_status"
        );
        assert!(
            value.platform_error.is_none(),
            "failed-rpc-unknown-audit-header-and-max-attempt.platform_error.presence"
        );
        assert!(
            value.dispatched,
            "failed-rpc-unknown-audit-header-and-max-attempt.dispatched"
        );
        assert_eq!(
            value.outcome.0, 2,
            "failed-rpc-unknown-audit-header-and-max-attempt.outcome"
        );
        assert!(
            value.identity.activation_id.is_none(),
            "failed-rpc-unknown-audit-header-and-max-attempt.identity.activation_id.presence"
        );
        assert!(
            value.identity.operation_id.is_some(),
            "failed-rpc-unknown-audit-header-and-max-attempt.identity.operation_id.presence"
        );
        assert_eq!(
            value.identity.operation_id.as_deref().unwrap(),
            "operation-a",
            "failed-rpc-unknown-audit-header-and-max-attempt.identity.operation_id"
        );
        assert!(
            value.audit_ack.is_none(),
            "failed-rpc-unknown-audit-header-and-max-attempt.audit_ack.presence"
        );
        assert!(
            value.audit_status.is_some(),
            "failed-rpc-unknown-audit-header-and-max-attempt.audit_status.presence"
        );
        assert_eq!(
            value.audit_status.as_deref().unwrap(),
            "future-state",
            "failed-rpc-unknown-audit-header-and-max-attempt.audit_status"
        );
        assert!(
            value.unsupported_wire_value.is_none(),
            "failed-rpc-unknown-audit-header-and-max-attempt.unsupported_wire_value.presence"
        );
        assert!(
            value.audit_attempt_sequence.is_some(),
            "failed-rpc-unknown-audit-header-and-max-attempt.audit_attempt_sequence.presence"
        );
        assert_eq!(
            value.audit_attempt_sequence.unwrap(),
            18_446_744_073_709_551_615_u64,
            "failed-rpc-unknown-audit-header-and-max-attempt.audit_attempt_sequence"
        );
    }
    {
        let value = AuditAck {
            status: AuditAckStatus(1),
            ..Default::default()
        };
        assert_eq!(value.status.0, 1, "audit-durable-attempt-absent.status");
        assert!(
            value.attempt_sequence.is_none(),
            "audit-durable-attempt-absent.attempt_sequence.presence"
        );
    }
    {
        let value = AuditAck {
            status: AuditAckStatus(3),
            attempt_sequence: Some(0_u64),
        };
        assert_eq!(value.status.0, 3, "audit-unavailable-attempt-zero.status");
        assert!(
            value.attempt_sequence.is_some(),
            "audit-unavailable-attempt-zero.attempt_sequence.presence"
        );
        assert_eq!(
            value.attempt_sequence.unwrap(),
            0_u64,
            "audit-unavailable-attempt-zero.attempt_sequence"
        );
    }
    {
        let value = AuditAck {
            status: AuditAckStatus(4),
            ..Default::default()
        };
        assert_eq!(
            value.status.0, 4,
            "audit-disabled-distinct-from-absence.status"
        );
        assert!(
            value.attempt_sequence.is_none(),
            "audit-disabled-distinct-from-absence.attempt_sequence.presence"
        );
    }
    {
        let value = ReleaseSelector {
            ..Default::default()
        };
        assert!(
            value.component_digest.is_none(),
            "selector-absent-not-fallback.component_digest.presence"
        );
        assert!(
            value.publication.is_none(),
            "selector-absent-not-fallback.publication.presence"
        );
    }
    {
        let value = ReleaseSelector {
            publication: Some(PublicationRef {
                id: String::new(),
                tenant: "tenant-a".into(),
            }),
            ..Default::default()
        };
        assert!(
            value.component_digest.is_none(),
            "selector-invalid-present-not-absent.component_digest.presence"
        );
        assert!(
            value.publication.is_some(),
            "selector-invalid-present-not-absent.publication.presence"
        );
        assert_eq!(
            value.publication.as_ref().unwrap().id,
            "",
            "selector-invalid-present-not-absent.publication.id"
        );
        assert_eq!(
            value.publication.as_ref().unwrap().tenant,
            "tenant-a",
            "selector-invalid-present-not-absent.publication.tenant"
        );
    }
    {
        let value = ReleaseSelector{component_digest: Some("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into()), publication: Some(PublicationRef{id: "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111".into(), tenant: "tenant-a".into()})};
        assert!(
            value.component_digest.is_some(),
            "selector-ambiguous-not-auto-selected.component_digest.presence"
        );
        assert_eq!(
            value.component_digest.as_deref().unwrap(),
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "selector-ambiguous-not-auto-selected.component_digest"
        );
        assert!(
            value.publication.is_some(),
            "selector-ambiguous-not-auto-selected.publication.presence"
        );
        assert_eq!(
            value.publication.as_ref().unwrap().id,
            "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111",
            "selector-ambiguous-not-auto-selected.publication.id"
        );
        assert_eq!(
            value.publication.as_ref().unwrap().tenant,
            "tenant-a",
            "selector-ambiguous-not-auto-selected.publication.tenant"
        );
    }
    {
        let value = PublicationIdentity{publication: PublicationRef{id: "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111".into(), tenant: "tenant-a".into()}, component_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(), package_digest: "sha256:1111111111111111111111111111111111111111111111111111111111111111".into()};
        assert_eq!(
            value.publication.id,
            "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111",
            "publication-original-package.publication.id"
        );
        assert_eq!(
            value.publication.tenant, "tenant-a",
            "publication-original-package.publication.tenant"
        );
        assert_eq!(
            value.component_digest,
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "publication-original-package.component_digest"
        );
        assert_eq!(
            value.package_digest,
            "sha256:1111111111111111111111111111111111111111111111111111111111111111",
            "publication-original-package.package_digest"
        );
    }
    {
        let value = PublicationIdentity{publication: PublicationRef{id: "publication:sha256:2222222222222222222222222222222222222222222222222222222222222222".into(), tenant: "tenant-a".into()}, component_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(), package_digest: "sha256:2222222222222222222222222222222222222222222222222222222222222222".into()};
        assert_eq!(
            value.publication.id,
            "publication:sha256:2222222222222222222222222222222222222222222222222222222222222222",
            "publication-corrected-package-same-component.publication.id"
        );
        assert_eq!(
            value.publication.tenant, "tenant-a",
            "publication-corrected-package-same-component.publication.tenant"
        );
        assert_eq!(
            value.component_digest,
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "publication-corrected-package-same-component.component_digest"
        );
        assert_eq!(
            value.package_digest,
            "sha256:2222222222222222222222222222222222222222222222222222222222222222",
            "publication-corrected-package-same-component.package_digest"
        );
    }
    {
        let value = PublicationIdentity{publication: PublicationRef{id: "publication:sha256:3333333333333333333333333333333333333333333333333333333333333333".into(), tenant: "tenant-b".into()}, component_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(), package_digest: "sha256:2222222222222222222222222222222222222222222222222222222222222222".into()};
        assert_eq!(
            value.publication.id,
            "publication:sha256:3333333333333333333333333333333333333333333333333333333333333333",
            "publication-other-tenant-same-package.publication.id"
        );
        assert_eq!(
            value.publication.tenant, "tenant-b",
            "publication-other-tenant-same-package.publication.tenant"
        );
        assert_eq!(
            value.component_digest,
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "publication-other-tenant-same-package.component_digest"
        );
        assert_eq!(
            value.package_digest,
            "sha256:2222222222222222222222222222222222222222222222222222222222222222",
            "publication-other-tenant-same-package.package_digest"
        );
    }
    assert!(parse_u64_decimal("0").is_some(), "uint64 decimal");
    assert_eq!(
        parse_u64_decimal("0").unwrap().to_string(),
        "0",
        "uint64 roundtrip"
    );
    assert!(
        parse_u64_decimal("9007199254740993").is_some(),
        "uint64 decimal"
    );
    assert_eq!(
        parse_u64_decimal("9007199254740993").unwrap().to_string(),
        "9007199254740993",
        "uint64 roundtrip"
    );
    assert!(
        parse_u64_decimal("9223372036854775808").is_some(),
        "uint64 decimal"
    );
    assert_eq!(
        parse_u64_decimal("9223372036854775808")
            .unwrap()
            .to_string(),
        "9223372036854775808",
        "uint64 roundtrip"
    );
    assert!(
        parse_u64_decimal("18446744073709551615").is_some(),
        "uint64 decimal"
    );
    assert_eq!(
        parse_u64_decimal("18446744073709551615")
            .unwrap()
            .to_string(),
        "18446744073709551615",
        "uint64 roundtrip"
    );
    assert!(
        parse_u64_decimal("18446744073709551616").is_none(),
        "uint64 decimal"
    );
    assert!(parse_u64_decimal("-1").is_none(), "uint64 decimal");
    assert!(parse_u64_decimal("+1").is_none(), "uint64 decimal");
    assert!(parse_u64_decimal("01").is_none(), "uint64 decimal");
    assert!(parse_u64_decimal(" 1").is_none(), "uint64 decimal");
    assert!(parse_u64_decimal("1 ").is_none(), "uint64 decimal");
    assert!(parse_u64_decimal("1.0").is_none(), "uint64 decimal");
    assert!(parse_u64_decimal("1e3").is_none(), "uint64 decimal");
    assert!(parse_u64_decimal("").is_none(), "uint64 decimal");
    assert!(parse_u64_decimal("1\u{0000}").is_none(), "uint64 decimal");
    assert!(parse_u64_decimal("1\n").is_none(), "uint64 decimal");
    assert!(parse_u64_decimal("1\r\n").is_none(), "uint64 decimal");
}
