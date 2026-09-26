use super::*;
use latent_core::{BoxFuture, ErrorDetail, Metadata};
use latent_executor::{BoundImport, ExecutionRequest, PreparationReadWait};
use latent_policy::capability::{MutationRequest, RecordKind};
use serde_json::json;
use std::{
    future::Future,
    pin::Pin,
    sync::Mutex,
    task::{Context, Poll},
    time::Instant,
};

pub fn busy_error() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: "closed test currentness contention".into(),
        retryable: true,
        details: vec![ErrorDetail {
            kind: "admission.currentness".into(),
            fields: Metadata::from([("reason".into(), "admission-authority-busy".into())]),
        }],
    }
}

#[derive(Default)]
pub struct Fence {
    pub calls: AtomicUsize,
    pub hold_at: AtomicUsize,
    pub post_commit: AtomicBool,
    pub failure: Mutex<Option<PlatformError>>,
}
impl CapabilityRouteFence for Fence {
    fn with_current(
        &self,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let count = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        let hold = self.hold_at.load(Ordering::SeqCst);
        if hold != 0 && count >= hold {
            if self.post_commit.load(Ordering::SeqCst) {
                action()?;
            }
            return Err(self
                .failure
                .lock()
                .unwrap()
                .clone()
                .unwrap_or_else(busy_error));
        }
        action()
    }
}

pub struct Timer {
    pub now: Mutex<Instant>,
    pub registrations: AtomicUsize,
    pub waits: AtomicUsize,
}
impl Timer {
    pub fn new() -> Self {
        Self {
            now: Mutex::new(Instant::now()),
            registrations: AtomicUsize::new(0),
            waits: AtomicUsize::new(0),
        }
    }
    pub fn advance(&self, amount: Duration) {
        *self.now.lock().unwrap() += amount;
    }
}
struct Sleep<'a> {
    timer: &'a Timer,
    deadline: Instant,
}
impl Future for Sleep<'_> {
    type Output = ();
    fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<()> {
        if *self.timer.now.lock().unwrap() >= self.deadline {
            Poll::Ready(())
        } else {
            Poll::Pending
        }
    }
}
impl Drop for Sleep<'_> {
    fn drop(&mut self) {
        self.timer.registrations.fetch_sub(1, Ordering::SeqCst);
    }
}
impl PreparationReadWait for Timer {
    fn now(&self) -> Instant {
        *self.now.lock().unwrap()
    }
    fn wait_until(&self, deadline: Instant) -> BoxFuture<'_, ()> {
        self.registrations.fetch_add(1, Ordering::SeqCst);
        self.waits.fetch_add(1, Ordering::SeqCst);
        Box::pin(Sleep {
            timer: self,
            deadline,
        })
    }
}

pub struct ManualClock(pub Mutex<latent_core::ClockSample>);
impl latent_core::ActivationClock for ManualClock {
    fn sample(&self) -> latent_core::ClockSample {
        *self.0.lock().unwrap()
    }
    fn monotonic_now(&self) -> Instant {
        self.0.lock().unwrap().monotonic()
    }
}

pub struct ClockFixture {
    pub base: Fixture,
    pub fence: Arc<Fence>,
    pub clock: HostClock,
    _provider: ProviderRegistration,
}
impl ClockFixture {
    pub fn new(clock: HostClock, limits: CapabilityBrokerLimits, required: bool) -> Self {
        Self::from_base(Fixture::new(limits), clock, required)
    }
    pub fn from_base(mut base: Fixture, clock: HostClock, required: bool) -> Self {
        let digest = format!("sha256:{}", "3".repeat(64));
        for (id, kind, document) in [
            (
                "clock-policy",
                RecordKind::Policy,
                json!({"formatVersion":1,"tenant":"a","rules":[{
                    "id":"allow-clock","effect":"allow","principals":[{"kind":"user","subject":"alice"}],
                    "services":["echo"],"publications":[base.publication.publication().as_str()],
                    "capability":clock.capability(),"operations":[clock.operation()],"resources":{"kind":"clock"},
                    "requireAudit":required,"ceiling":{"operations":1,"inputBytes":0,"outputBytes":8,"wallTimeMillis":5000}
                }]}),
            ),
            (
                "clock-binding",
                RecordKind::ProviderBinding,
                json!({"formatVersion":1,"tenant":"a",
                "capability":clock.capability(),"providerProfile":"clock-fixture-v1",
                "configurationDigest":digest,"configurationEpoch":1,"restriction":{"operations":[]}}),
            ),
        ] {
            base.policies
                .mutate(
                    MutationRequest {
                        tenant: "a",
                        actor: "operator",
                        id,
                        kind,
                        operation_id: id,
                        expected_revision: 0,
                        document: Some(&serde_json::to_vec(&document).unwrap()),
                    },
                    Instant::now() + Duration::from_secs(10),
                    |_| Ok(()),
                )
                .unwrap();
        }
        let provider = base
            .broker
            .register_provider(ProviderConfiguration {
                capability: clock.capability(),
                profile: "clock-fixture-v1",
                configuration_digest: &digest,
                configuration_epoch: 1,
                restriction_json: br#"{"operations":[]}"#,
                minimum_call_charges: &[ProviderBudgetRequirement {
                    operation: clock.operation(),
                    dimension: latent_core::BudgetDimension::CpuFuel,
                    minimum: 100,
                }],
            })
            .unwrap();
        let fence = Arc::new(Fence::default());
        base.plan = base
            .broker
            .compile_invocation_plan(
                &base.revision,
                Some(&latent_core::DeploymentId("clock-deployment".into())),
                &[CapabilityBindingSpec {
                    definition_digest: Some(&latent_artifacts::package::artifact_blob_digest(
                        b"clock fixture",
                    )),
                    provider: &provider.reference(),
                    imported_operations: &[clock.operation().into()],
                    policy_ids: &["clock-policy".into()],
                    provider_binding_id: "clock-binding",
                    deployment_restriction_json: br#"{"operations":[]}"#,
                }],
                &base.publication,
                &[],
                &[],
                &[],
                Some(fence.clone()),
                Instant::now() + Duration::from_secs(10),
            )
            .unwrap();
        Self {
            base,
            fence,
            clock,
            _provider: provider,
        }
    }
    pub fn request(&self) -> (ExecutionRequest, Control) {
        let (mut request, control) = self.base.request("clock-currentness");
        request.imports = vec![BoundImport {
            capability: latent_core::CapabilityId(self.clock.capability().into()),
            contract: self.clock.capability().into(),
            opaque_handle: "not-authority".into(),
        }];
        (request, control)
    }
    pub fn idle(&self, session: &CapabilitySession, before: CapabilityBrokerSnapshot) {
        let after = self.base.broker.snapshot();
        assert_eq!(after, before);
        assert_eq!(session.observer().live_calls(), 0);
        assert_eq!(session.observer().retained_handles(), 0);
    }
    pub fn revoke(&self) {
        self.base
            .policies
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    id: "clock-policy",
                    kind: RecordKind::Policy,
                    operation_id: "revoke-clock",
                    expected_revision: 4,
                    document: None,
                },
                Instant::now() + Duration::from_secs(10),
                |_| Ok(()),
            )
            .unwrap();
    }
}
