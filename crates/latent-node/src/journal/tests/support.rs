use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use latent_activation::{ActivationEnvelope, ActivationOutcome, ActivationSuccess, TraceContext};
use latent_core::{
    ActivationClock, ActivationId, BudgetConsumption, ClockSample, ContractId, FunctionId,
    InvocationPrincipal, Metadata, PrincipalKind, ResourceBudget, ServiceId, SpanId, TenantId,
    TraceId,
};
use latent_routing::InvocationTarget;

use super::super::{LocalActivationJournal, LocalActivationJournalConfig};

pub(super) struct Clock(Mutex<ClockSample>);
impl Clock {
    pub fn new() -> Self {
        Self(Mutex::new(ClockSample::new(1000, Instant::now())))
    }
    pub fn elapse(&self, duration: Duration) {
        let mut current = self.0.lock().expect("clock");
        *current = ClockSample::new(current.unix_millis(), current.monotonic() + duration);
    }
    pub fn wall(&self, unix: u64) {
        let mut current = self.0.lock().expect("clock");
        *current = ClockSample::new(unix, current.monotonic());
    }
}
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        *self.0.lock().expect("clock")
    }
    fn monotonic_now(&self) -> Instant {
        self.sample().monotonic()
    }
}

pub(super) fn journal(active: usize, terminal: usize) -> (LocalActivationJournal, Arc<Clock>) {
    let clock = Arc::new(Clock::new());
    let config = LocalActivationJournalConfig {
        maximum_active: active,
        maximum_terminal: terminal,
        maximum_record_bytes: 64 * 1024,
        maximum_retained_bytes: 1024 * 1024,
        terminal_retention: Duration::from_secs(1),
    };
    (
        LocalActivationJournal::new(config, clock.clone()).expect("journal"),
        clock,
    )
}

pub(super) fn outcome() -> ActivationOutcome {
    ActivationOutcome::Succeeded(ActivationSuccess {
        output: b"done".to_vec(),
        output_media_type: "test".to_owned(),
        consumption: BudgetConsumption::default(),
        committed_state_version: None,
        effect_ids: Vec::new(),
        metadata: Metadata::new(),
    })
}

pub(super) fn envelope(id: &str) -> ActivationEnvelope {
    ActivationEnvelope {
        activation_id: ActivationId(id.to_owned()),
        parent_activation_id: None,
        root_activation_id: ActivationId(id.to_owned()),
        principal: InvocationPrincipal {
            subject: "caller".to_owned(),
            kind: PrincipalKind::User,
            tenant: Some(TenantId("tenant".to_owned())),
            service: None,
            claims: Metadata::new(),
        },
        target: InvocationTarget {
            tenant: TenantId("tenant".to_owned()),
            service: ServiceId("service".to_owned()),
            contract: ContractId("example:values/api@0.1.0".to_owned()),
            function: FunctionId("call".to_owned()),
            route: None,
        },
        resolved_revision: None,
        deadline_unix_millis: None,
        priority: 0,
        trace: TraceContext {
            trace_id: TraceId("trace".to_owned()),
            span_id: SpanId("span".to_owned()),
            trace_flags: 1,
            baggage: Metadata::new(),
        },
        idempotency_key: None,
        retry_attempt: 0,
        budget: ResourceBudget {
            cpu_fuel: 100,
            memory_bytes: 1024,
            wall_time_limit_millis: Some(50),
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 100,
            effect_count: 0,
        },
        metadata: Metadata::new(),
        input: Vec::new(),
        input_media_type: "application/json".to_owned(),
    }
}
