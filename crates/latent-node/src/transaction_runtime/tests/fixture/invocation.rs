use super::*;
use latent_activation::{ActivationEnvelope, TraceContext};
use latent_core::{
    ActivationBudget, ActivationId, BudgetProfile, ClockSample, ContractId,
    EffectiveActivationBudget, FunctionId, ResourceBudget, RevisionId, RouteGeneration, ServiceId,
    SpanId, TenantId, TraceId,
};
use latent_manifest::TransactionOperationMode;
use latent_routing::{InvocationTarget, ResolvedRevision};
use std::sync::atomic::{AtomicU64, Ordering};
static ACTIVATIONS: AtomicU64 = AtomicU64::new(1);
struct Cancellation {
    token: crate::CancellationToken,
    terminal: tokio::sync::watch::Sender<bool>,
}
impl latent_core::BudgetCancellationProbe for Cancellation {
    fn is_cancelled(&self) -> bool {
        self.token.is_cancelled()
    }
    fn cancelled(&self) -> latent_core::BoxFuture<'_, ()> {
        Box::pin(async move {
            let mut terminal = self.terminal.subscribe();
            tokio::select! { () = self.token.cancelled() => {}, _ = terminal.changed() => {} }
        })
    }
    fn mark_terminal(&self) {
        self.terminal.send_replace(true);
    }
}

impl Fixture {
    pub fn invocation(
        &self,
        query: bool,
        key: &str,
    ) -> (
        Arc<NativeTransactionAdmission>,
        ActivationEnvelope,
        ActivationBudget,
    ) {
        let resources = ResourceBudget {
            cpu_fuel: 1_000_000,
            memory_bytes: 64 * 1024 * 1024,
            wall_time_limit_millis: Some(10_000),
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 4 * 1024 * 1024,
            state_write_bytes: if query { 0 } else { 2 * 1024 * 1024 },
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 16 * 1024,
            effect_count: if query { 0 } else { 32 },
        };
        let grant = EffectiveActivationBudget::admit_profile_at(
            BudgetProfile::Phase4,
            &resources,
            &resources,
            &resources,
            None,
            ClockSample::system_now(),
        )
        .unwrap();
        let budget = ActivationBudget::with_profile(grant, BudgetProfile::Phase4).unwrap();
        let function = if query { "query" } else { "update" };
        let target = InvocationTarget {
            tenant: TenantId("a".into()),
            service: ServiceId("a/echo".into()),
            contract: ContractId("a:echo/api@0.1.0".into()),
            function: FunctionId(function.into()),
            route: None,
        };
        let activation = ActivationId(format!(
            "native-{}",
            ACTIVATIONS.fetch_add(1, Ordering::Relaxed)
        ));
        let registration = self.cancellations.register(activation.clone()).unwrap();
        let cancellation = Cancellation {
            token: registration.token(),
            terminal: tokio::sync::watch::channel(false).0,
        };
        budget
            .enable_descendants(
                latent_core::DelegationLimits::default(),
                Arc::new(cancellation),
            )
            .unwrap();
        self.registrations.lock().unwrap().push(registration);
        let envelope = ActivationEnvelope {
            activation_id: activation.clone(),
            parent_activation_id: None,
            root_activation_id: activation,
            principal: policy::principal(),
            target: target.clone(),
            resolved_revision: Some(ResolvedRevision {
                target,
                revision: RevisionId("revision".into()),
                release: self.publication.release().clone(),
                publication: Some(self.publication.publication().clone()),
                route_generation: RouteGeneration(1),
                attributes: Metadata::new(),
            }),
            deadline_unix_millis: None,
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId("native-trace".into()),
                span_id: SpanId("native-span".into()),
                trace_flags: 0,
                baggage: Metadata::new(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: resources,
            metadata: Metadata::new(),
            input: b"same".to_vec(),
            input_media_type: "application/octet-stream".into(),
        };
        let admission = NativeTransactionAdmission::new(
            Arc::clone(&self.owners),
            Arc::clone(&self.installation),
            TransactionSelection {
                namespace: "orders".into(),
                incarnation: 1,
                entity: None,
                operation: function.into(),
                mode: if query {
                    TransactionOperationMode::FreshQuery
                } else {
                    TransactionOperationMode::StrictCommand
                },
                client_key: (!query).then(|| key.into()),
                expected_versions: Vec::new(),
                minimum_view_version: None,
                input_format: "raw-v1".into(),
                retry: None,
            },
        )
        .unwrap();
        (Arc::new(admission), envelope, budget)
    }
}
