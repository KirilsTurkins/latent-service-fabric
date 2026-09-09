use std::future::poll_fn;
use std::task::Poll;

use latent_core::{ActivationId, BoxFuture, PlatformErrorCode};
use latent_executor::{
    ExecutionBackend, ExecutionCleanup, ExecutionReport, GuestInterruptionKind, GuestOutcome,
};
use latent_wasmtime::{
    InvocationInputDropReason, InvocationInputObserver, InvocationInputPhase,
    InvocationInputSnapshot, WasmtimeBackend,
};
use serde_json::json;

use super::support::{
    budget, config, idle, prepared, request, returned, run, Cancellation, VALUES, WATCHDOG,
};

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn raw_input_is_gone_at_pending_guest_dispatch_while_native_owners_remain() {
    let (backend, prepared) = prepared(config()).await;
    let observer = backend.invocation_input_observer();
    let ids = [
        "cancel-owner",
        "cancel-followup",
        "drop-owner",
        "drop-followup",
    ]
    .map(|id| ActivationId(id.to_owned()));
    observer.enable(&ids).unwrap();
    for (pair, cancel) in [(0, true), (2, false)] {
        let cancellation = Cancellation::new(&ids[pair].0);
        let mut input = request(
            prepared.clone(),
            &cancellation.id,
            VALUES,
            "spin",
            b"[]",
            budget(),
        );
        input.activation.input = vec![b' '; 64 * 1024];
        input.activation.input[..2].copy_from_slice(b"[]");
        let capacity = u64::try_from(input.activation.input.capacity()).unwrap();
        let mut invocation = backend.invoke_contained(input, &cancellation);
        wait_for_guest_dispatch(&mut invocation, &observer, &cancellation.id).await;
        assert_guest_ownership(&observer.snapshot(), &cancellation.id, capacity, &backend);
        if cancel {
            cancellation.cancel();
            let report = tokio::time::timeout(WATCHDOG, invocation).await.unwrap();
            assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
            assert!(matches!(
                report.outcome.unwrap(),
                GuestOutcome::Interrupted {
                    kind: GuestInterruptionKind::Cancelled,
                    ..
                }
            ));
        } else {
            drop(invocation);
        }
        idle(&backend);
        assert_eq!(backend.active_instance_reservations(), 0);
        assert_eq!(observer.snapshot().live_invocations, 0);
        let followup = Cancellation::new(&ids[pair + 1].0);
        let outcome = run(
            &backend,
            request(
                prepared.clone(),
                &followup.id,
                VALUES,
                "identify",
                b"[]",
                budget(),
            ),
            &followup,
        )
        .await
        .unwrap();
        assert_eq!(returned(outcome), json!([11]));
        idle(&backend);
    }
    let final_snapshot = observer.snapshot();
    assert!(!final_snapshot.overflowed);
    assert_eq!(final_snapshot.started_invocations, 4);
    assert_eq!(final_snapshot.finished_invocations, 3);
    assert_eq!(final_snapshot.dropped_invocations, 1);
    assert_eq!(final_snapshot.live_raw_capacity_bytes, 0);
    backend.release(prepared).await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn invalid_input_precedes_zero_cell_memory_and_early_errors_drop_at_scope_exit() {
    let (backend, prepared) = prepared(config()).await;
    let observer = backend.invocation_input_observer();
    let ids = ["invalid-input-owner", "zero-memory-owner"].map(|id| ActivationId(id.to_owned()));
    observer.enable(&ids).unwrap();
    for (index, payload) in [b"not-json".as_slice(), b"[]".as_slice()]
        .into_iter()
        .enumerate()
    {
        let cancellation = Cancellation::new(&ids[index].0);
        let mut request = request(
            prepared.clone(),
            &cancellation.id,
            VALUES,
            "identify",
            payload,
            budget(),
        );
        request.cell.maximum_memory_bytes = 0;
        let error = run(&backend, request, &cancellation).await.unwrap_err();
        assert_eq!(
            error.code,
            if index == 0 {
                PlatformErrorCode::InvalidArgument
            } else {
                PlatformErrorCode::ResourceExhausted
            }
        );
        if index == 1 {
            assert_eq!(error.message, "effective memory budget is zero");
        }
        let snapshot = observer.snapshot();
        let stages = records(&snapshot, &cancellation.id).collect::<Vec<_>>();
        assert_eq!(
            stages.iter().map(|record| record.phase).collect::<Vec<_>>(),
            [
                InvocationInputPhase::RawOwnerCreated,
                InvocationInputPhase::RawOwnerDropped,
                InvocationInputPhase::InvocationFinished,
            ]
        );
        assert_eq!(
            stages[1].drop_reason,
            Some(InvocationInputDropReason::OwnerScopeExit)
        );
        assert_eq!(snapshot.live_raw_owners, 0);
        assert_eq!(snapshot.live_raw_capacity_bytes, 0);
        assert_eq!(snapshot.live_invocations, 0);
        assert!(!snapshot.overflowed);
        idle(&backend);
        assert_eq!(backend.active_instance_reservations(), 0);
    }
    backend.release(prepared).await.unwrap();
}

fn records<'a>(
    snapshot: &'a InvocationInputSnapshot,
    id: &ActivationId,
) -> impl Iterator<Item = &'a latent_wasmtime::InvocationInputRecord> {
    let token = snapshot
        .identities
        .iter()
        .find(|identity| identity.activation_id == *id)
        .unwrap()
        .token;
    snapshot
        .records
        .iter()
        .filter(move |record| record.token == token)
}

async fn wait_for_guest_dispatch(
    invocation: &mut BoxFuture<'_, ExecutionReport>,
    observer: &InvocationInputObserver,
    id: &ActivationId,
) {
    tokio::time::timeout(
        WATCHDOG,
        poll_fn(|context| {
            let result = invocation.as_mut().poll(context);
            assert!(
                result.is_pending(),
                "spin completed before its dispatch witness: {result:?}"
            );
            let snapshot = observer.snapshot();
            if records(&snapshot, id)
                .any(|record| record.phase == InvocationInputPhase::GuestCallStart)
            {
                Poll::Ready(())
            } else {
                Poll::Pending
            }
        }),
    )
    .await
    .expect("actual guest dispatch and Pending within watchdog");
}

fn assert_guest_ownership(
    snapshot: &InvocationInputSnapshot,
    id: &ActivationId,
    capacity: u64,
    backend: &WasmtimeBackend,
) {
    assert!(!snapshot.overflowed);
    assert_eq!(snapshot.live_invocations, 1);
    assert_eq!(snapshot.live_raw_owners, 0);
    assert_eq!(snapshot.live_raw_capacity_bytes, 0);
    let stages = records(snapshot, id).collect::<Vec<_>>();
    assert_eq!(
        stages.iter().map(|record| record.phase).collect::<Vec<_>>(),
        [
            InvocationInputPhase::RawOwnerCreated,
            InvocationInputPhase::RawOwnerDropped,
            InvocationInputPhase::BeforeCallExport,
            InvocationInputPhase::GuestCallStart,
        ]
    );
    assert_eq!(
        stages[1].drop_reason,
        Some(InvocationInputDropReason::BeforeGuestCall)
    );
    assert_eq!(stages[1].raw_capacity_bytes, Some(capacity));
    assert!(stages
        .windows(2)
        .all(|pair| pair[0].observed_nanos <= pair[1].observed_nanos));
    let resources = backend.resource_snapshot();
    assert_eq!(resources.live_stores, 1);
    assert_eq!(resources.live_host_states, 1);
    assert_eq!(resources.live_component_instances, 1);
    assert_eq!(resources.live_cancellation_probes, 1);
    assert_eq!(backend.active_instance_reservations(), 1);
}
