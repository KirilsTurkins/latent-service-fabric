use std::collections::VecDeque;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

use latent_activation::{
    ActivationEnvelope, ActivationManager, ActivationOutcome, ActivationSuccess, TraceContext,
};
use latent_artifacts::CapsuleArtifact;
use latent_core::{
    ActivationId, BoxFuture, BudgetConsumption, CancelDisposition, ContractId, FunctionId,
    InvocationPrincipal, Metadata, PlatformError, PlatformErrorCode, PrincipalKind, ResourceBudget,
    ServiceId, SpanId, TenantId, TraceId,
};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionRequest, GuestOutcome, PreparationKey,
    PreparedComponent,
};
use latent_routing::InvocationTarget;

pub(super) struct Backend;
impl ExecutionBackend for Backend {
    fn backend_id(&self) -> &'static str {
        "harness-test-backend"
    }
    fn prepare<'a>(
        &'a self,
        _: &'a CapsuleArtifact,
        _: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        Box::pin(async {
            Err(super::super::error(
                PlatformErrorCode::IncompatibleContract,
                "unused-test-backend",
            ))
        })
    }
    fn invoke<'a>(
        &'a self,
        _: ExecutionRequest,
        _: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        Box::pin(async {
            Err(super::super::error(
                PlatformErrorCode::IncompatibleContract,
                "unused-test-backend",
            ))
        })
    }
    fn release(&self, _: PreparedComponent) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(async { Ok(()) })
    }
}

pub(super) struct Manager {
    pub calls: AtomicUsize,
    pub outcomes: Mutex<VecDeque<ActivationOutcome>>,
}
impl Manager {
    pub fn new(outcomes: impl IntoIterator<Item = ActivationOutcome>) -> Self {
        Self {
            calls: AtomicUsize::new(0),
            outcomes: Mutex::new(outcomes.into_iter().collect()),
        }
    }
}
impl ActivationManager for Manager {
    fn invoke(&self, _: ActivationEnvelope) -> BoxFuture<'_, ActivationOutcome> {
        self.calls.fetch_add(1, Ordering::Relaxed);
        let outcome = self
            .outcomes
            .lock()
            .unwrap()
            .pop_front()
            .expect("one bounded expected invocation");
        Box::pin(std::future::ready(outcome))
    }
    fn cancel<'a>(
        &'a self,
        _: &'a ActivationId,
        _: &'a str,
    ) -> BoxFuture<'a, Result<CancelDisposition, PlatformError>> {
        panic!("unscoped cancellation must never be called")
    }
}

pub(crate) fn envelope() -> ActivationEnvelope {
    ActivationEnvelope {
        activation_id: ActivationId("harness-activation".to_owned()),
        root_activation_id: ActivationId("harness-activation".to_owned()),
        parent_activation_id: None,
        principal: InvocationPrincipal {
            subject: "alice".to_owned(),
            kind: PrincipalKind::User,
            tenant: Some(TenantId("acme".to_owned())),
            service: None,
            claims: Metadata::new(),
        },
        target: InvocationTarget {
            tenant: TenantId("acme".to_owned()),
            service: ServiceId("echo".to_owned()),
            contract: ContractId("tests:echo/api@0.1.0".to_owned()),
            function: FunctionId("echo".to_owned()),
            route: None,
        },
        resolved_revision: None,
        deadline_unix_millis: None,
        priority: 0,
        trace: TraceContext {
            trace_id: TraceId("trace".to_owned()),
            span_id: SpanId("span".to_owned()),
            trace_flags: 0,
            baggage: Metadata::new(),
        },
        idempotency_key: None,
        retry_attempt: 0,
        budget: ResourceBudget {
            cpu_fuel: 10_000,
            memory_bytes: 1024 * 1024,
            wall_time_limit_millis: Some(100),
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 1024,
            effect_count: 0,
        },
        metadata: Metadata::new(),
        input: b"hello".to_vec(),
        input_media_type: "text/plain".to_owned(),
    }
}

pub(super) fn success(bytes: &[u8]) -> ActivationOutcome {
    ActivationOutcome::Succeeded(ActivationSuccess {
        output: bytes.to_vec(),
        output_media_type: "text/plain".to_owned(),
        consumption: BudgetConsumption {
            cpu_fuel: 17,
            ..BudgetConsumption::default()
        },
        committed_state_version: None,
        effect_ids: Vec::new(),
        metadata: Metadata::new(),
    })
}
