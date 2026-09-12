use super::*;
use crate::aot::{identity, supervisor::InputFixture, AotCompilerLimits, ValidatedAotProfile};
use latent_core::TenantId;

#[test]
fn native_observations_use_exact_sealed_source_identities_and_fixed_outcomes() {
    let fixture = InputFixture::new();
    let input = fixture.read();
    for (event, kind, result) in [
        (
            Event::Hit,
            Phase2AuditEventKind::CacheHit,
            AuditOutcome::Succeeded,
        ),
        (
            Event::Miss,
            Phase2AuditEventKind::CacheMiss,
            AuditOutcome::Succeeded,
        ),
        (
            Event::Corrupt,
            Phase2AuditEventKind::CacheCorruption,
            AuditOutcome::Failed,
        ),
    ] {
        let record = observation(input.key(), event);
        assert_eq!(record.scope, AuditScope::Tenant(TenantId("tests".into())));
        assert_eq!(record.kind, kind);
        assert_eq!(record.outcome, result);
        assert_eq!(record.cache_kind, Some(AuditCacheKind::Native));
        assert_eq!(
            record.identities.component.as_ref().unwrap().0,
            input.key().component().as_str()
        );
        assert_eq!(record.identities.package.as_ref(), input.key().package());
        assert!(record.identities.policies.is_empty());
    }
    capture(None, input.key(), Event::Hit);
    assert!(input.check().is_ok());
}

#[test]
fn unscoped_local_source_stays_node_scoped_without_a_package_claim() {
    let profile = ValidatedAotProfile::from_config(
        &crate::WasmtimeConfig::default(),
        AotCompilerLimits::default(),
    )
    .unwrap();
    let key = identity::fixture(&profile);
    let record = observation(&key, Event::Miss);
    assert_eq!(record.scope, AuditScope::Node);
    assert!(record.identities.package.is_none());
    assert!(record.identities.received_manifest_digest.is_none());
}
