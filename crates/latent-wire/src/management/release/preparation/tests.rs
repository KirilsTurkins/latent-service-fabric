use super::*;
use crate::invocation::AuthenticatedInvocationContext;
use latent_core::{InvocationPrincipal, Metadata, PrincipalKind, TenantId};

#[test]
fn release_preparation_wait_is_finite_and_keeps_original_transport_expiry() {
    for millis in [0, MAX_RELEASE_PREPARATION_WAIT_MILLIS + 1, u64::MAX] {
        let request = Request::new(proto::PrepareReleaseRequest {
            maximum_wait_millis: millis,
            ..Default::default()
        });
        assert_eq!(
            deadline(&request).unwrap_err().code(),
            tonic::Code::InvalidArgument
        );
    }
    let mut request = Request::new(proto::PrepareReleaseRequest {
        maximum_wait_millis: MAX_RELEASE_PREPARATION_WAIT_MILLIS,
        ..Default::default()
    });
    let original = Instant::now() + Duration::from_millis(17);
    request.extensions_mut().insert(
        AuthenticatedInvocationContext::new(InvocationPrincipal {
            subject: "operator".into(),
            kind: PrincipalKind::Administrator,
            tenant: Some(TenantId("acme".into())),
            service: None,
            claims: Metadata::new(),
        })
        .with_transport_deadline_at(1, original),
    );
    assert_eq!(deadline(&request).unwrap(), original);
    let expired = Instant::now() - Duration::from_millis(1);
    request.extensions_mut().insert(
        AuthenticatedInvocationContext::new(InvocationPrincipal {
            subject: "operator".into(),
            kind: PrincipalKind::Administrator,
            tenant: Some(TenantId("acme".into())),
            service: None,
            claims: Metadata::new(),
        })
        .with_transport_deadline_at(1, expired),
    );
    assert_eq!(deadline(&request).unwrap(), expired);
}

#[test]
fn release_preparation_body_bound_does_not_inherit_a_longer_transport_wait() {
    let request = Request::new(proto::PrepareReleaseRequest {
        maximum_wait_millis: 5,
        ..Default::default()
    });
    let before = Instant::now();
    let expires = deadline(&request).unwrap();
    let after = Instant::now();
    assert!(expires >= before + Duration::from_millis(5));
    assert!(expires <= after + Duration::from_millis(5));
    assert_eq!(MAX_RELEASE_PREPARATION_WAIT_MILLIS, 300_000);
}
