//! Normal authenticated invocation conversion for trusted transaction hosts.
use super::{
    authentication, conversion, local, proto, validation, AuthenticatedInvocationContext,
    InvocationLimits, InvocationResponse, InvocationRevision, PrincipalPolicy,
};
use latent_activation::{ActivationRequest, TraceContext};
use latent_core::{PlatformError, PlatformErrorCode};

pub fn transaction_activation_request(
    request: proto::InvokeRequest,
    context: &AuthenticatedInvocationContext,
    trace: TraceContext,
    limits: &InvocationLimits,
    principals: &dyn PrincipalPolicy,
) -> Result<ActivationRequest, PlatformError> {
    authentication::validate_trace(&trace, limits)?;
    let command = validation::validate_invoke(
        request,
        context.principal().clone(),
        trace,
        context.transport_deadline_unix_millis(),
        limits,
        principals,
    )
    .map_err(|status| PlatformError {
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
    })?;
    Ok(local::activation_request(command))
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
        let selected = transaction_activation_request(
            request(),
            &context,
            trace.next_trace().unwrap(),
            &limits,
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
            &LocalPrincipalPolicy
        )
        .is_err());
    }
}
