use super::*;
use http_body::{Body as HttpBody, Frame};
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeCapacityLimits, NativeCapacityOwner,
        NativeCapacityPartition, NativeReservationRequest,
    },
    test_support::{
        block_on,
        coordination::{with_watchdog, PauseTicket, PollProbe, Rendezvous, Stage, WATCHDOG},
        TestClock,
    },
    ActivationClock,
};
use latent_state::{
    embedded::Family,
    store_io::{StoreIoError, StoreIoKind, StoreIoLimits},
};
use prost::Message;
use std::{
    future::poll_fn,
    pin::Pin,
    sync::mpsc,
    task::{Context, Poll},
};
use tonic::{
    body::Body,
    codegen::{http, Bytes, Service},
    Status,
};
const ORDINARY_BUFFER_BYTES: usize = 3 * 1024 * 1024;
const ORDINARY_WORK_BYTES: u64 = 3 * ORDINARY_BUFFER_BYTES as u64;
const ORDINARY_RESERVATION_BYTES: u64 = ORDINARY_WORK_BYTES + 2_048;

pub(super) fn install(fixture: &mut Fixture, owner: NativeCapacityOwner) {
    Arc::get_mut(&mut fixture.backend.0)
        .unwrap()
        .services
        .admission = Arc::new(StateManagementRecoveryAdmission::new(owner));
}
fn pause<T>(gates: &Rendezvous, notice: &mpsc::Sender<PauseTicket>, buffer: T) {
    let (registration, mut tracked) = gates.track(buffer).unwrap();
    tracked.commit(Stage::Entered).unwrap();
    block_on(with_watchdog(WATCHDOG, async {
        let mut waiting = Box::pin(tracked.pause());
        PollProbe::default().pending(waiting.as_mut());
        notice
            .send(gates.blocked(registration, Stage::Entered).unwrap())
            .unwrap();
        waiting.await;
    }));
}
fn io_limits(pressure: StoreIoError) -> StoreIoLimits {
    let mut limits = latent_state::protected_store::ProtectedStoreConfig::bounded_linux(
        "/unused-test-profile".into(),
    )
    .io;
    match pressure {
        StoreIoError::QueueFull => {
            limits.queued_jobs = 1;
            limits.accepted_jobs = 8;
        }
        StoreIoError::AcceptedFull => {
            limits.queued_jobs = 2;
            limits.accepted_jobs = 3;
        }
        StoreIoError::ByteBudget => {
            limits.queued_jobs = 2;
            limits.accepted_jobs = 8;
            limits.retained_bytes =
                limits.resident_bytes + limits.recovery.unwrap().retained_bytes + 12 * 1024 * 1024;
            // Startup and actual native metadata are also prepaid in this
            // profile; a tiny per-job ceiling would reject initialization.
            limits.job_bytes = 10 * 1024 * 1024;
        }
        _ => unreachable!(),
    }
    limits
}
struct OneFrame(Option<Bytes>);
impl HttpBody for OneFrame {
    type Data = Bytes;
    type Error = Status;
    fn poll_frame(
        mut self: Pin<&mut Self>,
        _: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Bytes>, Status>>> {
        Poll::Ready(self.0.take().map(|bytes| Ok(Frame::data(bytes))))
    }
}
async fn response_body(fixture: &Fixture) -> Body {
    let adapter = super::super::super::Phase4ServiceAdapter::with_services(
        Arc::new(fixture.backend.clone()),
        crate::management::ManagementLimits::default(),
        super::super::super::Phase4Services {
            principals: Arc::new(crate::invocation::LocalPrincipalPolicy),
            management: Arc::new(crate::management::LocalManagementPolicy),
            clock: Arc::new(latent_core::SystemActivationClock),
        },
    )
    .unwrap();
    let encoded = fixture.target().encode_to_vec();
    let mut bytes = vec![0];
    bytes.extend_from_slice(&u32::try_from(encoded.len()).unwrap().to_be_bytes());
    bytes.extend_from_slice(&encoded);
    let mut request = http::Request::builder()
        .method("POST")
        .uri("/latent.control.v1.StateService/InspectNamespace")
        .header("content-type", "application/grpc")
        .body(Body::new(OneFrame(Some(Bytes::from(bytes)))))
        .unwrap();
    request.extensions_mut().insert(context("alice"));
    let mut server = adapter.state_server();
    let response = with_watchdog(WATCHDOG, server.call(request)).await.unwrap();
    assert_eq!(response.status(), http::StatusCode::OK);
    assert!(response.headers().get("grpc-status").is_none());
    response.into_body()
}
fn capacity_owner() -> NativeCapacityOwner {
    NativeCapacityOwner::new(NativeCapacityLimits {
        ordinary: NativeCapacityPartition {
            slots: 1,
            bytes: ORDINARY_RESERVATION_BYTES,
            maximum_reservation_bytes: ORDINARY_RESERVATION_BYTES,
        },
        ..NativeCapacityLimits::default()
    })
    .unwrap()
}

#[tokio::test]
async fn authenticated_recovery_and_retained_rpc_frame_progress_under_real_ordinary_saturation() {
    for pressure in [
        StoreIoError::QueueFull,
        StoreIoError::AcceptedFull,
        StoreIoError::ByteBudget,
    ] {
        let mut fixture = Fixture::with_io(false, Some(io_limits(pressure))).await;
        let owner = capacity_owner();
        install(&mut fixture, owner.clone());
        drop(fixture.create().await);
        let ordinary = owner
            .reserve(
                NativeAdmissionClass::Ordinary,
                NativeReservationRequest {
                    work_bytes: ORDINARY_WORK_BYTES,
                    ..NativeReservationRequest::default()
                },
                deadline(),
            )
            .unwrap();
        let gates = Rendezvous::new(3);
        let (notice, receiver) = mpsc::channel();
        let mut jobs = Vec::new();
        let mut tickets = Vec::new();
        for kind in [StoreIoKind::Read, StoreIoKind::Read, StoreIoKind::Write] {
            let worker = gates.clone();
            let notice = notice.clone();
            let buffer = ordinary
                .allocate_bytes(NativeBufferClass::Work, ORDINARY_BUFFER_BYTES)
                .unwrap();
            jobs.push(
                fixture
                    .store
                    .with_store(kind, ORDINARY_BUFFER_BYTES as u64, move |_| {
                        pause(&worker, &notice, buffer);
                        Ok(())
                    })
                    .unwrap(),
            );
            tickets.push(receiver.recv_timeout(WATCHDOG).unwrap());
        }
        drop(ordinary);
        let queued = (pressure == StoreIoError::QueueFull).then(|| {
            fixture
                .store
                .with_store(StoreIoKind::Read, 1_024, |_| Ok(vec![0_u8; 1_024]))
                .unwrap()
        });
        assert!(matches!(
            fixture.store.with_store(StoreIoKind::Read, 4 * 1024 * 1024, |_| Ok(())),
            Err(ProtectedStoreError::Io(actual)) if actual == pressure
        ));
        assert!(matches!(
            owner.reserve(
                NativeAdmissionClass::Ordinary,
                NativeReservationRequest::default(),
                deadline()
            ),
            Err(latent_core::native_capacity::NativeCapacityError::SlotsFull)
        ));
        let mut body = response_body(&fixture).await;
        let frame = with_watchdog(WATCHDOG, poll_fn(|cx| Pin::new(&mut body).poll_frame(cx)))
            .await
            .unwrap()
            .unwrap();
        let bytes = frame.into_data().unwrap();
        let response = c::InspectNamespaceResponse::decode(&bytes[5..]).unwrap();
        assert_eq!(response.namespace.unwrap().generation, 1);
        let held = owner.snapshot().unwrap();
        assert_eq!(held.ordinary.slots, 1);
        assert_eq!(held.ordinary.bytes, ORDINARY_RESERVATION_BYTES);
        assert_eq!(held.recovery.slots, 1);
        assert!(held.recovery.bytes >= (WORK_BYTES + RESPONSE_BYTES) as u64);
        let native = fixture.store.snapshot().unwrap();
        assert_eq!((native.active_reads, native.active_writes), (2, 1));
        drop(body);
        assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
        let retained_frame = bytes.clone();
        drop(bytes);
        assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
        drop(retained_frame);
        assert_eq!(owner.snapshot().unwrap().recovery.bytes, 0);
        for ticket in tickets {
            gates.release(ticket).unwrap();
        }
        for job in jobs {
            with_watchdog(WATCHDOG, job).await.unwrap().unwrap();
        }
        if let Some(job) = queued {
            with_watchdog(WATCHDOG, job).await.unwrap().unwrap();
        }
        fixture.finish().await;
        assert!(owner.snapshot().unwrap().physically_retired());
    }
}

#[tokio::test]
async fn detached_recovery_write_keeps_global_capacity_until_original_expiry_and_real_retirement() {
    let mut fixture = Fixture::new(false).await;
    let clock = TestClock::new(100, Instant::now(), 1);
    let owner =
        NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), Arc::new(clock.clone()))
            .unwrap();
    install(&mut fixture, owner.clone());
    Arc::get_mut(&mut fixture.backend.0).unwrap().services.clock = Arc::new(clock.clone());
    drop(fixture.create().await);
    let gates = Rendezvous::new(1);
    let worker = gates.clone();
    let (notice, receiver) = mpsc::channel();
    let write = fixture
        .store
        .with_store(StoreIoKind::Write, 1_024, move |_| {
            pause(&worker, &notice, vec![0_u8; 1_024]);
            Ok(())
        })
        .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    let original_deadline = clock.monotonic_now() + Duration::from_secs(5);
    let original = context("alice").with_transport_deadline_at(5_100, original_deadline);
    let mut request = Box::pin(
        fixture.backend.execute_state(
            original,
            fixture
                .mutation("expired-quiesce", c::NamespaceMutationKind::Quiesce, 1)
                .into(),
        ),
    );
    PollProbe::default().pending(request.as_mut());
    assert_eq!(fixture.store.snapshot().unwrap().recovery_queued, 1);
    assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
    drop(request);
    clock.advance(Duration::from_secs(5));
    assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
    gates.release(ticket).unwrap();
    with_watchdog(WATCHDOG, write).await.unwrap().unwrap();
    fixture.finish().await;
    assert!(owner.snapshot().unwrap().physically_retired());
    let mut config = fixture.config.clone();
    config.create_if_missing = false;
    let reopened = fixture::start(config).await;
    let rows = reopened
        .with_store(StoreIoKind::RecoveryRead, 65_536, |engine| {
            engine.snapshot()?.scan(Family::Namespace, b"", 128, 65_536)
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    // One original create receipt and one namespace record; no quiesce receipt
    // was invented after the original queued request's deadline expired.
    assert_eq!(rows.len(), 2);
    reopened.close();
    assert!(
        with_watchdog(
            WATCHDOG,
            reopened
                .drain_async(deadline(), std::future::pending())
                .unwrap()
        )
        .await
        .clean
    );
}
