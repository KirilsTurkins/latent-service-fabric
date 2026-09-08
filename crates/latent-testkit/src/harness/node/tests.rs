use latent_activation::ActivationRequest;
use latent_core::{PlatformErrorCode, PrincipalKind, TenantId};

use super::{authenticated_tenant, authorize_request};

fn request() -> ActivationRequest {
    ActivationRequest::from_envelope(crate::harness::tests::support::envelope())
}

#[test]
fn exact_principal_and_target_tenant_remain_required_for_administrators() {
    let mut request = request();
    request.principal.kind = PrincipalKind::Administrator;
    let trusted = request.principal.clone();
    let tenant = authenticated_tenant(&trusted).unwrap();
    authorize_request(&trusted, tenant, &request).unwrap();
    request.target.tenant = TenantId("foreign".to_owned());
    assert_eq!(
        authorize_request(&trusted, tenant, &request)
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    request.target.tenant = tenant.clone();
    request
        .principal
        .claims
        .insert("latent.node.operator".to_owned(), "true".to_owned());
    assert_eq!(
        authorize_request(&trusted, tenant, &request)
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    request.principal = trusted.clone();
    request.principal.subject = "another-user".to_owned();
    assert_eq!(
        authorize_request(&trusted, tenant, &request)
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
}

#[test]
fn anonymous_missing_scope_and_unbounded_claims_never_reach_node_queries() {
    let mut principal = request().principal;
    principal.kind = PrincipalKind::Anonymous;
    assert_eq!(
        authenticated_tenant(&principal).unwrap_err().code,
        PlatformErrorCode::Unauthenticated
    );
    principal.kind = PrincipalKind::User;
    principal.tenant = None;
    assert_eq!(
        authenticated_tenant(&principal).unwrap_err().code,
        PlatformErrorCode::Unauthenticated
    );
    principal.tenant = Some(TenantId("acme".to_owned()));
    principal
        .claims
        .insert("bounded".to_owned(), String::with_capacity(513));
    assert_eq!(
        authenticated_tenant(&principal).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
}
