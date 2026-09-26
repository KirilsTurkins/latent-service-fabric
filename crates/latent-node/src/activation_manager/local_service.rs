use super::{
    control::{error, CatchPanic},
    failure_for_platform_error,
    probes::ActivationControl,
    ActivationHandle, ActivationReceipt, ActivationTransportInterruption, BudgetConsumption, Inner,
    Lifecycle, LocalActivationManager, TransportStop,
};
use latent_activation::{ActivationRequest, TraceContext};
use latent_capabilities::broker::{
    LocalServiceCompletion, LocalServiceInvocation, LocalServiceInvoker, LocalServiceRequest,
    ProviderCall,
};
use latent_core::{
    ActivationPhase, BudgetProfile, ChildBudgetDelegation, ChildBudgetOwner, IncomingDeadline,
    Metadata, PlatformError, PlatformErrorCode, ResourceBudget, SpanId, TraceId,
};
use latent_routing::ResolvedRevision;
use latent_scheduler::AdmittedSchedulingRequest;
use std::sync::{Arc, Weak};

mod budget;
mod result;

pub(super) struct ChildAdmission {
    pub delegation: ChildBudgetDelegation,
    pub control: Arc<ActivationControl>,
    pub target: ResolvedRevision,
}
struct Invoker {
    manager: Weak<Inner>,
    ceiling: ResourceBudget,
}
impl LocalActivationManager {
    /// One shared local adapter. It keeps no manager/backend ownership cycle and
    /// creates no dormant service resource. The configured ceiling is further
    /// intersected with half the parent's remaining grant and normal admission.
    pub fn local_service_invoker(
        &self,
        maximum_child_budget: ResourceBudget,
    ) -> Result<Arc<dyn LocalServiceInvoker>, PlatformError> {
        BudgetProfile::Phase3
            .validate_request(&maximum_child_budget)
            .map_err(|e| e.to_platform_error())?;
        if maximum_child_budget.cpu_fuel == 0
            || maximum_child_budget.memory_bytes == 0
            || maximum_child_budget
                .wall_time_limit_millis
                .is_some_and(|value| value == 0)
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid local service ceiling",
            ));
        }
        Ok(Arc::new(Invoker {
            manager: Arc::downgrade(&self.inner),
            ceiling: maximum_child_budget,
        }))
    }
}
impl LocalServiceInvoker for Invoker {
    fn start(
        &self,
        mut call: ProviderCall,
        request: LocalServiceRequest,
    ) -> Result<LocalServiceInvocation, PlatformError> {
        let executor = tokio::runtime::Handle::try_current().map_err(|_| {
            error(
                PlatformErrorCode::Unavailable,
                "local service runtime unavailable",
            )
        })?;
        let manager = self.manager.upgrade().ok_or_else(|| {
            error(
                PlatformErrorCode::Unavailable,
                "local service manager retired",
            )
        })?;
        let (activation, child) = manager.start_child(&call, request, &self.ceiling)?;
        // This witnesses the node's accepted child lifecycle, not guest success
        // or transactional effects. Failed evidence recording remains Unknown;
        // the actual child and call still go through node-owned cleanup.
        let _ = call.record_provider_outcome(
            latent_capabilities::broker::AuditProviderOutcome::LocalDispatchAccepted,
        );
        let (sender, receiver) = tokio::sync::oneshot::channel();
        // This task is bounded by the accepted call, descendant, quota and cell
        // owners. It drives cleanup after receiver loss; no extra worker pool.
        executor.spawn(drive_child(activation, child, call, sender));
        Ok(Box::pin(async move {
            receiver
                .await
                .map_err(|_| error(PlatformErrorCode::Internal, "local service owner stopped"))
        }))
    }
}
impl Inner {
    fn local_envelope(
        &self,
        call: &ProviderCall,
        request: LocalServiceRequest,
        target: &ResolvedRevision,
        grant: latent_core::EffectiveActivationBudget,
    ) -> Result<latent_activation::ActivationEnvelope, PlatformError> {
        let activation_id = self.ids.next_id()?;
        self.requests.build(ActivationRequest {
            activation_id: Some(activation_id.clone()),
            parent_activation_id: Some(call.activation_id().clone()),
            root_activation_id: Some(call.root_activation_id().clone()),
            principal: call.local_invocation_principal(target.target.tenant.clone()),
            target: target.target.clone(),
            deadline_unix_millis: grant.deadline.unix_millis(),
            priority: request.priority,
            // Host-derived span correlation cannot import guest lineage claims.
            trace: TraceContext {
                trace_id: TraceId(call.root_activation_id().0.clone()),
                span_id: SpanId(activation_id.0.clone()),
                trace_flags: 0,
                baggage: Metadata::new(),
            },
            idempotency_key: request.idempotency_key,
            retry_attempt: 0,
            budget: grant.budget,
            metadata: request.metadata,
            input: request.input,
            input_media_type: request.input_media_type,
        })
    }
    fn start_child(
        self: &Arc<Self>,
        call: &ProviderCall,
        request: LocalServiceRequest,
        ceiling: &ResourceBudget,
    ) -> Result<(ActivationHandle, ChildBudgetOwner), PlatformError> {
        let target = call.local_invocation_target(&request.target)?;
        if call.maximum_output_bytes() < 1024 {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "local service result capacity required",
            ));
        }
        let eligibility = self
            .dependencies
            .artifacts
            .execution_eligibility_selected(&target.release, target.publication.as_ref())?
            .ok_or_else(|| {
                error(
                    PlatformErrorCode::PermissionDenied,
                    "local service publication required",
                )
            })?;
        call.check_local_node(&self.clock, &eligibility)?;
        eligibility.authorize_tenant(&target.target.tenant)?;
        let parent = call.budget_accounting();
        let sample = self.clock.sample();
        let grant = budget::share(parent.remaining_at(sample.monotonic())).intersect(ceiling);
        let requested = budget::incoming(sample, call.deadline(), request.deadline_unix_millis)?;
        let delegation = parent.delegate_at(&grant, ceiling, ceiling, Some(&requested), sample)?;
        let grant = delegation.grant();
        let incoming = IncomingDeadline::new(
            grant.deadline.monotonic().expect("finite child"),
            grant.deadline.unix_millis().expect("finite child"),
        );
        let mut envelope = self.local_envelope(call, request, &target, grant)?;
        let activation_id = envelope.activation_id.clone();
        let (journal, cancellation) = self.journal.begin_with(&envelope, || {
            self.cancellations.register(activation_id.clone())
        })?;
        let transport_stop = Arc::new(TransportStop::default());
        let mut lifecycle = Lifecycle::new(
            journal,
            cancellation,
            self.clock.clone(),
            transport_stop.clone(),
            Some(incoming),
        );
        lifecycle.begin_observation(self.observations.as_ref(), &envelope);
        let control = Arc::new(ActivationControl::new(
            lifecycle.registration(),
            transport_stop.clone(),
            true,
        ));
        let token = lifecycle.registration().token();
        let admitted = (|| {
            let (permit, child) = self.resolve_and_admit(
                &mut envelope,
                &mut lifecycle,
                &token,
                Some(ChildAdmission {
                    delegation,
                    control: control.clone(),
                    target,
                }),
            )?;
            let child = child.expect("accepted descendant owner");
            lifecycle.advance(ActivationPhase::Queued, Metadata::new())?;
            let scheduled = self
                .dependencies
                .scheduler
                .try_enqueue(AdmittedSchedulingRequest {
                    permit,
                    cancellation: control.clone(),
                })?;
            lifecycle.assigned = true;
            lifecycle.scheduled = Some(scheduled);
            lifecycle.child_control = Some(control);
            Ok::<_, PlatformError>(child)
        })();
        let child = match admitted {
            Ok(child) => child,
            Err(failure) => {
                // Publish the actual admission/capacity failure, including a
                // zero-use finalization if the child was admitted but never ran.
                let _ = lifecycle.complete(failure_for_platform_error(
                    failure.clone(),
                    BudgetConsumption::default(),
                ));
                return Err(failure);
            }
        };
        Ok((
            self.child_handle(envelope, lifecycle, transport_stop),
            child,
        ))
    }
    fn child_handle(
        self: &Arc<Self>,
        envelope: latent_activation::ActivationEnvelope,
        mut lifecycle: Lifecycle,
        transport_stop: Arc<TransportStop>,
    ) -> ActivationHandle {
        let activation_id = envelope.activation_id.clone();
        let inner = self.clone();
        let completion = Box::pin(async move {
            let result = CatchPanic::new(inner.drive(envelope, &mut lifecycle)).await;
            let outcome = result.unwrap_or_else(|()| {
                failure_for_platform_error(
                    error(
                        PlatformErrorCode::Internal,
                        "local service execution or cleanup panicked",
                    ),
                    BudgetConsumption::default(),
                )
            });
            let activation_id = lifecycle.activation_id().clone();
            let resolved_revision = lifecycle.resolved.clone();
            let outcome = lifecycle.complete(outcome);
            ActivationReceipt {
                activation_id,
                resolved_revision,
                outcome,
            }
        });
        ActivationHandle {
            activation_id,
            completion,
            transport_stop,
        }
    }
}

async fn drive_child(
    mut activation: ActivationHandle,
    child: ChildBudgetOwner,
    call: ProviderCall,
    mut sender: tokio::sync::oneshot::Sender<LocalServiceCompletion>,
) {
    let receipt = tokio::select! {
        biased;
        () = call.budget_accounting().descendant_cancelled() => None,
        () = sender.closed() => None,
        receipt = &mut activation => Some(receipt),
    };
    let receipt = match receipt {
        Some(receipt) => receipt,
        None => {
            activation
                .interrupt_for_cleanup(ActivationTransportInterruption::Disconnected)
                .await
        }
    };
    let outcome = result::bounded(receipt.outcome, call.maximum_output_bytes());
    // A closed receiver drops the result only after actual child cleanup. If it
    // remains open, output and the sealed child ledger transfer together.
    let _ = sender.send(LocalServiceCompletion {
        outcome,
        call,
        child,
    });
}

impl ChildAdmission {
    pub(super) fn check_target(&self, resolved: &ResolvedRevision) -> Result<(), PlatformError> {
        // An unrelated control update may advance the global generation.
        // Require every pinned identity; diagnostic attributes come from
        // the current catalog, not the compiled binding descriptor.
        let expected = &self.target;
        if expected.target != resolved.target
            || expected.revision != resolved.revision
            || expected.release != resolved.release
            || expected.publication != resolved.publication
        {
            return Err(error(
                PlatformErrorCode::RouteUnavailable,
                "local service target changed",
            ));
        }
        Ok(())
    }
}
