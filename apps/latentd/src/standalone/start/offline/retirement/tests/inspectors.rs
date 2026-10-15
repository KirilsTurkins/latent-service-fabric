//! Public inspectors on the actual signed, warm PHASE4 catalog owners.
use super::{Catalogs, NodeSettings, TempDir};
use crate::standalone::{audit::AuditRuntime, StandaloneNode};
use latent_capabilities::broker::io::IoRuntime;
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeCapacityOwner,
    NATIVE_RESERVATION_METADATA_BYTES,
};
use latent_policy::capability::PolicyStore;
use latent_rollout::RolloutHandle;
use std::{cell::RefCell, sync::Arc, time::Instant};

mod fixture;

enum Capture {
    Inactive,
    Armed,
    Observed(Box<Probe>),
}
thread_local! {
    static INSPECTION: RefCell<Capture> = const { RefCell::new(Capture::Inactive) };
}

struct Probe {
    policy: Arc<PolicyStore>,
    audit: AuditRuntime,
    rollout: RolloutHandle,
    sampler: tokio::task::AbortHandle,
    io: Arc<IoRuntime>,
    native: NativeCapacityOwner,
}

pub(in super::super) fn observe(catalogs: &Catalogs, response: &NativeBufferPermit) {
    INSPECTION.with(|capture| {
        let mut capture = capture.borrow_mut();
        if matches!(*capture, Capture::Inactive) {
            return;
        }
        assert!(matches!(*capture, Capture::Armed));
        let policy = catalogs.policies.as_ref().unwrap().handle().store().clone();
        assert_eq!(catalogs.deployments.binding_inventory().2, 1);
        assert!(policy.retained_read_owners() > 0);
        let native = catalogs.state.as_ref().unwrap().native.clone();
        assert!(response.is_from_owner(&native));
        assert_eq!(response.class(), NativeAdmissionClass::Recovery);
        assert_eq!(response.buffer_class(), NativeBufferClass::Response);
        assert_eq!(response.bytes(), 1024 * 1024);
        eprintln!(
            "inspector-report-reached warmBindings=1 policyReaders={} responseBytes={} class=recovery bufferClass=response",
            policy.retained_read_owners(),
            response.bytes(),
        );
        *capture = Capture::Observed(Box::new(Probe {
            policy,
            audit: catalogs.audit.as_ref().unwrap().retirement_observer(),
            rollout: catalogs.rollouts.as_ref().unwrap().handle(),
            sampler: catalogs.control.as_ref().unwrap().task_observer(),
            io: catalogs.providers.as_ref().unwrap().io_observer(),
            native,
        }));
    });
}

fn arm() {
    INSPECTION.with(|capture| {
        assert!(matches!(*capture.borrow(), Capture::Inactive));
        *capture.borrow_mut() = Capture::Armed;
    });
}

fn take() -> Probe {
    INSPECTION.with(|capture| match capture.replace(Capture::Inactive) {
        Capture::Observed(probe) => *probe,
        _ => panic!("actual inspector did not complete its report and capture"),
    })
}

impl Probe {
    async fn finish(&self, deadline: Instant) {
        tokio::time::timeout_at(deadline.into(), async {
            while self.rollout.snapshot().worker_live || !self.sampler.is_finished() {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        let rollout = self.rollout.snapshot();
        assert!(!rollout.failed);
        assert_eq!(rollout.queued_commands, 0);
        assert_eq!(rollout.active_commands, 0);
        assert_eq!(rollout.retained_request_bytes, 0);
        assert_eq!(rollout.response_owners, 0);
        assert_eq!(rollout.response_bytes, 0);
        let audit = self
            .audit
            .shutdown(deadline.saturating_duration_since(Instant::now()))
            .await
            .unwrap();
        assert!(audit.clean());
        assert_eq!(self.policy.retained_read_owners(), 0);
        let io = self.io.snapshot();
        assert_eq!(io.calls, 0);
        assert_eq!(io.occupied_running_slots, 0);
        assert_eq!(io.queued_calls, 0);
        assert_eq!(io.staged_bytes, 0);
        assert_eq!(io.result_bytes, 0);
        assert_eq!(io.buffers, 0);
        assert_eq!(io.streams, 0);
        assert_eq!(io.metadata_bytes, 0);
        eprintln!(
            "inspector-original-owners-retired rolloutLive=false samplerFinished=true auditJoined={} policyReaders=0 ioOwners=0",
            audit.worker_joined,
        );
    }
}

#[tokio::test]
async fn warm_configured_http_inspector_retires_after_graph_drop() {
    let directory = TempDir::new().unwrap();
    let settings = fixture::warm(&directory).await;
    let until = Instant::now() + settings.shutdown_grace();
    arm();
    let result = Box::pin(StandaloneNode::inspect_configured_http_effects(
        settings,
        tokio::runtime::Handle::current(),
    ))
    .await;
    let probe = take();
    probe.finish(until).await;
    if result.is_err() {
        assert!(probe.native.snapshot().unwrap().physically_retired());
    }
    assert!(
        result.is_ok(),
        "warm configured HTTP inspection must succeed after graph retirement"
    );
    let report = result.unwrap();
    assert_eq!(
        report.schema_version,
        "latent.configured-http-effect-inspection.v1"
    );
    assert!(report.adapters.is_empty());
    let encoded = report.encode().unwrap();
    assert_eq!(encoded.reserved_bytes(), 1024 * 1024);
    assert_eq!(probe.native.snapshot().unwrap().recovery.slots, 1);
    assert_eq!(
        probe.native.snapshot().unwrap().recovery.bytes,
        1024 * 1024 + NATIVE_RESERVATION_METADATA_BYTES
    );
    let wire: serde_json::Value = serde_json::from_slice(encoded.get()).unwrap();
    assert_eq!(wire["adapters"], serde_json::json!([]));
    drop(encoded);
    assert!(probe.native.snapshot().unwrap().physically_retired());
}

#[tokio::test]
async fn warm_transaction_host_inspector_retires_after_graph_drop() {
    let directory = TempDir::new().unwrap();
    let settings = fixture::warm(&directory).await;
    let until = Instant::now() + settings.shutdown_grace();
    arm();
    let result = Box::pin(StandaloneNode::inspect_transaction_hosts(
        settings,
        tokio::runtime::Handle::current(),
    ))
    .await;
    let probe = take();
    probe.finish(until).await;
    if result.is_err() {
        assert!(probe.native.snapshot().unwrap().physically_retired());
    }
    assert!(
        result.is_ok(),
        "warm transaction host inspection must succeed after graph retirement"
    );
    let report = result.unwrap();
    assert_eq!(
        report.schema_version,
        "latent.transaction-host-inspection.v1"
    );
    assert_eq!(report.configured_providers.len(), 1);
    assert_eq!(report.configured_transport_callers.len(), 1);
    assert_eq!(report.state_configuration_epoch, 1);
    assert!(report.deferred_http.is_empty());
    let encoded = report.encode().unwrap();
    assert_eq!(encoded.reserved_bytes(), 1024 * 1024);
    assert_eq!(probe.native.snapshot().unwrap().recovery.slots, 1);
    assert_eq!(
        probe.native.snapshot().unwrap().recovery.bytes,
        32 * 1024 + 14 * 1024 * 1024 + NATIVE_RESERVATION_METADATA_BYTES
    );
    let wire: serde_json::Value = serde_json::from_slice(encoded.get()).unwrap();
    assert_eq!(wire["deferredHttp"], serde_json::json!([]));
    drop(encoded);
    assert!(probe.native.snapshot().unwrap().physically_retired());
}
