use super::*;
use latent_activation::{ActivationEnvelope, TraceContext};
use latent_core::{
    ActivationBudget, ActivationId, BudgetProfile, ClockSample, ContractId,
    EffectiveActivationBudget, FunctionId, ResourceBudget, RevisionId, RouteGeneration, ServiceId,
    SpanId, TenantId, TraceId,
};
use latent_routing::{InvocationTarget, ResolvedRevision};
use std::sync::atomic::{AtomicU64, Ordering};
static ACTIVATIONS: AtomicU64 = AtomicU64::new(1);

pub(in crate::transaction_runtime) struct Call {
    pub admission: Arc<CommandAdmission>,
    pub envelope: ActivationEnvelope,
    pub budget: ActivationBudget,
    pub registration: crate::CancellationRegistration,
    transport: std::sync::Mutex<Option<crate::activation_manager::TestTransactionTransport>>,
}
impl Call {
    pub fn interrupt_transport(&self, cause: crate::ActivationTransportInterruption) {
        self.transport
            .lock()
            .unwrap()
            .take()
            .unwrap()
            .interrupt(cause);
    }
    pub async fn admit(&self) -> TransactionAdmission {
        self.admission
            .preflight(&self.envelope, &self.budget)
            .await
            .unwrap();
        self.admission
            .admit(&self.envelope, &self.budget)
            .await
            .unwrap()
    }
    pub fn waiting(
        &self,
    ) -> tokio::task::JoinHandle<Result<TransactionAdmission, latent_core::PlatformError>> {
        let admission = Arc::clone(&self.admission);
        let envelope = self.envelope.clone();
        let budget = self.budget.clone();
        tokio::spawn(async move {
            admission.preflight(&envelope, &budget).await?;
            admission.admit(&envelope, &budget).await
        })
    }
}

impl Fixture {
    pub fn call(&self, client_key: &str, entity: &str) -> Call {
        let resources = ResourceBudget {
            cpu_fuel: 1_000_000,
            memory_bytes: 64 * 1024 * 1024,
            wall_time_limit_millis: Some(10_000),
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 4 * 1024 * 1024,
            state_write_bytes: 2 * 1024 * 1024,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 16 * 1024,
            effect_count: 32,
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
        let target = InvocationTarget {
            tenant: TenantId("a".into()),
            service: ServiceId("a/echo".into()),
            contract: ContractId("a:echo/api@0.1.0".into()),
            function: FunctionId("update".into()),
            route: None,
        };
        let activation = ActivationId(format!(
            "installed-entity-{}",
            ACTIVATIONS.fetch_add(1, Ordering::Relaxed)
        ));
        let registration = self.cancellations.register(activation.clone()).unwrap();
        let envelope = ActivationEnvelope {
            activation_id: activation.clone(),
            parent_activation_id: None,
            root_activation_id: activation,
            principal: factory::principal(),
            target: target.clone(),
            resolved_revision: Some(ResolvedRevision {
                target,
                revision: RevisionId("revision".into()),
                release: self.owners.publication.release().clone(),
                publication: Some(self.owners.publication.publication().clone()),
                route_generation: RouteGeneration(1),
                attributes: Metadata::new(),
            }),
            deadline_unix_millis: None,
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId("installed-trace".into()),
                span_id: SpanId("installed-span".into()),
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
        let time = Arc::new(time::Time::new(
            self.owners.source.clone(),
            self.native.clone(),
        ));
        let coordinator = CommandCoordinator::new_with_entity_lanes(
            Arc::clone(&self.owners.store),
            self.waiters.clone(),
            Some(self.owners.source.effect_authority()),
            time.clone(),
            Arc::clone(&self.lanes),
        )
        .unwrap();
        let admission = coordinator.admission(Arc::new(factory::Factory {
            owners: Arc::clone(&self.owners),
            time,
            client_key: client_key.into(),
            entity: entity.into(),
        }));
        let (control, transport) =
            crate::TransactionAdmissionControl::for_registered_test_with_transport(
                &registration,
                &budget,
            );
        admission.bind_control(control).unwrap();
        Call {
            admission,
            envelope,
            budget,
            registration,
            transport: std::sync::Mutex::new(Some(transport)),
        }
    }
}
