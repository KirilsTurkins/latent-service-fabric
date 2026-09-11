use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use latent_activation::{ActivationEnvelope, TraceContext};
use latent_core::{
    ActivationBudget, ActivationClock, ActivationId, CapabilityId, CellId, ContractId,
    EffectiveActivationBudget, FunctionId, InvocationPrincipal, Metadata, PrincipalKind, ServiceId,
    SpanId, SystemActivationClock, TenantId, TraceId,
};
use latent_executor::{
    BoundImport, ExecutionCancellation, ExecutionCancellationProbe, ExecutionCell,
    ExecutionRequest, PreparedComponent,
};
use latent_routing::InvocationTarget;

use super::{config, context::Context, Result};

pub(super) struct Control {
    pub id: ActivationId,
    pub ledger: ActivationBudget,
    stop: Arc<Stop>,
}
struct Stop(AtomicBool);
impl ExecutionCancellationProbe for Stop {
    fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }
    fn reason(&self) -> Option<String> {
        self.is_cancelled()
            .then(|| "ownership proof cancellation".into())
    }
}
impl Control {
    pub fn new(id: ActivationId) -> Result<Self> {
        let grant = config::budget();
        let effective = EffectiveActivationBudget::admit_at(
            &grant,
            &grant,
            &grant,
            None,
            SystemActivationClock.sample(),
        )?;
        Ok(Self {
            id,
            ledger: ActivationBudget::new(effective),
            stop: Arc::new(Stop(AtomicBool::new(false))),
        })
    }
    pub fn cancel(&self) {
        self.stop.0.store(true, Ordering::Release);
    }
}
impl ExecutionCancellation for Control {
    fn activation_id(&self) -> &ActivationId {
        &self.id
    }
    fn is_cancelled(&self) -> bool {
        self.stop.is_cancelled()
    }
    fn reason(&self) -> Option<String> {
        self.stop.reason()
    }
    fn budget_accounting(&self) -> Option<&ActivationBudget> {
        Some(&self.ledger)
    }
    fn probe(&self) -> Option<Arc<dyn ExecutionCancellationProbe>> {
        Some(self.stop.clone())
    }
}

pub(super) fn identifier(ordinal: u32) -> ActivationId {
    ActivationId(format!("ownership-invocation-{ordinal:012}"))
}

pub(super) struct Template {
    pub fixture: String,
    pub tenant: String,
    pub service: String,
    pub contract: String,
    pub imports: Vec<String>,
    pub prepared: PreparedComponent,
}

pub(super) fn build(
    template: &Template,
    context: &Context,
    payload: &[u8],
    control: &Control,
    function: &str,
) -> ExecutionRequest {
    let mut metadata = context.metadata.clone();
    metadata.insert("guest.visible".into(), control.id.0.clone());
    let budget = control.ledger.granted().clone();
    ExecutionRequest {
        activation: ActivationEnvelope {
            activation_id: control.id.clone(),
            root_activation_id: control.id.clone(),
            parent_activation_id: Some(control.id.clone()),
            principal: InvocationPrincipal {
                subject: control.id.0.clone(),
                kind: PrincipalKind::Service,
                tenant: Some(TenantId(template.tenant.clone())),
                service: Some(ServiceId("ownership-caller".into())),
                claims: context.claims.clone(),
            },
            target: InvocationTarget {
                tenant: TenantId(template.tenant.clone()),
                service: ServiceId(template.service.clone()),
                contract: ContractId(template.contract.clone()),
                function: FunctionId(function.into()),
                route: None,
            },
            resolved_revision: None,
            deadline_unix_millis: control.ledger.deadline().unix_millis(),
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId("11111111111111111111111111111111".into()),
                span_id: SpanId("1111111111111111".into()),
                trace_flags: 1,
                baggage: context.baggage.clone(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: budget.clone(),
            metadata,
            input: payload.to_vec(),
            input_media_type: super::MEDIA.into(),
        },
        prepared: template.prepared.clone(),
        cell: ExecutionCell {
            id: CellId("ownership-direct-cell".into()),
            class: "standard".into(),
            maximum_memory_bytes: budget.memory_bytes,
            metadata: Metadata::new(),
        },
        imports: template
            .imports
            .iter()
            .map(|contract| BoundImport {
                capability: CapabilityId(contract.clone()),
                contract: contract.clone(),
                opaque_handle: control.id.0.clone(),
            })
            .collect(),
        budget,
    }
}
