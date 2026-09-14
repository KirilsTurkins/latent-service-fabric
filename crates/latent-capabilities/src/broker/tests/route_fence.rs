use super::*;
use std::sync::atomic::AtomicBool;
use std::time::Instant;
struct Fence(AtomicBool);
impl CapabilityRouteFence for Fence {
    fn with_current(
        &self,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if !self.0.load(Ordering::Acquire) {
            return Err(denied());
        }
        action()
    }
}
#[test]
fn local_route_cutover_denies_old_handles_before_provider_work_starts() {
    let mut f = Fixture::new(CapabilityBrokerLimits::default());
    let fence = Arc::new(Fence(AtomicBool::new(true)));
    let mut target = f.revision.clone();
    target.target.contract = latent_core::ContractId(CAP.into());
    target.target.function.0.clear();
    target.attributes.clear();
    f.plan = f
        .broker
        .compile_routed_plan(
            &f.revision,
            &[CapabilityBindingSpec {
                provider: &f.provider.reference(),
                imported_operations: &["read".into()],
                policy_ids: &["p".into()],
                provider_binding_id: "binding",
                deployment_restriction_json: br#"{"operations":[]}"#,
            }],
            &f.publication,
            &[f.publication.clone()],
            &[target.clone()],
            Some(fence.clone()),
            Instant::now() + Duration::from_secs(10),
        )
        .unwrap();
    let (request, control) = f.request("routed");
    let session = f.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    assert!(call(&session, handle).is_ok());
    let response = ready(
        session.call(handle, "read", resource(), b"input", output(), |call| {
            let resolved = call.local_target().unwrap();
            assert_eq!(resolved.revision, target.revision);
            assert_eq!(resolved.publication, target.publication);
            assert_eq!(resolved.route_generation, target.route_generation);
            assert_eq!(resolved.target.contract.0, CAP);
            assert_eq!(resolved.target.function.0, "read");
            async move { call.complete(b"ok") }
        }),
    )
    .unwrap();
    drop(response);
    fence.0.store(false, Ordering::Release);
    let entered = AtomicBool::new(false);
    assert!(ready(
        session.call(handle, "read", resource(), b"input", output(), |call| {
            entered.store(true, Ordering::Release);
            async move { call.complete(b"unexpected") }
        })
    )
    .is_err());
    assert!(!entered.load(Ordering::Acquire));
    assert!(session.bind(CAP, "read", resource()).is_err());
    assert_eq!(session.observer().live_calls(), 0);
    assert_eq!(f.broker.snapshot().buffer_bytes, 0);
}
