use super::super::tests::fixture::*;
use super::super::*;
use super::*;
use latent_core::{ActivationBudget, ClockSample, EffectiveActivationBudget};

fn dispatch(session: &CapabilitySession) -> ProviderCall {
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let call = session
        .dispatch(
            handle,
            "read",
            resource(),
            &[],
            CapabilityCallCost::new(128),
            |call| call,
        )
        .unwrap();
    session.close_handle(handle).unwrap();
    call
}
async fn start(io: &IoRuntime, session: &CapabilitySession) -> IoCall {
    io.admit(session)
        .unwrap()
        .wait()
        .await
        .unwrap()
        .start(dispatch(session))
        .unwrap()
}
fn buffer(call: &IoCall, content: &[u8], size: usize) -> IoBuffer {
    let mut buffer = call.buffer(size, 16).unwrap();
    buffer.spare_mut().unwrap()[..content.len()].copy_from_slice(content);
    buffer.advance_written(content.len()).unwrap();
    buffer
}

#[tokio::test]
async fn partial_consumers_retain_capacity_and_original_activation_after_close() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = fixture.request("partial");
    let session = fixture.session(&request, &control);
    let observer = session.observer();
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let call = start(&io, &session).await;
    let (mut writer, mut reader) = call.stream(1).unwrap();
    writer.write(buffer(&call, b"abcdef", 32)).await.unwrap();
    writer.finish(IoStreamTerminal::Eof);
    let mut chunk = reader.read().await.unwrap().unwrap();
    chunk.consume(2).unwrap();
    assert_eq!(chunk.bytes(), b"cdef");
    assert!(reader.read().await.unwrap().is_none());
    reader.close();
    drop(call);
    drop(session);
    assert_eq!(io.snapshot().result_bytes, chunk.capacity());
    assert_eq!(io.snapshot().streams, 1);
    assert_eq!(io.snapshot().calls, 1);
    assert!(!observer.is_quiescent());
    drop(chunk);
    assert_eq!(io.snapshot(), IoSnapshot::default());
    assert!(observer.is_quiescent());
}

#[tokio::test]
async fn bounded_ring_backpressures_without_spawning_and_preserves_order() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = fixture.request("backpressure");
    let session = fixture.session(&request, &control);
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let call = start(&io, &session).await;
    let (mut writer, mut reader) = call.stream(1).unwrap();
    writer.write(buffer(&call, b"one", 16)).await.unwrap();
    let mut blocked = Box::pin(writer.write(buffer(&call, b"two", 16)));
    pending(blocked.as_mut());
    assert_eq!(io.snapshot().result_bytes, 32);
    let first = reader.read().await.unwrap().unwrap();
    blocked.await.unwrap();
    writer.finish(IoStreamTerminal::Eof);
    let second = reader.read().await.unwrap().unwrap();
    assert_eq!(first.bytes(), b"one");
    assert_eq!(second.bytes(), b"two");
    assert!(reader.read().await.unwrap().is_none());
    drop((first, second, reader, call));
    assert_eq!(io.snapshot(), IoSnapshot::default());
}

#[tokio::test]
async fn queue_is_finite_fair_and_retains_staging_when_waiter_is_dropped() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = fixture.request("queue");
    let session = fixture.session(&request, &control);
    let observer = session.observer();
    let io = IoRuntime::new(IoLimits {
        maximum_running_calls: 1,
        maximum_queued_calls: 2,
        ..IoLimits::default()
    })
    .unwrap();
    let call = start(&io, &session).await;
    let first = io.admit(&session).unwrap();
    let second = io.admit(&session).unwrap();
    assert_eq!(
        io.admit(&session).err().unwrap().code,
        PlatformErrorCode::ResourceExhausted
    );
    let staged = second.input(64, 12).unwrap();
    let mut first = Box::pin(first.wait());
    let mut second = Box::pin(second.wait());
    pending(first.as_mut());
    pending(second.as_mut());
    drop(call);
    pending(second.as_mut()); // second cannot jump the first queued waiter
    let ready = first.await.unwrap();
    assert_eq!(io.snapshot().queued_calls, 1);
    drop(second);
    drop(ready);
    drop(session);
    assert_eq!(io.snapshot().staged_bytes, 64);
    assert_eq!(io.snapshot().queued_calls, 1);
    assert!(!observer.is_quiescent());
    drop(staged);
    assert!(observer.is_quiescent());
    assert_eq!(io.snapshot(), IoSnapshot::default());
}

#[tokio::test]
async fn result_limit_metadata_and_actual_capacity_are_independent() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = fixture.request("bytes");
    let session = fixture.session(&request, &control);
    let io = IoRuntime::new(IoLimits {
        maximum_chunk_bytes: 32,
        maximum_result_bytes: 32,
        ..IoLimits::default()
    })
    .unwrap();
    let call = start(&io, &session).await;
    let retained = buffer(&call, b"x", 32).retain().unwrap();
    assert_eq!(io.snapshot().result_bytes, 32); // length 1 still costs capacity 32
    assert!(buffer(&call, b"y", 32).retain().is_err());
    assert_eq!(io.snapshot().staged_bytes, 0);
    assert_eq!(io.snapshot().result_bytes, 32);
    assert!(call.buffer(33, 0).is_err());
    assert!(call.buffer(1, usize::MAX).is_err());
    assert_eq!(io.snapshot().buffers, 1);
    drop((retained, call));
    assert_eq!(io.snapshot(), IoSnapshot::default());
}

#[tokio::test]
async fn stopped_caller_does_not_retire_actual_blocking_work_or_refund_buffers() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = fixture.request("worker");
    let session = fixture.session(&request, &control);
    let observer = session.observer();
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let call = start(&io, &session).await;
    let stop = call.stop_handle();
    let data = buffer(&call, b"owned by worker", 64);
    let (release, wait) = std::sync::mpsc::sync_channel(1);
    // One deterministic existing-worker stand-in; the production I/O module
    // creates no threads and requires moving the lease into such a bounded job.
    let worker = std::thread::spawn(move || {
        wait.recv().unwrap();
        assert!(call.checkpoint().is_err());
        drop(data);
        drop(call);
    });
    stop.stop();
    io.retire();
    drop(session);
    assert_eq!(io.snapshot().staged_bytes, 64);
    assert!(!observer.is_quiescent());
    release.send(()).unwrap();
    worker.join().unwrap();
    assert!(observer.is_quiescent());
    assert_eq!(io.snapshot(), IoSnapshot::default());
}

#[tokio::test]
async fn revocation_during_queue_denies_final_dispatch_and_foreign_session_is_rejected() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = fixture.request("queued-policy");
    let session = fixture.session(&request, &control);
    let io = IoRuntime::new(IoLimits {
        maximum_running_calls: 1,
        ..IoLimits::default()
    })
    .unwrap();
    let ready = io.admit(&session).unwrap().wait().await.unwrap();
    let (other_request, other_control) = fixture.request("other");
    let other = fixture.session(&other_request, &other_control);
    assert!(ready.start(dispatch(&other)).is_err());
    let running = start(&io, &session).await;
    let mut waiting = Box::pin(io.admit(&session).unwrap().wait());
    pending(waiting.as_mut());
    fixture.revoke_policy();
    drop(running);
    let ready = waiting.await.unwrap();
    assert!(session.bind(CAP, "read", resource()).is_err());
    drop(ready);
    assert_eq!(io.snapshot(), IoSnapshot::default());
}

#[tokio::test]
async fn terminal_partial_error_oversize_close_and_cross_activation_streams() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = fixture.request("stream-terminal");
    let session = fixture.session(&request, &control);
    let io = IoRuntime::new(IoLimits {
        maximum_stream_bytes: 3,
        ..IoLimits::default()
    })
    .unwrap();
    let call = start(&io, &session).await;
    let other = start(&io, &session).await;
    let (mut writer, mut reader) = call.stream(2).unwrap();
    assert!(writer.write(buffer(&other, b"x", 8)).await.is_err());
    writer.write(buffer(&call, b"abc", 8)).await.unwrap();
    assert!(writer.write(buffer(&call, b"d", 8)).await.is_err());
    assert_eq!(reader.terminal(), Some(IoStreamTerminal::TooLarge));
    assert_eq!(reader.read().await.unwrap().unwrap().bytes(), b"abc");
    assert_eq!(
        reader.read().await.err().unwrap().code,
        PlatformErrorCode::ResourceExhausted
    );
    drop((writer, reader));
    let (writer, mut reader) = call.stream(1).unwrap();
    drop(writer);
    assert!(reader.read().await.is_err());
    assert_eq!(reader.terminal(), Some(IoStreamTerminal::Uncertain));
    drop(reader);
    let (mut writer, reader) = call.stream(1).unwrap();
    reader.close();
    assert!(writer.write(buffer(&call, b"x", 8)).await.is_err());
    drop((writer, call, other));
    assert_eq!(io.snapshot(), IoSnapshot::default());
}

#[tokio::test]
async fn cancellation_during_delivery_wakes_writer_and_keeps_delivered_consumer() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = fixture.request("delivery-stop");
    let session = fixture.session(&request, &control);
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let call = start(&io, &session).await;
    let (mut writer, mut reader) = call.stream(1).unwrap();
    writer.write(buffer(&call, b"delivered", 16)).await.unwrap();
    let delivered = reader.read().await.unwrap().unwrap();
    writer.write(buffer(&call, b"queued", 16)).await.unwrap();
    let mut blocked = Box::pin(writer.write(buffer(&call, b"waiting", 16)));
    pending(blocked.as_mut());
    call.stop_handle().stop();
    assert_eq!(
        blocked.await.err().unwrap().code,
        PlatformErrorCode::Cancelled
    );
    assert_eq!(
        reader.read().await.err().unwrap().code,
        PlatformErrorCode::Cancelled
    );
    drop((writer, reader, call));
    assert_eq!(io.snapshot().result_bytes, 16);
    drop(delivered);
    assert_eq!(io.snapshot(), IoSnapshot::default());
}

#[tokio::test]
async fn queue_age_and_node_retirement_wake_without_extending_original_deadline() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = fixture.request("expiry");
    let session = fixture.session(&request, &control);
    let io = IoRuntime::new(IoLimits {
        maximum_running_calls: 1,
        maximum_queue_wait: Duration::from_millis(50),
        ..IoLimits::default()
    })
    .unwrap();
    let call = start(&io, &session).await;
    let deadline = call.deadline();
    assert_eq!(
        io.admit(&session).unwrap().wait().await.err().unwrap().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(call.deadline(), deadline);
    let mut queued = Box::pin(io.admit(&session).unwrap().wait());
    pending(queued.as_mut());
    io.retire();
    assert_eq!(
        queued.await.err().unwrap().code,
        PlatformErrorCode::Unavailable
    );
    assert!(io.admit(&session).is_err());
    drop(call);
    assert_eq!(io.snapshot(), IoSnapshot::default());
}

#[tokio::test]
async fn waiting_transitions_keep_slots_and_timeout_is_not_restarted() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = fixture.request("waiting-phase");
    let session = fixture.session(&request, &control);
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let until = Instant::now() + Duration::from_secs(1);
    let admission = io.admit_until(&session, until).unwrap();
    let stop = admission.stop_handle();
    assert_eq!(stop.phase(), IoWorkPhase::Queued);
    let ready = admission.wait().await.unwrap();
    assert_eq!(stop.phase(), IoWorkPhase::Ready);
    let call = ready.start(dispatch(&session)).unwrap();
    assert_eq!(call.deadline(), until);
    assert_eq!(stop.phase(), IoWorkPhase::Running);
    let mut waiting = Box::pin(call.wait_for(std::future::pending::<()>()));
    pending(waiting.as_mut());
    assert_eq!(stop.phase(), IoWorkPhase::WaitingProvider);
    assert_eq!(io.snapshot().occupied_running_slots, 1);
    assert_eq!(
        waiting.await.err().unwrap().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(call.deadline(), until);
    assert_eq!(stop.phase(), IoWorkPhase::Running);
    drop(call);
    assert_eq!(stop.phase(), IoWorkPhase::Retired);
    assert_eq!(io.snapshot(), IoSnapshot::default());
    let widening = control.budget.deadline().monotonic().unwrap() + Duration::from_secs(1);
    assert!(io.admit_until(&session, widening).is_err());
    assert!(io.admit_until(&session, Instant::now()).is_err());
    assert_eq!(io.snapshot(), IoSnapshot::default());
}

#[tokio::test]
async fn unwinding_work_and_dropping_runtime_keep_only_actual_retained_owners() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = fixture.request("unwind");
    let session = fixture.session(&request, &control);
    let observer = session.observer();
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let call = start(&io, &session).await;
    let stop = call.stop_handle();
    let bytes = buffer(&call, b"retained", 32).retain().unwrap();
    let failed = std::panic::catch_unwind(std::panic::AssertUnwindSafe(move || {
        let _actual_work = call;
        panic!("deterministic provider panic");
    }));
    assert!(failed.is_err());
    assert_eq!(stop.phase(), IoWorkPhase::Cleaning);
    assert_eq!(io.snapshot().result_bytes, 32);
    drop(io);
    drop(session);
    assert!(!observer.is_quiescent());
    drop(bytes);
    assert_eq!(stop.phase(), IoWorkPhase::Retired);
    assert!(observer.is_quiescent());
}

#[test]
fn all_limit_dimensions_have_finite_hard_ceilings() {
    assert!(IoRuntime::new(IoLimits {
        maximum_running_calls: 0,
        ..IoLimits::default()
    })
    .is_err());
    assert!(IoRuntime::new(IoLimits {
        maximum_queued_calls: usize::MAX,
        ..IoLimits::default()
    })
    .is_err());
    assert!(IoRuntime::new(IoLimits {
        maximum_metadata_bytes: usize::MAX,
        ..IoLimits::default()
    })
    .is_err());
    assert!(IoRuntime::new(IoLimits {
        maximum_stream_chunks: usize::MAX,
        ..IoLimits::default()
    })
    .is_err());
    assert!(IoRuntime::new(IoLimits {
        maximum_stream_bytes: u64::MAX,
        ..IoLimits::default()
    })
    .is_err());
    assert!(IoRuntime::new(IoLimits {
        maximum_queue_wait: Duration::ZERO,
        ..IoLimits::default()
    })
    .is_err());
}

#[tokio::test]
async fn output_across_streams_obeys_the_original_call_ceiling_without_refunding_permission() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = fixture.request("output-ceiling");
    let session = fixture.session(&request, &control);
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let admission = io.admit(&session).unwrap();
    let mut staged = admission.input(8, 0).unwrap();
    staged.spare_mut().unwrap()[0] = 7;
    staged.advance_written(1).unwrap();
    assert!(staged.retain().is_err()); // queue ownership grants no output authority
    let ready = admission.wait().await.unwrap();
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let provider = session
        .dispatch(
            handle,
            "read",
            resource(),
            &[],
            CapabilityCallCost::new(3),
            |call| call,
        )
        .unwrap();
    session.close_handle(handle).unwrap();
    let call = ready.start(provider).unwrap();
    let (mut first, mut reader) = call.stream(1).unwrap();
    first.write(buffer(&call, b"abc", 16)).await.unwrap();
    drop(reader.read().await.unwrap().unwrap());
    assert_eq!(io.snapshot().result_bytes, 0);
    let (mut second, other_reader) = call.stream(1).unwrap();
    assert!(second.write(buffer(&call, b"d", 16)).await.is_err());
    assert_eq!(io.snapshot().result_bytes, 0);
    assert_eq!(io.snapshot().staged_bytes, 0);
    drop((first, second, reader, other_reader, call));
    assert_eq!(io.snapshot(), IoSnapshot::default());
}

#[test]
fn an_unbounded_store_deadline_cannot_admit_host_io() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (mut request, mut control) = fixture.request("unbounded");
    request.budget.wall_time_limit_millis = None;
    request.activation.budget = request.budget.clone();
    request.activation.deadline_unix_millis = None;
    control.budget = ActivationBudget::new(
        EffectiveActivationBudget::admit_at(
            &request.budget,
            &request.budget,
            &request.budget,
            None,
            ClockSample::system_now(),
        )
        .unwrap(),
    );
    let session = fixture.session(&request, &control);
    let observer = session.observer();
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    assert_eq!(
        io.admit(&session).err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(io.snapshot(), IoSnapshot::default());
    drop(session);
    assert!(observer.is_quiescent());
}

#[tokio::test]
async fn retiring_the_broker_wakes_existing_queues_and_denies_new_waiters() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = fixture.request("retired-broker");
    let session = fixture.session(&request, &control);
    let io = IoRuntime::new(IoLimits {
        maximum_running_calls: 1,
        ..IoLimits::default()
    })
    .unwrap();
    let call = start(&io, &session).await;
    let mut waiting = Box::pin(io.admit(&session).unwrap().wait());
    pending(waiting.as_mut());
    fixture.broker.retire();
    assert!(io.admit(&session).is_err());
    assert!(tokio::time::timeout(Duration::from_secs(2), waiting)
        .await
        .unwrap()
        .is_err());
    assert_eq!(io.snapshot().calls, 1);
    drop(call);
    assert_eq!(io.snapshot(), IoSnapshot::default());
}

mod transfer;
