use super::*;

pub(super) fn block_storage(fixture: &Fixture, gates: &Rendezvous) -> Vec<PauseTicket> {
    let (notice, receiver) = std::sync::mpsc::channel();
    for kind in [StoreIoKind::Write, StoreIoKind::Read, StoreIoKind::Read] {
        let gates = gates.clone();
        let notice = notice.clone();
        let job = fixture
            .store
            .with_store(kind, 1024, move |_| {
                let (registration, mut work) = gates.track(vec![0_u8; 1024]).unwrap();
                work.commit(Stage::Entered).unwrap();
                latent_core::test_support::block_on(with_watchdog(WATCHDOG, async {
                    let mut pause = Box::pin(work.pause());
                    PollProbe::default().pending(pause.as_mut());
                    let ticket = gates.blocked(registration, Stage::Entered).unwrap();
                    notice.send(ticket).unwrap();
                    pause.await;
                }));
                Ok(())
            })
            .unwrap();
        drop(job);
    }
    let tickets = (0..3)
        .map(|_| receiver.recv_timeout(WATCHDOG).unwrap())
        .collect();
    loop {
        match fixture.store.with_store(StoreIoKind::Read, 0, |_| Ok(())) {
            Ok(job) => drop(job),
            Err(ProtectedStoreError::Io(latent_state::store_io::StoreIoError::QueueFull)) => break,
            Err(error) => panic!("unexpected queue failure {error:?}"),
        }
    }
    assert_eq!(
        fixture.store.snapshot().unwrap().queued,
        fixture.config.io.queued_jobs
    );
    tickets
}

#[tokio::test]
async fn full_native_queue_retains_one_bounded_receipt_and_root_pin_until_actual_record_cas() {
    let fixture = Fixture::new().await;
    let authority = fixture
        .seed(1, "tenant-a", "publication", profile("test.v1"))
        .await;
    let (adapter, mut entered) = Adapter::new("test.v1", Some("tenant-a"));
    let mut dispatcher = fixture
        .start(config(), vec![adapter.clone()], None)
        .await
        .unwrap();
    let parked = event(&mut entered).await;
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::Dispatching
    );
    dispatcher.pause();
    let gates = Rendezvous::new(3);
    let storage = block_storage(&fixture, &gates);
    adapter.gates.release(parked.ticket.unwrap()).unwrap();
    with_watchdog(WATCHDOG, async {
        loop {
            if fixture.authority.owners().unwrap().physical == 0 {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await;
    assert_eq!(adapter.physical.load(Ordering::SeqCst), 0);
    assert_eq!(fixture.capacity.snapshot().unwrap().ordinary.slots, 1);
    assert!(
        fixture.capacity.snapshot().unwrap().ordinary.bytes
            >= super::super::capacity::ATTEMPT_NATIVE_BYTES
    );
    let during = dispatcher.snapshot().unwrap();
    assert_eq!(during.accepted_effects, 1);
    assert_eq!(during.active_jobs, 1);
    assert!(during.retained_attempt_bytes >= DispatcherConfig::ATTEMPT_BYTES);
    assert_eq!(fixture.store.snapshot().unwrap().physical_owners, 2); // Role plus receipt/attempt pin.
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 1);
    for ticket in storage {
        gates.release(ticket).unwrap();
    }
    wait_disposition(&fixture, &authority, Disposition::ProviderAcknowledged).await;
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 1);
    fixture.finish().await;
    assert!(fixture.capacity.snapshot().unwrap().physically_retired());
}
