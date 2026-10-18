use super::*;
use latent_capabilities::broker::http::HttpError;
use latent_core::transaction_contract::Value;
use latent_effects::{
    authority::{CommitLink, EffectScope},
    payload::{payload_digest, PayloadRecord},
};
use latent_http::deferred::DeferredHttpAuthorization;

#[tokio::test]
async fn actual_retired_dispatch_policy_preserves_unavailable_without_provider_work() {
    let http = HttpFixture::new().await;
    let mut setup = http.setup().await;
    let installed = installed(&setup).await;
    let operation = &setup.fixture.settings.operations[0];
    let scope = EffectScope {
        tenant: operation.tenant.0.clone(),
        namespace: "orders".into(),
        incarnation: operation.incarnation,
        publication: operation.publication.as_str().into(),
        binding: "approved-http".into(),
        operation: "http".into(),
    };
    let value = Value {
        media_type: "text/plain".into(),
        bytes: b"retained-policy-refusal".to_vec(),
        metadata: Vec::new(),
    };
    let time = setup.effects.command_time().unwrap();
    let captured = setup
        .authority
        .capture(
            &scope,
            CommitLink {
                command: "dispatch-policy-command".into(),
                caller_scope: "dispatch-policy-caller".into(),
                attempt: 1,
                commit: "dispatch-policy-commit".into(),
                effect: "3".repeat(64),
                sequence: 0,
            },
            u64::try_from(value.bytes.len()).unwrap(),
            payload_digest(&value).unwrap(),
            time,
        )
        .unwrap();
    let payload = PayloadRecord::new(&captured, value).unwrap();
    let mut physical = setup.authority.accept(&captured, 1, time).unwrap();
    let grant = physical
        .accept_with(&captured, 1, time, |grant| grant)
        .unwrap();
    payload.verify_grant(&grant).unwrap();
    let registry = &setup.services.http.registry;
    let initial = registry.check_current(&grant, "POST", &http.endpoint.operation_path);
    let missing = super::super::super::http::DispatchRegistry::new().check_current(
        &grant,
        "POST",
        &http.endpoint.operation_path,
    );
    setup.policy.retire();
    let refused = registry.check_current(&grant, "POST", &http.endpoint.operation_path);
    drop(grant);
    physical.retire().unwrap();
    let physical_owners = setup.authority.owners().unwrap();
    let native = setup.kernel.native.clone();
    drop(payload);
    drop(installed);
    setup.services.http = super::super::super::InstalledHttpEffects::empty();
    setup.finish().await;
    http.finish().await;
    assert!(native.snapshot().unwrap().physically_retired());
    assert_eq!(physical_owners.physical, 0);
    assert_eq!(physical_owners.quarantined, 0);
    assert_eq!(initial, Ok(()));
    assert_eq!(missing, Err(HttpError::PermissionDenied));
    assert_eq!(refused, Err(HttpError::Unavailable));
}
