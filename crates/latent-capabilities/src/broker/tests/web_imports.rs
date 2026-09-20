use super::*;
use latent_core::CapabilityId;
use latent_executor::BoundImport;

#[test]
fn web_context_is_distinct_from_exact_provider_imports() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (mut request, control) = fixture.request("web-imports");
    let context = BoundImport {
        capability: CapabilityId("latent:context/context@0.1.0".into()),
        contract: "latent:context/context@0.1.0".into(),
        opaque_handle: "descriptive-only".into(),
    };
    assert!(session::imports_match(&fixture.plan, &request, false));
    assert!(!session::imports_match(&fixture.plan, &request, true));
    request.imports.push(context.clone());
    assert!(session::imports_match(&fixture.plan, &request, true));
    assert!(!session::imports_match(&fixture.plan, &request, false));
    // Adding context to an ordinary capsule cannot manufacture a sealed web use.
    assert!(fixture
        .broker
        .open_session(
            fixture.plan.clone(),
            &request,
            &control,
            &fixture.publication
        )
        .is_err());
    for replacement in [
        "latent:log/log@0.1.0",
        "latent:http/client@0.2.0",
        "unknown",
    ] {
        let mut wrong = request.clone();
        wrong.imports[1].contract = replacement.into();
        wrong.imports[1].capability.0 = replacement.into();
        assert!(!session::imports_match(&fixture.plan, &wrong, true));
    }
    let mut duplicate = request.clone();
    duplicate.imports.push(context);
    assert!(!session::imports_match(&fixture.plan, &duplicate, true));
    let mut missing = request.clone();
    missing.imports.remove(0);
    assert!(!session::imports_match(&fixture.plan, &missing, true));
    request.imports[1].capability.0 = "forged".into();
    assert!(!session::imports_match(&fixture.plan, &request, true));
}
