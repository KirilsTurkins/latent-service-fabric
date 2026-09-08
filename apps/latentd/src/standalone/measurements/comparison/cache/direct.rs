use std::time::{SystemTime, UNIX_EPOCH};

use latent_activation::ActivationEnvelope;
use latent_core::{
    ActivationId, CapabilityId, CellId, ContractId, FunctionId, InvocationPrincipal,
    InvocationTarget, Metadata, PrincipalKind, ResourceBudget, ServiceId, SpanId, TenantId,
    TraceContext, TraceId,
};
use latent_executor::{
    BoundImport, ExecutionBackend, ExecutionCancellation, ExecutionCell, ExecutionCleanup,
    ExecutionRequest, GuestOutcome, PreparedActivation,
};
use latent_wasmtime::WasmtimeBackend;
use serde_json::{json, Value};

use super::{cold, Result, Writer};

struct Control(ActivationId);
impl ExecutionCancellation for Control {
    fn activation_id(&self) -> &ActivationId {
        &self.0
    }
    fn is_cancelled(&self) -> bool {
        false
    }
    fn reason(&self) -> Option<String> {
        None
    }
}

pub(super) async fn execute(
    backend: &WasmtimeBackend,
    active: PreparedActivation,
    writer: &mut Writer,
    clock: cold::call::Clock,
) -> Result<()> {
    let id = ActivationId("cache-held-direct".into());
    let descriptor = active.prepared.descriptor().clone();
    let request = request(&id, &active)?;
    let started = clock.elapsed();
    let report = backend
        .invoke_prepared_contained(request, active.prepared, &Control(id.clone()))
        .await;
    let finished = clock.elapsed();
    let reusable = report.cleanup == ExecutionCleanup::Reusable;
    let (outcome, response, valid) = match report.outcome {
        Ok(GuestOutcome::Returned {
            output,
            output_media_type,
            consumption,
        }) => {
            let valid = output_media_type == super::super::super::fixtures::MEDIA
                && serde_json::from_slice::<Value>(&output).ok()
                    == Some(json!([{"ok":super::super::INPUT}]));
            (
                "success",
                json!({"payload_sha256":latent_artifacts::content_digest(&output).0,
                "payload_bytes":output.len().to_string(),"media_type":output_media_type,
                "consumption":cold::call::consumption(Some(&latent_wire::invocation::consumption_to_proto(&consumption)))}),
                valid,
            )
        }
        Ok(GuestOutcome::DeclaredError { .. }) => ("declared-error", Value::Null, false),
        Ok(GuestOutcome::Trapped { .. }) => ("trap", Value::Null, false),
        Ok(GuestOutcome::Interrupted { kind, .. }) => {
            ("interrupted", json!({"kind":format!("{kind:?}")}), false)
        }
        Err(error) => (
            "platform-failure",
            json!({"code":format!("{:?}",error.code)}),
            false,
        ),
    };
    writer.sample(&json!({"kind":"direct-execution","activation_id":id.0,
        "release_digest":descriptor.key.release.0,"prepared_handle":descriptor.opaque_handle,
        "started_nanos":started.to_string(),"finished_nanos":finished.to_string(),
        "outcome":outcome,"response":response,"cleanup_reusable":reusable,
        "backend_timing":backend.take_invocation_timing(&id).map(super::super::evidence::timing)}))?;
    if !valid || !reusable {
        return Err("held direct execution failed".into());
    }
    Ok(())
}

fn request(id: &ActivationId, active: &PreparedActivation) -> Result<ExecutionRequest> {
    let budget = ResourceBudget {
        cpu_fuel: 10_000_000_000,
        memory_bytes: 16_777_216,
        wall_time_limit_millis: Some(1000),
        log_bytes: 16384,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        effect_count: 0,
    };
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let imports = active
        .imports
        .iter()
        .map(|contract| BoundImport {
            capability: CapabilityId(contract.0.clone()),
            contract: contract.0.clone(),
            opaque_handle: id.0.clone(),
        })
        .collect();
    Ok(ExecutionRequest {
        activation: ActivationEnvelope {
            activation_id: id.clone(),
            root_activation_id: id.clone(),
            parent_activation_id: None,
            principal: InvocationPrincipal {
                subject: "comparison-examples".into(),
                kind: PrincipalKind::Administrator,
                tenant: Some(TenantId("examples".into())),
                service: None,
                claims: Metadata::new(),
            },
            target: InvocationTarget {
                tenant: TenantId("examples".into()),
                service: ServiceId("cold-key-0".into()),
                contract: ContractId("examples:echo/api@0.1.0".into()),
                function: FunctionId("echo".into()),
                route: None,
            },
            resolved_revision: None,
            deadline_unix_millis: Some(now.checked_add(1000).ok_or("direct deadline overflow")?),
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId("11111111111111111111111111111111".into()),
                span_id: SpanId("1111111111111111".into()),
                trace_flags: 1,
                baggage: Metadata::new(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: budget.clone(),
            metadata: Metadata::new(),
            input: serde_json::to_vec(&json!([super::super::INPUT]))?,
            input_media_type: super::super::super::fixtures::MEDIA.into(),
        },
        prepared: active.prepared.descriptor().clone(),
        cell: ExecutionCell {
            id: CellId("cache-direct-cell".into()),
            class: "standard".into(),
            maximum_memory_bytes: budget.memory_bytes,
            metadata: Metadata::new(),
        },
        imports,
        budget,
    })
}
