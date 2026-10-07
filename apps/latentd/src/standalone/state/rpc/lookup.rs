//! Read-only typed recovery retains the actual installed source and result owner.
use super::*;
use latent_activation::ActivationRequest;
use latent_core::{IncomingDeadline, ResourceBudget};
use latent_wire::phase4::transaction as t;

struct Selection {
    command: t::CommandSelector,
    publication: latent_wire::management::proto::PublicationRef,
    attempt: Option<String>,
    commit: Option<String>,
}
impl Selection {
    fn from_request(value: contract::Request) -> Result<Self, PlatformError> {
        match value {
            contract::Request::LookupCommand(value) => Ok(Self {
                command: value.command.ok_or_else(denied)?,
                publication: value.authorization_publication.ok_or_else(denied)?,
                attempt: value.attempt_id,
                commit: None,
            }),
            contract::Request::LookupCommit(value) => Ok(Self {
                command: value.command.ok_or_else(denied)?,
                publication: value.authorization_publication.ok_or_else(denied)?,
                attempt: None,
                commit: Some(value.receipt_id),
            }),
            _ => Err(denied()),
        }
    }
    fn accepts(&self, op: &crate::standalone::state::InstalledTransactionOperation) -> bool {
        self.command.namespace.as_ref().is_some_and(|namespace| {
            op.target().tenant.0 == namespace.tenant
                && op.namespace() == namespace.namespace
                && op.incarnation().to_string() == namespace.incarnation
                && op.entity() == self.command.entity.as_deref()
                && op.target().function.0 == self.command.operation
                && op.mode() == latent_manifest::TransactionOperationMode::StrictCommand
                && op.publication().publication().as_str() == self.publication.id
                && op.target().tenant.0 == self.publication.tenant
        }) && self.command.shared_recovery_scope.is_none()
    }
}
impl InstalledTransactionRpc {
    pub(super) fn start_lookup(
        &self,
        call: Phase4Call,
    ) -> Result<BoxFuture<'_, Result<OwnedPhase4Response, PlatformError>>, PlatformError> {
        call.request().validate().map_err(|_| denied())?;
        let (context, message) = call.into_parts();
        LocalPrincipalPolicy.authenticate(context.principal())?;
        let selection = Selection::from_request(message)?;
        let mut matches = self
            .state
            .0
            .installed
            .iter()
            .filter(|op| selection.accepts(op));
        let installed = matches.next().cloned().ok_or_else(denied)?;
        if matches.next().is_some() {
            return Err(denied());
        }
        installed.publication().check_current()?;
        let request = request(
            &context,
            installed.target().clone(),
            self.traces.next_trace()?,
            &self.limits,
            &self.transaction_ceiling,
            self.clock.sample(),
        )?;
        let expiry = context.transport_expires_at().ok_or_else(denied)?;
        let unix = context
            .transport_deadline_unix_millis()
            .ok_or_else(denied)?;
        let admission = self.state.result_admission(
            Arc::clone(&installed),
            selection.command.client_key.clone(),
            Arc::new(RpcResultCodec),
        )?;
        let slot = self.cleanup.reserve_activation()?;
        let handle = self.manager.start_transaction_with_deadline(
            request,
            Some(IncomingDeadline::new(expiry, unix)),
            admission,
        )?;
        let retained = slot.own(handle, installed);
        Ok(Box::pin(async move {
            let (receipt, _) = retained.await;
            projection::lookup_response(
                receipt,
                &selection.command,
                selection.attempt.as_deref(),
                selection.commit.as_deref(),
                &self.limits,
            )
        }))
    }
}
fn request(
    context: &latent_wire::invocation::AuthenticatedInvocationContext,
    target: latent_routing::InvocationTarget,
    trace: latent_activation::TraceContext,
    limits: &InvocationLimits,
    ceiling: &ResourceBudget,
    sample: latent_core::ClockSample,
) -> Result<ActivationRequest, PlatformError> {
    let expiry = context.transport_expires_at().ok_or_else(denied)?;
    if expiry <= sample.monotonic() || context.transport_deadline_unix_millis().is_none() {
        return Err(unavailable());
    }
    let wall = u64::try_from(
        expiry
            .saturating_duration_since(sample.monotonic())
            .as_millis(),
    )
    .map_err(|_| denied())?
    .min(limits.max_timeout_millis)
    .min(ceiling.wall_time_limit_millis.ok_or_else(denied)?);
    if wall == 0 {
        return Err(unavailable());
    }
    Ok(ActivationRequest {
        activation_id: None,
        root_activation_id: None,
        parent_activation_id: None,
        principal: context.principal().clone(),
        target,
        deadline_unix_millis: context.transport_deadline_unix_millis(),
        priority: 0,
        trace,
        idempotency_key: None,
        retry_attempt: 0,
        budget: ResourceBudget {
            cpu_fuel: ceiling.cpu_fuel.min(limits.max_cpu_fuel),
            memory_bytes: ceiling.memory_bytes.min(limits.max_memory_bytes),
            wall_time_limit_millis: Some(wall),
            state_read_bytes: ceiling.state_read_bytes,
            state_write_bytes: 0,
            effect_count: 0,
            child_calls: 0,
            outbound_requests: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 0,
        },
        metadata: latent_core::Metadata::new(),
        input: Vec::new(),
        input_media_type: "application/vnd.latent.wit-values.v1+json".into(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn result_lookup_request_keeps_arrival_deadline_and_has_no_execution_input_or_write_budget() {
        let sample = latent_core::ClockSample::new(10_000, std::time::Instant::now());
        let expiry = sample.monotonic() + std::time::Duration::from_millis(750);
        let context = latent_wire::invocation::AuthenticatedInvocationContext::new(
            latent_core::InvocationPrincipal {
                subject: "alice".into(),
                kind: latent_core::PrincipalKind::User,
                tenant: Some(latent_core::TenantId("alpha".into())),
                service: None,
                claims: latent_core::Metadata::new(),
            },
        )
        .with_transport_deadline_at(10_750, expiry);
        let target = latent_routing::InvocationTarget {
            tenant: latent_core::TenantId("alpha".into()),
            service: latent_core::ServiceId("alpha/aggregate".into()),
            contract: latent_core::ContractId("alpha:aggregate/api@1.0.0".into()),
            function: latent_core::FunctionId("update".into()),
            route: None,
        };
        let ceiling = ResourceBudget {
            cpu_fuel: 100,
            memory_bytes: 4096,
            wall_time_limit_millis: Some(5_000),
            state_read_bytes: 4_194_304,
            state_write_bytes: 2_097_152,
            effect_count: 32,
            child_calls: 0,
            outbound_requests: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 0,
        };
        let trace = SystemInvocationTraceSource::default().next_trace().unwrap();
        let actual = request(
            &context,
            target.clone(),
            trace,
            &InvocationLimits::default(),
            &ceiling,
            sample,
        )
        .unwrap();
        assert_eq!(actual.target, target);
        assert_eq!(actual.principal, *context.principal());
        assert_eq!(actual.deadline_unix_millis, Some(10_750));
        assert_eq!(actual.budget.wall_time_limit_millis, Some(750));
        assert_eq!(actual.budget.state_read_bytes, ceiling.state_read_bytes);
        assert_eq!(actual.budget.state_write_bytes, 0);
        assert_eq!(actual.budget.effect_count, 0);
        assert_eq!(actual.budget.child_calls, 0);
        assert_eq!(actual.budget.outbound_requests, 0);
        assert!(actual.input.is_empty() && actual.input.capacity() == 0);
        assert!(actual.parent_activation_id.is_none() && actual.metadata.is_empty());
        let later = latent_core::ClockSample::new(10_750, expiry);
        assert!(request(
            &context,
            target,
            SystemInvocationTraceSource::default().next_trace().unwrap(),
            &InvocationLimits::default(),
            &ceiling,
            later
        )
        .is_err());
    }
}
