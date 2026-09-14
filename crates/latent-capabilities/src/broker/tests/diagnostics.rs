use super::*;
use crate::broker::diagnostics::{BindingState, TenantUsage};
use latent_core::TenantId;

#[test]
fn explanations_use_current_compiled_policy_and_cannot_admit_a_call() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("inspection");
    let session = f.session(&request, &control);
    let mut principal = session.core.principal.clone();
    let allowed = f
        .plan
        .explain_grant(&principal, CAP, "read", resource())
        .unwrap();
    assert!(allowed.allowed);
    assert_eq!(allowed.ceiling.unwrap().operations, 4);
    assert_eq!(f.broker.snapshot().calls, 0);
    assert_eq!(
        f.plan.inspect_bindings(&TenantId("a".into())).unwrap()[0].state,
        BindingState::Current
    );
    principal.tenant = Some(TenantId("b".into()));
    assert!(f
        .plan
        .explain_grant(&principal, CAP, "read", resource())
        .is_err());
    assert!(f.plan.inspect_bindings(&TenantId("b".into())).is_err());
    f.revoke_policy();
    let denied = f
        .plan
        .explain_grant(&session.core.principal, CAP, "read", resource())
        .unwrap();
    assert!(!denied.allowed);
    assert_eq!(denied.reason, "policy-changed-or-revoked");
    assert!(allowed.allowed); // Old public DTO is still descriptive, never consulted.
    assert!(session.bind(CAP, "read", resource()).is_err());
    f.provider.retire();
    assert_eq!(
        f.plan.inspect_bindings(&TenantId("a".into())).unwrap()[0].state,
        BindingState::ProviderUnavailable
    );
}

#[test]
fn scoped_usage_tracks_cancelled_calls_and_retained_output_until_actual_drop() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let tenant = TenantId("a".into());
    let (request, control) = f.request("retained-output");
    let session = f.session(&request, &control);
    let observer = session.observer();
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let call = session
        .dispatch(handle, "read", resource(), b"input", output(), |call| call)
        .unwrap();
    let usage = f.broker.inspect_tenant_usage(&tenant).unwrap();
    assert_eq!((usage.calls, usage.reserved_buffer_bytes), (1, 37));
    let result = call.complete(b"response").unwrap();
    drop(session);
    let usage = f.broker.inspect_tenant_usage(&tenant).unwrap();
    assert_eq!(
        (
            usage.calls,
            usage.results,
            usage.reserved_buffer_bytes,
            usage.retired_sessions_with_resources
        ),
        (0, 1, 32, 1)
    );
    assert_eq!(observer.reserved_buffer_bytes(), 32);
    assert_eq!(
        f.broker
            .inspect_tenant_usage(&TenantId("b".into()))
            .unwrap(),
        TenantUsage::default()
    );
    drop(result);
    assert!(observer.is_quiescent());
    assert_eq!(
        f.broker.inspect_tenant_usage(&tenant).unwrap(),
        TenantUsage::default()
    );
    let (request, control) = f.request("cancelled-owner");
    let session = f.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let call = session
        .dispatch(handle, "read", resource(), b"input", output(), |call| call)
        .unwrap();
    control.probe.0.store(true, Ordering::Release);
    drop(session);
    let usage = f.broker.inspect_tenant_usage(&tenant).unwrap();
    assert_eq!(
        (
            usage.calls,
            usage.reserved_buffer_bytes,
            usage.retired_sessions_with_resources
        ),
        (1, 37, 1)
    );
    drop(call);
    assert_eq!(
        f.broker.inspect_tenant_usage(&tenant).unwrap(),
        TenantUsage::default()
    );
    let global = f.broker.inspect_node_usage().unwrap();
    assert!(global.pools.is_none() && global.io.is_none());
}
