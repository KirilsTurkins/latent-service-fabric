//! Real transport handoff regression, separate from the fixed measured population.
use std::sync::atomic::Ordering;
use std::time::{Duration, Instant};

use latent_core::ActivationId;
use latent_wasmtime::{InvocationInputObserver, InvocationInputPhase, InvocationInputSnapshot};
use latent_wire::invocation::InvocationServiceClient;
use serde_json::json;

use super::super::{fixtures::Fixture, runtime};
use super::{cold, Node};

const INTERRUPTED: &str = "ownership-supervised-interrupted";
const RECOVERED: &str = "ownership-supervised-recovered";

#[test]
#[ignore = "requires the maintained generic component and real loopback transport"]
fn transferred_backend_input_retires_before_same_cell_reuse() {
    let threads = crate::standalone::RuntimeThreads::default();
    let invocation = runtime(2, &threads.invocation);
    let control = runtime(4, &threads.control);
    invocation.block_on(async {
        tokio::time::timeout(
            Duration::from_secs(15),
            run(
                control.handle().clone(),
                crate::standalone::RuntimeThreads {
                    invocation: threads.invocation.clone(),
                    control: threads.control.clone(),
                },
            ),
        )
        .await
        .expect("supervised input ownership regression watchdog");
    });
    drop(invocation);
    drop(control);
    assert_eq!(threads.invocation.load(Ordering::Acquire), 0);
    assert_eq!(threads.control.load(Ordering::Acquire), 0);
}

async fn run(control: tokio::runtime::Handle, threads: crate::standalone::RuntimeThreads) {
    let data = tempfile::tempdir().unwrap();
    let plan = cold::plan::Plan {
        schema: "latent.optimization.cold-plan.v1".into(),
        profile: "smoke".into(),
        repetition: 1,
        compiler_workers: Some(2),
    };
    let mut config = plan.configuration(data.path());
    config["cells"][0]["capacity"] = json!(1);
    config["cells"][0]["queueCapacity"] = json!(2);
    config["cache"]["preparations"] = json!(2);
    config["credentials"][0]["tenant"] = json!("tests");
    let mut node = Box::pin(Node::start_configured(
        16,
        config,
        Fixture::generic().unwrap(),
        control,
        threads,
        Instant::now(),
    ))
    .await
    .unwrap();
    // Publication is setup for this ownership regression, not a measured offer.
    // Match the existing server/channel cap while keeping invocation deadlines.
    node.publish_with_timeout(Duration::from_secs(5))
        .await
        .unwrap();
    node.published().await.unwrap();
    let observer = node.owner.backend.invocation_input_observer();
    observer
        .enable(&[
            ActivationId(INTERRUPTED.into()),
            ActivationId(RECOVERED.into()),
        ])
        .unwrap();

    interrupt(&mut node, &observer).await;
    let snapshot = observer.snapshot();
    assert_raw_retirement(&snapshot);
    let status = node.status(INTERRUPTED).await.unwrap();
    assert_eq!(status.terminal_state.as_deref(), Some("cancelled"));
    assert_idle(&node);
    let response = node
        .invoke(node.fixture.request("identify", RECOVERED, &json!([])))
        .await
        .unwrap();
    assert_eq!(response.activation_id, RECOVERED);
    let Some(latent_wire::invocation::proto::invoke_response::Result::Success(success)) =
        &response.result
    else {
        panic!("same-cell follow-up did not succeed: {response:?}");
    };
    assert_eq!(success.media_type, super::super::fixtures::MEDIA);
    assert_eq!(success.payload, b"[11]");
    assert_idle(&node);
    assert_eq!(node.work.invoke_attempts, 2);

    let stopped = Box::pin(node.shutdown()).await.unwrap();
    assert!(stopped.clean && stopped.cleanup.driver_joined && !stopped.cleanup.failed);
    assert_eq!(stopped.quarantined_cells, 0);
    assert_eq!(
        (stopped.cleanup.handoffs, stopped.cleanup.completed),
        (1, 1)
    );
    assert_eq!(
        (
            stopped.cleanup.reserved,
            stopped.cleanup.queued,
            stopped.cleanup.running
        ),
        (0, 0, 0)
    );
    let final_input = observer.snapshot();
    assert!(!final_input.overflowed);
    assert_eq!(
        (
            final_input.started_invocations,
            final_input.finished_invocations,
            final_input.dropped_invocations
        ),
        (2, 2, 0)
    );
    assert_eq!(
        (
            final_input.live_invocations,
            final_input.live_raw_owners,
            final_input.live_raw_capacity_bytes
        ),
        (0, 0, 0)
    );
    data.close().unwrap();
}

async fn interrupt(node: &mut Node, observer: &InvocationInputObserver) {
    let mut request = node.fixture.request("spin", INTERRUPTED, &json!([]));
    request.payload.resize(65_536, b' ');
    let budget = request.budget.as_mut().unwrap();
    budget.cpu_fuel = 10_000_000_000;
    budget.wall_time_limit_millis = Some(3000);
    let request = cold::call::auth(request, Duration::from_secs(5)).unwrap();
    node.command(true).unwrap();
    let mut client = InvocationServiceClient::new(node.channel());
    let mut invocation = Box::pin(client.invoke(request));
    tokio::select! {
        result = &mut invocation => panic!("spin returned before actual guest dispatch: {result:?}"),
        () = guest_dispatched(observer) => {}
    }
    let native = node.owner.backend.resource_snapshot();
    assert_eq!(
        (
            native.live_stores,
            native.live_host_states,
            native.live_component_instances,
            native.live_cancellation_probes
        ),
        (1, 1, 1, 1)
    );
    assert_eq!(node.owner.inventory().unwrap().cell_capacity[0].active, 1);
    // Drop the actual RPC future. The separate node owner must retain its
    // original execution future until native cleanup acknowledges interruption.
    drop(invocation);
    drop(client);
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            let cleanup = node.owner.cleanup_snapshot().unwrap();
            if cleanup.completed == 1 && cleanup.reserved + cleanup.queued + cleanup.running == 0 {
                break;
            }
            assert!(
                !cleanup.failed && cleanup.timed_out + cleanup.panicked + cleanup.fallbacks == 0
            );
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .expect("actual transferred continuation was not reclaimed");
}

async fn guest_dispatched(observer: &InvocationInputObserver) {
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            let snapshot = observer.snapshot();
            assert!(!snapshot.overflowed);
            if snapshot
                .records
                .iter()
                .any(|row| row.token == 0 && row.phase == InvocationInputPhase::GuestCallStart)
            {
                return;
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .expect("actual backend guest call was not dispatched");
}

fn assert_raw_retirement(snapshot: &InvocationInputSnapshot) {
    assert!(!snapshot.overflowed);
    let event = |phase| {
        snapshot
            .records
            .iter()
            .find(|row| row.token == 0 && row.phase == phase)
            .unwrap()
    };
    let raw = event(InvocationInputPhase::RawOwnerCreated);
    let before = event(InvocationInputPhase::BeforeCallExport);
    let guest = event(InvocationInputPhase::GuestCallStart);
    let dropped = event(InvocationInputPhase::RawOwnerDropped);
    let finished = event(InvocationInputPhase::InvocationFinished);
    assert_eq!(raw.raw_length_bytes, Some(65_536));
    assert!(raw.raw_capacity_bytes.unwrap() >= 65_536);
    // Both the retained-input control and consuming candidate must keep the
    // same native owners through acknowledgement. The paired collector checks
    // their different raw-buffer lifetimes separately.
    assert!(raw.sequence < before.sequence && before.sequence < guest.sequence);
    assert!(raw.sequence < dropped.sequence && guest.sequence < finished.sequence);
    assert!(dropped.sequence < finished.sequence);
    assert_eq!(
        (
            snapshot.live_invocations,
            snapshot.live_raw_owners,
            snapshot.live_raw_capacity_bytes
        ),
        (0, 0, 0)
    );
}

fn assert_idle(node: &Node) {
    let inventory = node.owner.inventory().unwrap();
    let cells = &inventory.cell_capacity[0];
    assert_eq!(
        (
            cells.total,
            cells.available,
            cells.active,
            cells.quarantined
        ),
        (1, 1, 0, 0)
    );
    let native = node.owner.backend.resource_snapshot();
    assert_eq!(
        (
            native.active_invocations,
            native.live_stores,
            native.live_host_states,
            native.live_component_instances,
            native.live_temporary_buffers,
            native.live_cancellation_probes
        ),
        (0, 0, 0, 0, 0, 0)
    );
}
