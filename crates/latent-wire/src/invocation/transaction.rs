//! Normal authenticated invocation conversion for trusted transaction hosts.
use super::{
    authentication, conversion, deadline, local, proto, validation, AuthenticatedInvocationContext,
    InvocationLimits, InvocationResponse, InvocationRevision, PrincipalPolicy,
};
use latent_activation::{ActivationRequest, TraceContext};
use latent_core::{
    BudgetProfile, ClockSample, IncomingDeadline, PlatformError, PlatformErrorCode, ResourceBudget,
};

pub fn transaction_activation_request(
    request: proto::InvokeRequest,
    context: &AuthenticatedInvocationContext,
    trace: TraceContext,
    limits: &InvocationLimits,
    transaction_ceiling: &ResourceBudget,
    sample: ClockSample,
    principals: &dyn PrincipalPolicy,
) -> Result<(ActivationRequest, IncomingDeadline), PlatformError> {
    // Ordinary InvocationService keeps zero state/effect ceilings. Only this
    // trusted installed transaction port supplies the actual configured node
    // ceilings; request metadata cannot select or enlarge them.
    limits.validate()?;
    if limits.budget_profile != BudgetProfile::Phase4
        || transaction_ceiling.state_read_bytes > 4 * 1024 * 1024
        || transaction_ceiling.state_write_bytes > 2 * 1024 * 1024
        || transaction_ceiling.effect_count > 32
    {
        return Err(PlatformError {
            code: PlatformErrorCode::InvalidArgument,
            message: "invalid installed transaction ceiling".into(),
            retryable: false,
            details: vec![],
        });
    }
    let mut selected = limits.clone();
    selected.max_state_read_bytes = transaction_ceiling.state_read_bytes;
    selected.max_state_write_bytes = transaction_ceiling.state_write_bytes;
    selected.max_effect_count = transaction_ceiling.effect_count;
    authentication::validate_trace(&trace, limits)?;
    let caller_deadline = request.deadline_unix_millis;
    let mut command = validation::validate_invoke(
        request,
        context.principal().clone(),
        trace,
        context.transport_deadline_unix_millis(),
        &selected,
        principals,
    )
    .map_err(invalid)?;
    // Reuse the maintained timing planner after the original borrowed bounds,
    // authentication and lineage validation. Its input needs only timing data;
    // the owned payload and maps are never cloned for this calculation.
    let plan = deadline::plan(
        &tonic::Request::new(proto::InvokeRequest {
            deadline_unix_millis: caller_deadline,
            ..Default::default()
        }),
        context.transport_deadline_unix_millis(),
        context.transport_expires_at(),
        sample,
        limits,
    )
    .map_err(invalid)?;
    let incoming = match (plan.expires_at, plan.effective_unix_millis) {
        (Some(expiry), Some(unix)) => IncomingDeadline::new(expiry, unix),
        _ => {
            return Err(invalid(tonic::Status::invalid_argument(
                "finite transaction deadline required",
            )))
        }
    };
    command.request.deadline_unix_millis = plan.effective_unix_millis;
    Ok((local::activation_request(command), incoming))
}

fn invalid(status: tonic::Status) -> PlatformError {
    PlatformError {
        code: match status.code() {
            tonic::Code::PermissionDenied | tonic::Code::Unauthenticated => {
                PlatformErrorCode::PermissionDenied
            }
            tonic::Code::ResourceExhausted => PlatformErrorCode::ResourceExhausted,
            tonic::Code::DeadlineExceeded => PlatformErrorCode::DeadlineExceeded,
            _ => PlatformErrorCode::InvalidArgument,
        },
        message: "invalid transactional invocation".into(),
        retryable: false,
        details: vec![],
    }
}

pub fn transaction_invocation_response(
    receipt: latent_node::ActivationReceipt,
    limits: &InvocationLimits,
) -> proto::InvokeResponse {
    conversion::public_invocation_response_to_proto(
        InvocationResponse {
            receipt: super::InvocationReceipt {
                activation_id: receipt.activation_id,
                resolved_revision: receipt
                    .resolved_revision
                    .map(|resolved| InvocationRevision {
                        revision_id: resolved.revision,
                        release_digest: resolved.release,
                        publication_id: resolved.publication,
                        route_generation: resolved.route_generation,
                    }),
            },
            outcome: receipt.outcome,
        },
        limits,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::invocation::{
        InvocationTraceSource, LocalPrincipalPolicy, SystemInvocationTraceSource,
    };
    use latent_core::{InvocationPrincipal, Metadata, PrincipalKind, TenantId};
    fn request() -> proto::InvokeRequest {
        proto::InvokeRequest {
            target: Some(proto::InvocationTarget {
                tenant: "a".into(),
                service: "a/aggregate".into(),
                contract: "a:aggregate/api@1.0.0".into(),
                function: "update".into(),
                route: None,
            }),
            payload: b"{\"params\":[]}".to_vec(),
            media_type: "application/vnd.latent.wit-values.v1+json".into(),
            budget: Some(proto::ResourceBudget {
                cpu_fuel: 100,
                memory_bytes: 4096,
                wall_time_limit_millis: Some(500),
                ..Default::default()
            }),
            ..Default::default()
        }
    }
    fn ceiling() -> ResourceBudget {
        ResourceBudget {
            state_read_bytes: 4 * 1024 * 1024,
            state_write_bytes: 2 * 1024 * 1024,
            effect_count: 1,
            ..Default::default()
        }
    }
    #[test]
    fn transaction_request_reuses_original_authenticated_target_lineage_and_deadline_validation() {
        let context = AuthenticatedInvocationContext::new(InvocationPrincipal {
            subject: "alice".into(),
            kind: PrincipalKind::User,
            tenant: Some(TenantId("a".into())),
            service: None,
            claims: Metadata::new(),
        })
        .with_transport_deadline(1200);
        let limits = InvocationLimits {
            budget_profile: latent_core::BudgetProfile::Phase4,
            ..InvocationLimits::default()
        };
        let trace = SystemInvocationTraceSource::default();
        let (selected, _) = transaction_activation_request(
            request(),
            &context,
            trace.next_trace().unwrap(),
            &limits,
            &ceiling(),
            ClockSample::new(1000, std::time::Instant::now()),
            &LocalPrincipalPolicy,
        )
        .unwrap();
        assert_eq!(selected.principal.subject, "alice");
        assert_eq!(selected.deadline_unix_millis, Some(1200));
        assert_eq!(selected.input, request().payload);
        let mut changed = request();
        changed.target.as_mut().unwrap().tenant = "foreign".into();
        assert!(transaction_activation_request(
            changed,
            &context,
            trace.next_trace().unwrap(),
            &limits,
            &ceiling(),
            ClockSample::new(1000, std::time::Instant::now()),
            &LocalPrincipalPolicy
        )
        .is_err());
        let mut changed = request();
        changed.parent_activation_id = Some("claimed-parent".into());
        changed.root_activation_id = Some("claimed-root".into());
        assert!(transaction_activation_request(
            changed,
            &context,
            trace.next_trace().unwrap(),
            &limits,
            &ceiling(),
            ClockSample::new(1000, std::time::Instant::now()),
            &LocalPrincipalPolicy
        )
        .is_err());
    }
    #[test]
    fn installed_transaction_ceiling_accepts_state_work_without_enabling_the_generic_invocation_endpoint(
    ) {
        let context = AuthenticatedInvocationContext::new(InvocationPrincipal {
            subject: "alice".into(),
            kind: PrincipalKind::User,
            tenant: Some(TenantId("a".into())),
            service: None,
            claims: Metadata::new(),
        })
        .with_transport_deadline(1200);
        let limits = InvocationLimits {
            budget_profile: BudgetProfile::Phase4,
            ..InvocationLimits::default()
        };
        limits.validate().unwrap();
        let trace = SystemInvocationTraceSource::default();
        let mut call = request();
        let budget = call.budget.as_mut().unwrap();
        budget.state_read_bytes = 4 * 1024 * 1024;
        budget.state_write_bytes = 2 * 1024 * 1024;
        budget.effect_count = 1;
        let (selected, _) = transaction_activation_request(
            call.clone(),
            &context,
            trace.next_trace().unwrap(),
            &limits,
            &ceiling(),
            ClockSample::new(1000, std::time::Instant::now()),
            &LocalPrincipalPolicy,
        )
        .unwrap();
        assert_eq!(selected.budget.state_read_bytes, 4 * 1024 * 1024);
        assert_eq!(selected.budget.state_write_bytes, 2 * 1024 * 1024);
        assert_eq!(selected.budget.effect_count, 1);
        let standard = validation::validate_invoke(
            call.clone(),
            context.principal().clone(),
            trace.next_trace().unwrap(),
            context.transport_deadline_unix_millis(),
            &limits,
            &LocalPrincipalPolicy,
        );
        assert_eq!(standard.unwrap_err().code(), tonic::Code::ResourceExhausted);
        for configured in [
            ResourceBudget {
                state_read_bytes: 0,
                ..ceiling()
            },
            ResourceBudget {
                state_write_bytes: 0,
                ..ceiling()
            },
            ResourceBudget {
                effect_count: 0,
                ..ceiling()
            },
        ] {
            assert!(transaction_activation_request(
                call.clone(),
                &context,
                trace.next_trace().unwrap(),
                &limits,
                &configured,
                ClockSample::new(1000, std::time::Instant::now()),
                &LocalPrincipalPolicy,
            )
            .is_err());
        }
        let wrong_profile = InvocationLimits::default();
        assert!(transaction_activation_request(
            call,
            &context,
            trace.next_trace().unwrap(),
            &wrong_profile,
            &ceiling(),
            ClockSample::new(1000, std::time::Instant::now()),
            &LocalPrincipalPolicy,
        )
        .is_err());
    }
    #[test]
    fn transaction_conversion_preserves_the_earlier_caller_deadline_and_exact_arrival_expiry() {
        let now = std::time::Instant::now();
        let transport_expiry = now + std::time::Duration::from_millis(200);
        let context = AuthenticatedInvocationContext::new(InvocationPrincipal {
            subject: "alice".into(),
            kind: PrincipalKind::User,
            tenant: Some(TenantId("a".into())),
            service: None,
            claims: Metadata::new(),
        })
        .with_transport_deadline_at(1200, transport_expiry);
        let limits = InvocationLimits {
            budget_profile: BudgetProfile::Phase4,
            ..InvocationLimits::default()
        };
        let trace = SystemInvocationTraceSource::default();
        let mut call = request();
        call.deadline_unix_millis = Some(1050);
        let (selected, incoming) = transaction_activation_request(
            call,
            &context,
            trace.next_trace().unwrap(),
            &limits,
            &ceiling(),
            ClockSample::new(1000, now),
            &LocalPrincipalPolicy,
        )
        .unwrap();
        assert_eq!(selected.deadline_unix_millis, Some(1050));
        assert_eq!(incoming.unix_millis(), 1050);
        assert_eq!(
            incoming.monotonic(),
            now + std::time::Duration::from_millis(50)
        );
        let (_, moved) = transaction_activation_request(
            request(),
            &context,
            trace.next_trace().unwrap(),
            &limits,
            &ceiling(),
            ClockSample::new(9000, now + std::time::Duration::from_millis(25)),
            &LocalPrincipalPolicy,
        )
        .unwrap();
        assert_eq!(moved.monotonic(), transport_expiry);
        assert_eq!(moved.unix_millis(), 9175);
        let mut expired = request();
        expired.deadline_unix_millis = Some(1000);
        assert_eq!(
            transaction_activation_request(
                expired,
                &context,
                trace.next_trace().unwrap(),
                &limits,
                &ceiling(),
                ClockSample::new(1000, now),
                &LocalPrincipalPolicy,
            )
            .unwrap_err()
            .code,
            PlatformErrorCode::DeadlineExceeded
        );
    }
}
