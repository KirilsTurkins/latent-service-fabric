use super::*;

const OPTIONS: IoTransferOptions = IoTransferOptions {
    maximum_chunk_bytes: 16,
    maximum_outstanding_chunks: 1,
};
fn cost(input: u64, output: u64) -> CapabilityCallCost {
    CapabilityCallCost::new(32)
        .with_stream_budget(CapabilityStreamBudget::new(input, output).unwrap())
}
fn stream_dispatch(
    session: &CapabilitySession,
    cost: CapabilityCallCost,
) -> Result<ProviderCall, PlatformError> {
    let handle = session.bind(CAP, "read", resource())?;
    let result = session.dispatch(handle, "read", resource(), &[], cost, |call| call);
    session.close_handle(handle).unwrap();
    result
}
async fn call(io: &IoRuntime, session: &CapabilitySession) -> IoCall {
    io.admit(session)
        .unwrap()
        .wait()
        .await
        .unwrap()
        .start(stream_dispatch(session, cost(128, 192)).unwrap())
        .unwrap()
}
fn chunk(transfer: &IoTransfer, n: usize) -> IoOutputChunk {
    let mut buffer = transfer.output_buffer(n).unwrap();
    buffer.spare_mut().unwrap()[..n].fill(b'x');
    buffer.advance_written(n).unwrap();
    buffer.finish().unwrap()
}
#[tokio::test]
async fn transfer_totals_exceed_a_small_window_without_reserving_a_whole_body() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("bulk-window");
    let session = f.session(&request, &control);
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let call = call(&io, &session).await;
    let transfer = call.transfer(OPTIONS).unwrap();
    assert_eq!(f.broker.snapshot().buffer_bytes, 32);
    assert!(call.transfer(OPTIONS).is_err());
    for i in 1..=12 {
        let chunk = chunk(&transfer, 16);
        assert_eq!(chunk.bytes(), [b'x'; 16]);
        assert_eq!(io.snapshot().result_bytes, 16);
        assert_eq!(io.snapshot().staged_bytes, 16); // prepaid lowering copy
        assert!(transfer.output_buffer(1).is_err()); // no read while caller holds the window
        assert_eq!(transfer.accepted_output_bytes(), i * 16);
        drop(chunk);
        assert_eq!(io.snapshot().result_bytes + io.snapshot().staged_bytes, 0);
    }
    let mut extra = transfer.output_buffer(1).unwrap();
    extra.spare_mut().unwrap()[0] = b'!';
    extra.advance_written(1).unwrap();
    assert!(extra.finish().is_err());
    assert_eq!(transfer.accepted_output_bytes(), 192);
    drop(transfer);
    assert!(call.transfer(OPTIONS).is_err()); // Drop cannot reset cumulative permission
    drop(call);
    drop(session);
    assert_eq!(io.snapshot(), IoSnapshot::default());
}
#[tokio::test]
async fn upload_window_counts_actual_capacity_and_never_refunds_accepted_totals() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("bulk-input");
    let session = f.session(&request, &control);
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let call = call(&io, &session).await;
    let transfer = call.transfer(OPTIONS).unwrap();
    let mut oversized = Vec::with_capacity(32);
    oversized.push(1);
    assert!(transfer.input(oversized).is_err());
    for i in 1..=8 {
        let input = transfer.input(vec![b'a'; 16]).unwrap();
        assert_eq!(input.as_ref(), [b'a'; 16]);
        assert_eq!(io.snapshot().staged_bytes, 16);
        assert!(transfer.input(vec![0]).is_err());
        assert_eq!(transfer.accepted_input_bytes(), i * 16);
        drop(input);
        assert_eq!(io.snapshot().staged_bytes, 0);
    }
    assert!(transfer.input(vec![0]).is_err());
    assert_eq!(transfer.accepted_input_bytes(), 128);
    assert_eq!(io.snapshot().staged_bytes, 0);
    drop((transfer, call, session));
    assert_eq!(io.snapshot(), IoSnapshot::default());
}
#[tokio::test]
async fn dropped_store_and_body_keep_already_owned_chunks_charged() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("bulk-drop");
    let session = f.session(&request, &control);
    let observer = session.observer();
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let call = call(&io, &session).await;
    let transfer = call.transfer(OPTIONS).unwrap();
    let chunk = chunk(&transfer, 16);
    drop((transfer, call, session));
    assert!(!observer.is_quiescent());
    assert_eq!(io.snapshot().streams, 1);
    assert_eq!(io.snapshot().result_bytes, 16);
    assert_eq!(io.snapshot().staged_bytes, 16);
    assert_eq!(chunk.bytes(), [b'x'; 16]);
    drop(chunk);
    assert!(observer.is_quiescent());
    assert_eq!(io.snapshot(), IoSnapshot::default());
}
#[tokio::test]
async fn buffered_calls_and_smaller_io_limits_cannot_mint_transfer_permission() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("bulk-closed");
    let session = f.session(&request, &control);
    let io = IoRuntime::new(IoLimits {
        maximum_stream_bytes: 64,
        ..IoLimits::default()
    })
    .unwrap();
    let buffered = start(&io, &session).await;
    assert!(buffered.transfer(OPTIONS).is_err());
    drop(buffered);
    let call = call(&io, &session).await;
    assert!(call.transfer(OPTIONS).is_err());
    assert_eq!(io.snapshot().streams, 0);
    drop((call, session));
    assert_eq!(io.snapshot(), IoSnapshot::default());
}
#[test]
fn policy_and_node_ceilings_check_total_bytes_before_accepting_a_stream() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("bulk-policy");
    let session = f.session(&request, &control);
    // Inline output alone is 32 and would fit. Total 32+240 exceeds this
    // independently configured policy's 256-byte output limit.
    assert_eq!(
        stream_dispatch(&session, cost(128, 240))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(f.broker.snapshot().buffer_bytes, 0);
    let small = Fixture::new(CapabilityBrokerLimits {
        maximum_stream_input_bytes: 64,
        ..CapabilityBrokerLimits::default()
    });
    let (request, control) = small.request("bulk-node");
    let session = small.session(&request, &control);
    assert_eq!(
        stream_dispatch(&session, cost(128, 192))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(small.broker.snapshot().buffer_bytes, 0);
}
