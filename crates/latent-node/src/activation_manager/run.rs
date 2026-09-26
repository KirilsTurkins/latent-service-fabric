use std::sync::Arc;

use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_admission::{AdmissionPermit, AdmissionRequest};
use latent_core::{
    ActivationBudget, ActivationPhase, BudgetConsumption, Metadata, PlatformError,
    PlatformErrorCode,
};
use latent_executor::{
    BoundImport, ExecutionCancellation, ExecutionCancellationProbe, ExecutionCell,
    ExecutionCleanup, ExecutionRequest, PreparedUse,
};
use latent_routing::RevisionPolicySource;
use latent_scheduler::AdmittedSchedulingRequest;
use latent_telemetry::ActivationCleanupDisposition;

use crate::activation_runner::{
    disposition_failure, failure_for_platform_error, map_execution_outcome, outcome_consumption,
};
use crate::CancellationToken;

use super::control::{cancelled, deadline_error, error, execution, stage};
use super::lifecycle::Lifecycle;
use super::probes::ActivationControl;
use super::Inner;

#[derive(Clone)]
struct ExecutionControl {
    probe: Arc<ActivationControl>,
    accounting: ActivationBudget,
}

impl ExecutionCancellation for ExecutionControl {
    fn activation_id(&self) -> &latent_core::ActivationId {
        self.probe.token().activation_id()
    }
    fn is_cancelled(&self) -> bool {
        self.probe.stopped()
            || (self.accounting.profile() == latent_core::BudgetProfile::Phase3
                && self.accounting.descendant_is_cancelled())
    }
    fn reason(&self) -> Option<String> {
        self.probe.reason().or_else(|| {
            (self.accounting.profile() == latent_core::BudgetProfile::Phase3
                && self.accounting.descendant_is_cancelled())
            .then(|| "activation ancestor stopped".to_owned())
        })
    }
    fn probe(&self) -> Option<Arc<dyn ExecutionCancellationProbe>> {
        if self.accounting.profile() == latent_core::BudgetProfile::Phase3 {
            Some(Arc::new(self.clone()))
        } else {
            Some(self.probe.clone())
        }
    }
    fn budget_accounting(&self) -> Option<&ActivationBudget> {
        Some(&self.accounting)
    }
}

impl ExecutionCancellationProbe for ExecutionControl {
    fn is_cancelled(&self) -> bool {
        ExecutionCancellation::is_cancelled(self)
    }
    fn reason(&self) -> Option<String> {
        ExecutionCancellation::reason(self)
    }
}

impl Inner {
    pub(super) async fn drive(
        &self,
        envelope: ActivationEnvelope,
        lifecycle: &mut Lifecycle,
    ) -> ActivationOutcome {
        let result = self.run(envelope, lifecycle).await;
        lifecycle.observe_cancellation();
        let outcome = result.unwrap_or_else(|error| {
            failure_for_platform_error(error, BudgetConsumption::default())
        });
        let Some(scheduled) = lifecycle.scheduled.take() else {
            return outcome;
        };
        let quarantined = lifecycle.quarantine_reason.is_some();
        let quarantine_reason = lifecycle.quarantine_reason.take();
        let disposition = async move {
            if let Some(reason) = quarantine_reason {
                scheduled.quarantine(reason).await
            } else {
                scheduled.release().await
            }
        };
        let result = tokio::time::timeout(self.config.cleanup_grace, disposition).await;
        let failure = match result {
            Ok(Ok(())) => {
                lifecycle.observe_cleanup(if quarantined {
                    ActivationCleanupDisposition::Quarantined
                } else {
                    ActivationCleanupDisposition::Released
                });
                return outcome;
            }
            Ok(Err(error)) => error,
            Err(_) => error(PlatformErrorCode::Internal, "cell disposition timed out"),
        };
        lifecycle.observe_cleanup(ActivationCleanupDisposition::Failed);
        disposition_failure(
            if quarantined { "quarantine" } else { "release" },
            failure,
            outcome_consumption(&outcome),
        )
    }

    async fn run(
        &self,
        mut envelope: ActivationEnvelope,
        lifecycle: &mut Lifecycle,
    ) -> Result<ActivationOutcome, PlatformError> {
        let token = lifecycle.registration().token();
        let transport = Arc::clone(&lifecycle.transport_stop);
        if token.is_cancelled() {
            return Err(cancelled(&token));
        }
        if lifecycle
            .incoming_deadline
            .is_some_and(|deadline| self.clock.monotonic_now() >= deadline.monotonic())
        {
            return Err(deadline_error());
        }
        if let Some(failure) = transport.failure() {
            return Err(failure);
        }
        let child_control = lifecycle.child_control.take();
        let permit = if child_control.is_some() {
            None
        } else if let Some(permit) = lifecycle.inbound_permit.take() {
            Some(permit)
        } else {
            let wait = super::admission_wait::Window::new(
                &token,
                lifecycle
                    .incoming_deadline
                    .map(|deadline| deadline.monotonic()),
                &self.clock,
                &transport,
            );
            let catalog = self.dependencies.catalog.pin()?;
            let resolved = wait
                .check(|| catalog.resolve(&envelope.target, Some(&envelope.activation_id.0)))
                .await?;
            Some(
                wait.check(|| {
                    self.resolve_and_admit_input(
                        &mut envelope,
                        lifecycle,
                        &token,
                        None,
                        None,
                        Some((resolved.clone(), catalog.clone())),
                    )
                    .map(|admitted| admitted.0)
                })
                .await?,
            )
        };
        let budget = lifecycle.budget.as_ref().expect("admitted budget").clone();
        if permit.is_some() {
            lifecycle.advance(ActivationPhase::Queued, Metadata::new())?;
        }
        let expiry = budget.deadline().monotonic();
        // Keep the original admission reservation and deadline while code is
        // prepared. A cold request does not occupy an execution cell.
        let (key, ready) = self
            .prepare_ready(&envelope, &token, &budget, &transport)
            .await?;
        let control = child_control.unwrap_or_else(|| {
            Arc::new(ActivationControl::new(
                lifecycle.registration(),
                transport.clone(),
                budget.profile() == latent_core::BudgetProfile::Phase3,
            ))
        });
        let scheduled = if let Some(permit) = permit {
            if budget.profile() == latent_core::BudgetProfile::Phase3 {
                budget.enable_descendants(permit.delegation_limits(), control.clone())?;
            }
            stage(
                self.dependencies
                    .scheduler
                    .enqueue(AdmittedSchedulingRequest {
                        permit,
                        cancellation: control.clone(),
                    }),
                &token,
                expiry,
                &self.clock,
                &transport,
            )
            .await?
        } else {
            // Nested calls reserve one existing cell synchronously. No child
            // can queue behind a parent which holds the capacity it needs.
            lifecycle.scheduled.take().expect("admitted child cell")
        };
        lifecycle.assigned = true;
        // An implementation cannot substitute another reservation or target.
        if scheduled.permit().admission().activation_id() != &envelope.activation_id
            || scheduled.permit().admission().revision()
                != envelope
                    .resolved_revision
                    .as_ref()
                    .expect("pinned revision")
        {
            drop(scheduled);
            return Err(error(
                PlatformErrorCode::IncompatibleContract,
                "scheduler changed the admitted activation",
            ));
        }
        lifecycle.scheduled = Some(scheduled);
        lifecycle.advance(ActivationPhase::Materializing, Metadata::new())?;
        let (prepared, imports) = self
            .materialize(&envelope, &control, &budget, &key, ready)
            .await?;
        self.execute(envelope, lifecycle, control, budget, prepared, imports)
            .await
    }

    async fn execute(
        &self,
        envelope: ActivationEnvelope,
        lifecycle: &mut Lifecycle,
        control: Arc<ActivationControl>,
        budget: ActivationBudget,
        prepared: PreparedUse,
        imports: Vec<BoundImport>,
    ) -> Result<ActivationOutcome, PlatformError> {
        let expiry = budget.deadline().monotonic();
        if control.token().is_cancelled() {
            return Err(cancelled(control.token()));
        }
        if budget.deadline().is_expired_at(self.clock.monotonic_now()) {
            return Err(deadline_error());
        }
        if let Some(failure) = control.transport().failure() {
            return Err(failure);
        }
        let scheduled = lifecycle
            .scheduled
            .as_ref()
            .expect("assigned execution cell");
        let lease = scheduled.lease();
        let cell_id = lease.id.0.clone();
        let cell = ExecutionCell {
            id: lease.id.clone(),
            class: scheduled
                .permit()
                .admission()
                .obligations()
                .cell_class
                .clone(),
            maximum_memory_bytes: lease.granted_budget.memory_bytes,
            metadata: Metadata::new(),
        };
        let request = ExecutionRequest {
            activation: envelope,
            prepared: prepared.descriptor().clone(),
            cell,
            imports,
            budget: budget.granted().clone(),
        };
        let cancellation = ExecutionControl {
            probe: control.clone(),
            accounting: budget,
        };
        lifecycle.advance(ActivationPhase::Running, Metadata::new())?;
        lifecycle.execution_started = true;
        let report = execution(
            self.dependencies
                .backend
                .invoke_prepared_contained(request, prepared, &cancellation),
            control.token(),
            expiry,
            &self.clock,
            self.config.cleanup_grace,
            control.transport(),
        )
        .await;
        let disposition = match report.cleanup {
            ExecutionCleanup::Reusable => "released",
            ExecutionCleanup::Quarantine { reason } => {
                let mut end = reason.len().min(256);
                while !reason.is_char_boundary(end) {
                    end -= 1;
                }
                lifecycle.quarantine_reason = Some(reason[..end].to_owned());
                "quarantined"
            }
        };
        Ok(map_execution_outcome(report.outcome, &cell_id, disposition))
    }

    pub(super) fn resolve_and_admit(
        &self,
        envelope: &mut ActivationEnvelope,
        lifecycle: &mut Lifecycle,
        token: &CancellationToken,
        child: Option<super::local_service::ChildAdmission>,
    ) -> Result<(AdmissionPermit, Option<latent_core::ChildBudgetOwner>), PlatformError> {
        self.resolve_and_admit_input(envelope, lifecycle, token, child, None, None)
    }

    pub(super) fn resolve_and_admit_input(
        &self,
        envelope: &mut ActivationEnvelope,
        lifecycle: &mut Lifecycle,
        token: &CancellationToken,
        child: Option<super::local_service::ChildAdmission>,
        maximum_inbound_bytes: Option<usize>,
        selected: Option<(
            latent_routing::ResolvedRevision,
            Arc<dyn latent_routing::ActivationCatalog>,
        )>,
    ) -> Result<(AdmissionPermit, Option<latent_core::ChildBudgetOwner>), PlatformError> {
        // A single immutable catalog view supplies both revision selection and
        // policy, even if a deployment changes while this invocation is queued.
        let (resolved, catalog) = if let Some(selected) = selected {
            selected
        } else {
            let catalog = self.dependencies.catalog.pin()?;
            let resolved = catalog.resolve(&envelope.target, Some(&envelope.activation_id.0))?;
            (resolved, catalog)
        };
        if resolved.target != envelope.target || resolved.route_generation != catalog.generation() {
            return Err(error(
                PlatformErrorCode::IncompatibleContract,
                "resolved activation does not match its pinned target",
            ));
        }
        if let Some(child) = &child {
            child.check_target(&resolved)?;
        }
        if let Some(previous) = &lifecycle.resolved {
            if previous != &resolved || lifecycle.budget.is_some() {
                return Err(error(
                    PlatformErrorCode::IncompatibleContract,
                    "admission cannot replace or repeat an accepted revision",
                ));
            }
        } else {
            lifecycle.resolved = Some(resolved.clone());
            envelope.resolved_revision = Some(resolved.clone());
            lifecycle.advance(
                ActivationPhase::Resolved,
                Metadata::from([
                    ("revision".to_owned(), resolved.revision.0.clone()),
                    ("release".to_owned(), resolved.release.0.clone()),
                    (
                        "route-generation".to_owned(),
                        resolved.route_generation.0.to_string(),
                    ),
                ]),
            )?;
        }
        if token.is_cancelled() {
            return Err(cancelled(token));
        }
        let policy: Arc<dyn RevisionPolicySource> = catalog;
        let admission = self.dependencies.admission.with_policy_source(policy);
        let request = AdmissionRequest {
            activation_id: envelope.activation_id.clone(),
            principal: envelope.principal.clone(),
            revision: resolved.clone(),
            requested_budget: envelope.budget.clone(),
            deadline_unix_millis: envelope.deadline_unix_millis,
            payload_bytes: u64::try_from(maximum_inbound_bytes.unwrap_or(envelope.input.len()))
                .map_err(|_| {
                    error(
                        PlatformErrorCode::ResourceExhausted,
                        "activation input size overflow",
                    )
                })?,
            priority: envelope.priority,
            attributes: Metadata::new(),
        };
        // Policy and quota work may consume part of a short allowance. Resample
        // the same live clock at reservation without reanchoring ingress expiry.
        let permit = admission.admit_with_clock(
            request,
            lifecycle.incoming_deadline.as_ref(),
            self.clock.as_ref(),
        )?;
        let child_owner = child
            .map(|child| {
                if permit.budget_profile() != latent_core::BudgetProfile::Phase3 {
                    return Err(error(
                        PlatformErrorCode::PermissionDenied,
                        "local service requires Phase 3 admission",
                    ));
                }
                child.delegation.accept(
                    permit.effective_budget(),
                    child.control,
                    self.clock.monotonic_now(),
                )
            })
            .transpose()?;
        let budget = if let Some(child) = &child_owner {
            child.accounting().clone()
        } else {
            ActivationBudget::with_profile(
                permit.effective_budget().clone(),
                permit.budget_profile(),
            )
            .map_err(|error| error.to_platform_error())?
        };
        if let Some(observer) = self.clock.deadline_diagnostic_observer() {
            observer.record_for_activation(
                &envelope.activation_id.0,
                latent_core::DeadlineDiagnosticObservation::AdmittedLedger {
                    observed_at: self.clock.monotonic_now(),
                    deadline: permit.deadline().clone(),
                    budget: permit.granted_budget().clone(),
                },
            );
        }
        envelope.budget = permit.granted_budget().clone();
        envelope.deadline_unix_millis = permit.deadline().unix_millis();
        envelope.priority = permit.obligations().priority;
        envelope.resolved_revision = Some(permit.revision().clone());
        lifecycle.resolved.clone_from(&envelope.resolved_revision);
        lifecycle.budget = Some(budget.clone());
        lifecycle.advance(ActivationPhase::Admitted, Metadata::new())?;
        Ok((permit, child_owner))
    }
}
