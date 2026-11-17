use super::*;
use crate::broker::http::{HttpBodyOwner, HttpError, HttpMethod, HttpOwnedRequest, HttpRequest};
use std::sync::Arc;

fn request(memory: IoMemory, bytes: &[u8]) -> HttpOwnedRequest {
    HttpOwnedRequest::preallocated(
        HttpRequest {
            method: HttpMethod::Post,
            url: "https://example.invalid/".into(),
            headers: Vec::new(),
            body: Some(bytes.to_vec()),
            body_media_type: None,
            idempotency_key: None,
            timeout_millis: None,
        },
        Arc::new(memory),
    )
}

fn charge() -> usize {
    bytes::Bytes::owner_with_retirement_allocation_size::<HttpBodyOwner, HttpInputRetirement>() + 64
}

#[tokio::test]
async fn buffered_body_keeps_original_native_and_node_charges_through_last_clone() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (input, control) = native_request(&fixture, "buffered-body-owner");
    let session = fixture.session(&input, &control);
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let call = start(&io, &session).await;
    let base = control.budget.host_memory_bytes();
    let snapshot = io.snapshot();
    let mut request = request(call.reserve_scratch(64, 64).unwrap(), b"resident");
    let body = request.take_body();
    drop(request);
    let before = io.snapshot();
    let bytes = body.into_http_bytes().unwrap();
    let expected = charge();
    eprintln!(
        "buffered HTTP owner Box={}, charge={expected}",
        expected - 64
    );
    #[cfg(all(target_arch = "x86_64", target_os = "linux"))]
    assert_eq!(expected, 176);
    assert_eq!(control.budget.host_memory_bytes(), base + expected as u64);
    assert_eq!(
        io.snapshot().metadata_bytes,
        before.metadata_bytes + expected
    );
    let clone = bytes.clone();
    drop(bytes);
    assert_eq!(&clone[..], b"resident");
    assert_eq!(control.budget.host_memory_bytes(), base + expected as u64);
    drop(clone);
    assert_eq!(control.budget.host_memory_bytes(), base);
    assert_eq!(io.snapshot(), snapshot);
}

#[tokio::test]
async fn buffered_body_refuses_original_host_and_node_exhaustion_before_publication() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (input, control) = native_request(&fixture, "buffered-body-refusal");
    let session = fixture.session(&input, &control);
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let call = start(&io, &session).await;
    let base = control.budget.host_memory_bytes();
    let snapshot = io.snapshot();
    let expected = charge();

    let mut first = request(call.reserve_scratch(64, 64).unwrap(), b"data");
    let body = first.take_body();
    drop(first);
    let held = input.budget.memory_bytes - base - expected as u64 + 1;
    let padding = control.budget.reserve_host_memory(held).unwrap();
    assert_eq!(
        body.into_http_bytes().err(),
        Some(HttpError::BudgetExhausted)
    );
    assert_eq!(control.budget.host_memory_bytes(), base + held);
    assert_eq!(io.snapshot(), snapshot);
    drop(padding);

    let mut second = request(call.reserve_scratch(64, 64).unwrap(), b"data");
    let body = second.take_body();
    drop(second);
    let padding = call
        .operation
        .runtime
        .counters
        .acquire(
            super::super::Kind::Metadata,
            IoLimits::default().maximum_metadata_bytes - io.snapshot().metadata_bytes - expected
                + 1,
        )
        .unwrap();
    assert_eq!(
        body.into_http_bytes().err(),
        Some(HttpError::BudgetExhausted)
    );
    assert_eq!(control.budget.host_memory_bytes(), base);
    drop(padding);
    assert_eq!(io.snapshot(), snapshot);
}

#[tokio::test]
async fn buffered_body_keeps_phase1_logical_path_and_rejects_foreign_session() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (input, control) = fixture.request("buffered-body-phase1");
    assert!(!control.budget.profile().supports_descendants());
    let session = fixture.session(&input, &control);
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let call = start(&io, &session).await;
    let snapshot = io.snapshot();
    let memory = call.reserve_scratch(64, 64).unwrap();
    let (foreign_input, foreign_control) = fixture.request("buffered-body-foreign");
    let foreign = fixture.session(&foreign_input, &foreign_control);
    assert_eq!(
        memory
            .reserve_http_body_owner(Some(&foreign.core), charge())
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    let mut request = request(memory, b"old");
    let body = request.take_body();
    drop(request);
    let before = io.snapshot();
    let bytes = body.into_http_bytes().unwrap();
    assert_eq!(&bytes[..], b"old");
    assert_eq!(io.snapshot(), before);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    drop(bytes);
    assert_eq!(io.snapshot(), snapshot);
}

#[tokio::test]
async fn buffered_body_preserves_finalized_budget_refusal() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (input, control) = native_request(&fixture, "buffered-body-finalized");
    let session = fixture.session(&input, &control);
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let call = start(&io, &session).await;
    let snapshot = io.snapshot();
    let mut request = request(call.reserve_scratch(64, 64).unwrap(), b"data");
    let body = request.take_body();
    drop(request);
    let _ = control.budget.finalize_at(None, std::time::Instant::now());
    assert_eq!(body.into_http_bytes().err(), Some(HttpError::Unavailable));
    assert_eq!(io.snapshot(), snapshot);
}

#[tokio::test]
async fn buffered_body_refunds_original_charges_on_caller_unwind() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (input, control) = native_request(&fixture, "buffered-body-caller-panic");
    let session = fixture.session(&input, &control);
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let call = start(&io, &session).await;
    let baseline = control.budget.host_memory_bytes();
    let snapshot = io.snapshot();
    let mut request = request(call.reserve_scratch(64, 64).unwrap(), b"data");
    let bytes = request.take_body().into_http_bytes().unwrap();
    drop(request);
    let outcome = std::panic::catch_unwind(move || {
        let _owner = bytes;
        panic!("controlled caller unwind");
    });
    assert!(outcome.is_err());
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    assert_eq!(io.snapshot(), snapshot);
}
