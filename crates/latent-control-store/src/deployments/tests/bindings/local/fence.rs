use super::*;
use latent_core::{InvocationPrincipal, Metadata, PlatformError, PrincipalKind};
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, GrantRestriction, ResourceTarget,
};

pub(super) fn admit(f: &Fixture) -> Result<(), PlatformError> {
    let catalog = f.store.read_catalog();
    let eligibility = |name: &str| {
        let record = catalog.record_by_id(&DeploymentId(name.into())).unwrap();
        catalog
            .eligibility_for(&record.deployment.release, record.publication.as_ref())
            .unwrap()
            .clone()
    };
    let consumer = eligibility("consumer");
    let dependency = eligibility("clock-provider");
    let tenant = TenantId("tests".into());
    let snapshot = f.policies.snapshot(
        &tenant,
        &["clock".into()],
        "installed",
        std::time::Instant::now() + std::time::Duration::from_secs(10),
    )?;
    let principal = InvocationPrincipal {
        subject: "alice".into(),
        kind: PrincipalKind::User,
        tenant: Some(tenant),
        service: None,
        claims: Metadata::new(),
    };
    let restriction =
        GrantRestriction::parse(br#"{"operations":[]}"#, package_fixture::component::CLOCK)?;
    let reference = f.provider.reference();
    let decision = snapshot.authorize(
        EvaluationInput {
            principal: &principal,
            service: "packaging",
            publication: consumer.publication().as_str(),
            capability: package_fixture::component::CLOCK,
            operation: "now-nanos",
            resource: ResourceTarget::Clock,
        },
        &CallRestrictions {
            imported_operations: &["now-nanos".into()],
            deployment: &restriction,
            provider_configuration: &restriction,
            provider_profile: reference.profile(),
            configuration_digest: reference.configuration_digest(),
            configuration_epoch: reference.configuration_epoch(),
            remaining: CapabilityCeiling {
                operations: 1,
                input_bytes: 128,
                output_bytes: 256,
                wall_time_millis: 5000,
            },
            input_bytes: 0,
            output_bytes: 8,
        },
        &consumer,
    )?;
    let mut entered = false;
    let result = f
        .policies
        .with_current_dependencies(&decision, &[dependency], &mut |_, _| {
            entered = true;
            Ok(())
        });
    assert_eq!(entered, result.is_ok());
    result
}
