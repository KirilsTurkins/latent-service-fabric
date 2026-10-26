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
    let shell = OperationOwner::allocation_bytes()
        .unwrap()
        .checked_add(PreparedRunningCall::<ProviderCall>::allocation_bytes().unwrap())
        .unwrap();
    assert!(shell <= OPERATION_METADATA as u64);
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

fn native_request(fixture: &Fixture, id: &str) -> (latent_executor::ExecutionRequest, Control) {
    let (mut request, mut control) = fixture.request(id);
    let profile = latent_core::BudgetProfile::Phase3;
    let grant = EffectiveActivationBudget::admit_profile_at(
        profile,
        &request.budget,
        &request.budget,
        &request.budget,
        None,
        ClockSample::system_now(),
    )
    .unwrap();
    control.budget = ActivationBudget::with_profile(grant, profile).unwrap();
    request.activation.deadline_unix_millis = control.budget.deadline().unix_millis();
    (request, control)
}

#[tokio::test]
async fn native_operation_preparation_refuses_each_backing_without_dispatch_or_node_leak() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = native_request(&fixture, "native-io-refusal");
    let session = fixture.session(&request, &control);
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let baseline = control.budget.host_memory_bytes();
    let reservations = control.budget.outstanding_reservations();
    let broker = fixture.broker.snapshot();
    let shared = OperationOwner::allocation_bytes().unwrap();
    let body = PreparedRunningCall::<ProviderCall>::allocation_bytes().unwrap();
    assert!(shared > 0 && body > 0 && shared + body <= OPERATION_METADATA as u64);
    // First refusal targets shared backing; second allows it and refuses only
    // the later body. The original1MiB grant is short by exactly ONE byte.
    for needed in [shared, shared + body] {
        let held = request.budget.memory_bytes - baseline - needed + 1;
        let padding = control.budget.reserve_host_memory(held).unwrap();
        let error = io.admit(&session).err().unwrap();
        assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
        assert_eq!(io.snapshot(), IoSnapshot::default());
        assert_eq!(fixture.broker.snapshot(), broker);
        assert_eq!(control.budget.host_memory_bytes(), baseline + held);
        assert_eq!(control.budget.outstanding_reservations(), reservations + 1);
        drop(padding);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(control.budget.outstanding_reservations(), reservations);
    }
    let admission = io.admit(&session).unwrap();
    assert_eq!(control.budget.host_memory_bytes(), baseline + shared + body);
    drop(admission); // never dispatched; running body was never allocated
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    assert_eq!(io.snapshot(), IoSnapshot::default());
    let (foreign_request, foreign_control) = native_request(&fixture, "native-io-foreign");
    let foreign = fixture.session(&foreign_request, &foreign_control);
    let foreign_bytes = foreign_control.budget.host_memory_bytes();
    let foreign_guards = foreign_control.budget.outstanding_reservations();
    let ready = io.admit(&session).unwrap().wait().await.unwrap();
    assert!(ready.start(dispatch(&foreign)).is_err());
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    assert_eq!(control.budget.outstanding_reservations(), reservations);
    assert_eq!(foreign_control.budget.host_memory_bytes(), foreign_bytes);
    assert_eq!(
        foreign_control.budget.outstanding_reservations(),
        foreign_guards
    );
    assert_eq!(io.snapshot(), IoSnapshot::default());
    let call = start(&io, &session).await;
    drop(call);
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    assert_eq!(control.budget.outstanding_reservations(), reservations);
    assert_eq!(io.snapshot(), IoSnapshot::default());
}

#[tokio::test]
async fn native_operation_running_buffer_and_last_weak_keep_full_backing_paid() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = native_request(&fixture, "native-io-lifetime");
    let session = fixture.session(&request, &control);
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let baseline = control.budget.host_memory_bytes();
    let reservations = control.budget.outstanding_reservations();
    let shared = OperationOwner::allocation_bytes().unwrap();
    let body = PreparedRunningCall::<ProviderCall>::allocation_bytes().unwrap();
    let admission = io.admit(&session).unwrap();
    let stop = admission.stop_handle();
    let late = stop.clone();
    assert_eq!(control.budget.host_memory_bytes(), baseline + shared + body);
    assert_eq!(control.budget.outstanding_reservations(), reservations + 2);
    assert_eq!(stop.phase(), IoWorkPhase::Queued);
    let ready = admission.wait().await.unwrap();
    assert_eq!(stop.phase(), IoWorkPhase::Ready);
    let provider = dispatch(&session);
    let admitted = control.budget.host_memory_bytes();
    let count = control.budget.outstanding_reservations();
    let call = ready.start(provider).unwrap();
    assert_eq!(stop.phase(), IoWorkPhase::Running);
    assert_eq!(control.budget.host_memory_bytes(), admitted);
    assert_eq!(control.budget.outstanding_reservations(), count);
    {
        let state = call.operation.execution.lock().unwrap();
        assert!(state.running_backing.is_none());
        let Authority::Running(call) = &state.authority else {
            panic!("running owner")
        };
        assert_eq!(call.allocation.as_ref().unwrap().bytes(), body);
        assert!(call
            .allocation
            .as_ref()
            .unwrap()
            .is_from_budget(&control.budget));
    }
    let retained = buffer(&call, b"physical owner", 64);
    let lease = call.lease();
    stop.stop();
    assert_eq!(
        call.wait_for(std::future::pending::<()>())
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::Cancelled
    );
    drop(call);
    assert_eq!(stop.phase(), IoWorkPhase::Cleaning);
    assert!(control.budget.host_memory_bytes() >= baseline + shared + body);
    drop(retained);
    assert_eq!(io.snapshot().calls, 1); // the existing provider lease is real work
    assert!(lease.checkpoint().is_err());
    drop(lease);
    assert_eq!(stop.phase(), IoWorkPhase::Retired);
    assert_eq!(io.snapshot(), IoSnapshot::default()); // existing logical node quota
                                                      // Dead T does NOT shrink the Arc allocation. FULL backing + billing stay
                                                      // paid until its actual final Weak, not just size_of(header).
    assert_eq!(control.budget.host_memory_bytes(), baseline + shared);
    assert_eq!(control.budget.outstanding_reservations(), reservations + 1);
    assert!(stop.checkpoint().is_err());
    drop(stop);
    assert_eq!(control.budget.host_memory_bytes(), baseline + shared);
    drop(late);
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    assert_eq!(control.budget.outstanding_reservations(), reservations);
    let fresh = start(&io, &session).await;
    drop(fresh);
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    assert_eq!(io.snapshot(), IoSnapshot::default());
}

#[test]
fn native_running_box_cleanup_is_physical_first_and_unwind_conservative() {
    use std::sync::atomic::AtomicUsize;
    #[repr(align(256))]
    struct Value {
        budget: ActivationBudget,
        drops: Arc<AtomicUsize>,
        panic: bool,
    }
    impl Drop for Value {
        fn drop(&mut self) {
            assert_eq!(self as *const Self as usize % 256, 0);
            assert_eq!(
                self.budget.host_memory_bytes(),
                PreparedRunningCall::<Self>::allocation_bytes().unwrap()
            );
            self.drops.fetch_add(1, Ordering::SeqCst);
            assert!(!self.panic, "original running body destructor");
        }
    }
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    for mode in 0..3 {
        let (_, control) = native_request(&fixture, "native-box-drop");
        let budget = control.budget.clone();
        let drops = Arc::new(AtomicUsize::new(0));
        let prepared = PreparedRunningCall::<Value>::reserve(&budget).unwrap();
        let bytes = PreparedRunningCall::<Value>::allocation_bytes().unwrap();
        assert_eq!(Layout::new::<Value>().align(), 256);
        assert_eq!(budget.host_memory_bytes(), bytes);
        assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, 0);
        let owner = prepared.finish(Value {
            budget: budget.clone(),
            drops: drops.clone(),
            panic: mode == 2,
        });
        assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, bytes);
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(move || {
            let actual_body = owner;
            if mode == 1 {
                panic!("unrelated caller unwind");
            }
            drop(actual_body);
        }));
        assert_eq!(result.is_err(), mode != 0);
        assert_eq!(drops.load(Ordering::SeqCst), 1);
        if mode == 2 {
            assert_eq!(budget.host_memory_bytes(), bytes); // SAME uncertain guard
            assert_eq!(budget.outstanding_reservations(), 1);
        } else {
            assert_eq!(budget.host_memory_bytes(), 0);
            assert_eq!(budget.outstanding_reservations(), 0);
        }
    }
    let (_, control) = native_request(&fixture, "native-box-zst");
    let owner = PreparedRunningCall::<()>::reserve(&control.budget)
        .unwrap()
        .finish(());
    assert_eq!(control.budget.host_memory_bytes(), 0);
    drop(owner);
    let (_, legacy) = fixture.request("legacy-box");
    let owner = PreparedRunningCall::<u64>::reserve(&legacy.budget)
        .unwrap()
        .finish(42);
    assert_eq!(*owner, 42);
    assert!(owner.allocation.is_none());
    drop(owner);
    assert_eq!(legacy.budget.host_memory_bytes(), 0);
}
