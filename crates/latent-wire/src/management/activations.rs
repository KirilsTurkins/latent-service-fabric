use super::{
    errors, identifier, proto, ManagementOperation, ManagementServiceAdapter, RequestBudget,
};
use latent_core::diagnostic::ActivationDiagnostic;
use tonic::{Request, Response, Status};

pub(super) fn inspect(
    adapter: &ManagementServiceAdapter,
    mut request: Request<proto::InspectActivationTreeRequest>,
) -> Result<Response<proto::InspectActivationTreeResponse>, Status> {
    let principal = adapter.authenticate(&mut request, ManagementOperation::Tenant)?;
    let tenant = crate::invocation::authenticated_tenant(&principal, &adapter.limits.auth)
        .map_err(|error| errors::platform_status(error, &adapter.limits))?;
    let mut budget = RequestBudget::new::<proto::InspectActivationTreeRequest>(&adapter.limits)?;
    let query = request.get_ref();
    budget.string(&query.activation_id, adapter.limits.max_id_bytes)?;
    identifier(&query.activation_id, adapter.limits.max_id_bytes)?;
    budget.page(query.page.as_ref(), &adapter.limits)?;
    adapter.check_encoded(query)?;
    let journal = adapter
        .activations
        .as_ref()
        .ok_or_else(|| Status::unimplemented("activation inspection unavailable"))?;
    let page_size = query.page.as_ref().map_or(0, |page| page.page_size);
    let value = journal
        .inspect_tree(
            tenant,
            &latent_core::ActivationId(query.activation_id.clone()),
            page_size as usize,
            query
                .page
                .as_ref()
                .and_then(|page| page.page_token.as_deref()),
        )
        .map_err(|error| errors::platform_status(error, &adapter.limits))?;
    let nodes = value
        .nodes
        .into_iter()
        .map(|node| proto::ActivationTreeNode {
            activation_id: node.activation_id.0,
            parent_activation_id: node.parent_activation_id.map(|id| id.0),
            root_activation_id: node.root_activation_id.0,
            phase: phase(node.phase).into(),
            terminal_state: node.terminal_state.map(|state| terminal(state).into()),
            last_updated_unix_millis: node.last_updated_unix_millis,
            diagnostic: node.diagnostic.map(diagnostic),
            diagnostic_is_terminal: node.diagnostic_is_terminal,
            principal_kind: match node.principal_kind {
                latent_core::PrincipalKind::Anonymous => "anonymous",
                latent_core::PrincipalKind::User => "user",
                latent_core::PrincipalKind::Service => "service",
                latent_core::PrincipalKind::Node => "node",
                latent_core::PrincipalKind::Trigger => "trigger",
                latent_core::PrincipalKind::Administrator => "administrator",
                _ => "unknown",
            }
            .into(),
            caller_service: node.caller_service.map(|id| id.0),
            granted_budget: node
                .granted_budget
                .as_ref()
                .map(super::control_budget_to_proto),
            effective_deadline_unix_millis: node.effective_deadline_unix_millis,
        })
        .collect();
    adapter.response(proto::InspectActivationTreeResponse {
        schema_version: 1,
        nodes,
        page: Some(proto::PageResponse {
            next_page_token: value.next_page_token,
        }),
        history_available: value.history_available,
        cursor_expired: value.cursor_expired,
        retained_history_only: true,
    })
}

fn diagnostic(value: ActivationDiagnostic) -> proto::ActivationDiagnostic {
    use std::fmt::Write as _;
    proto::ActivationDiagnostic {
        schema_version: ActivationDiagnostic::VERSION,
        stage: value.stage as i32,
        reason: value.reason as i32,
        profile: value.profile.map(|profile| profile as i32),
        profile_digest: value.profile_digest.map(|digest| {
            let mut text = String::with_capacity(64);
            for byte in digest {
                let _ = write!(text, "{byte:02x}");
            }
            text
        }),
        configured_bound: value.configured_bound,
        calculated_requirement: value.calculated_requirement,
        fixed_bytes: value.fixed_bytes,
        lifting_fuel: value.lifting_fuel,
        lift_multiplier: value.lift_multiplier,
    }
}
fn phase(value: latent_core::ActivationPhase) -> &'static str {
    use latent_core::ActivationPhase as P;
    match value {
        P::Received => "received",
        P::Resolved => "resolved",
        P::Admitted => "admitted",
        P::Queued => "queued",
        P::Materializing => "materializing",
        P::Running => "running",
        _ => "unknown",
    }
}
fn terminal(value: latent_core::ActivationTerminalState) -> &'static str {
    use latent_core::ActivationTerminalState as T;
    match value {
        T::Completed => "completed",
        T::Rejected => "rejected",
        T::Cancelled => "cancelled",
        T::DeadlineExceeded => "deadline_exceeded",
        T::ResourceExhausted => "resource_exhausted",
        T::GuestTrap => "guest_trap",
        T::StateConflict => "state_conflict",
        T::DependencyFailed => "dependency_failed",
        T::PlatformFailed => "platform_failed",
        _ => "unknown",
    }
}
