//! Actual pool/channel ownership controls, not a kernel retirement model.
use super::*;
use latent_core::PlatformErrorCode;
use std::net::Shutdown;

async fn finished(pools: &ProviderPools) {
    tokio::time::timeout(Duration::from_secs(3), async {
        loop {
            if pools
                .inner
                .control
                .tasks
                .lock()
                .unwrap()
                .iter()
                .all(|slot| slot.as_ref().is_none_or(|job| job.is_finished()))
            {
                return;
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .expect("original finite worker must finish");
}

#[tokio::test]
async fn buffered_and_delivered_close_receipt_keeps_original_cleanup_charge() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("close-receipt-held");
    let call = setup.call(&session).await;
    let (connection, _peer) = connect(&setup.client, &call);
    drop(call);
    drop(session);
    let job = match setup
        .pools
        .cleanup_stream_kernel_blocking_quarantined(connection, |stream| {
            stream.shutdown(Shutdown::Both).unwrap();
            StreamKernelCloseObservation::RequestAccepted
        }) {
        Ok(job) => job,
        Err(_) => panic!("original cleanup admission"),
    };
    finished(&setup.pools).await;
    // The actual worker is complete, but its buffered result is still paid.
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Cleanup), 1);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
    assert_eq!(setup.pools.inner.failed_cleanup.load(Ordering::Acquire), 1);
    let buffered_metadata = setup.pools.inner.quotas.use_of(Kind::Metadata);
    let receipt = job.wait().await.unwrap();
    assert_eq!(
        receipt.observation(),
        StreamKernelCloseObservation::RequestAccepted
    );
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Cleanup), 1);
    assert_eq!(
        setup.pools.inner.quotas.use_of(Kind::Metadata),
        buffered_metadata
    );
    drop(receipt);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Cleanup), 0);
    assert!(setup.pools.inner.quotas.use_of(Kind::Metadata) < buffered_metadata);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
    assert_eq!(setup.pools.inner.failed_cleanup.load(Ordering::Acquire), 1);
}

#[tokio::test]
async fn abandoned_close_waiter_does_not_release_running_or_quarantined_owner() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("close-receipt-abandoned");
    let call = setup.call(&session).await;
    let (connection, _peer) = connect(&setup.client, &call);
    let (entered, observed) = std::sync::mpsc::channel();
    let (release, wait) = std::sync::mpsc::channel();
    let job =
        match setup
            .pools
            .cleanup_stream_kernel_blocking_quarantined(connection, move |stream| {
                entered.send(()).unwrap();
                wait.recv_timeout(Duration::from_secs(2)).unwrap();
                stream.shutdown(Shutdown::Both).unwrap();
                StreamKernelCloseObservation::Uncertain
            }) {
            Ok(job) => job,
            Err(_) => panic!("original cleanup admission"),
        };
    observed.recv_timeout(Duration::from_secs(2)).unwrap();
    drop(job);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Cleanup), 1);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
    release.send(()).unwrap();
    finished(&setup.pools).await;
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Cleanup), 0);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
    assert_eq!(setup.pools.inner.failed_cleanup.load(Ordering::Acquire), 1);
}

#[tokio::test]
async fn close_worker_panic_never_publishes_accepted_receipt_or_refunds_connection() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("close-receipt-panic");
    let call = setup.call(&session).await;
    let (connection, _peer) = connect(&setup.client, &call);
    let job = match setup
        .pools
        .cleanup_stream_kernel_blocking_quarantined(connection, |_| {
            panic!("controlled interruption before close observation")
        }) {
        Ok(job) => job,
        Err(_) => panic!("original cleanup admission"),
    };
    finished(&setup.pools).await;
    // Even an empty closed channel stays paid while its receiver is unpolled.
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Cleanup), 1);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
    assert_eq!(setup.pools.inner.failed_cleanup.load(Ordering::Acquire), 1);
    assert!(job.wait().await.is_err());
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Cleanup), 0);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
    assert_eq!(setup.pools.inner.failed_cleanup.load(Ordering::Acquire), 1);
}

#[tokio::test]
async fn published_receipt_drop_cannot_release_live_sender_worker_tail() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("close-receipt-publish-tail");
    let call = setup.call(&session).await;
    let (connection, _peer) = connect(&setup.client, &call);
    let (published, observed) = std::sync::mpsc::sync_channel(1);
    let (release, resume) = std::sync::mpsc::sync_channel(1);
    let barrier = super::super::control::ClosePublicationBarrier { published, resume };
    let job = match setup.pools.cleanup_stream_kernel_with_publication_barrier(
        connection,
        |_| StreamKernelCloseObservation::RequestAccepted,
        barrier,
    ) {
        Ok(job) => job,
        Err(_) => panic!("original cleanup admission"),
    };
    observed.recv_timeout(Duration::from_secs(2)).unwrap();
    let receipt = job.wait().await.unwrap();
    assert_eq!(
        receipt.observation(),
        StreamKernelCloseObservation::RequestAccepted
    );
    drop(receipt);
    // Receiver and receipt are GONE. The real worker is still paused after send.
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Cleanup), 1);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
    assert_eq!(setup.pools.inner.failed_cleanup.load(Ordering::Acquire), 1);
    let metadata = setup.pools.inner.quotas.use_of(Kind::Metadata);
    release.send(()).unwrap();
    finished(&setup.pools).await;
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Cleanup), 0);
    assert!(setup.pools.inner.quotas.use_of(Kind::Metadata) < metadata);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
}

#[tokio::test]
async fn held_close_receipt_bounds_new_admission_and_returns_unchanged_owner() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_cleanup_jobs: 1,
        ..ProviderPoolLimits::default()
    });
    let (session, _control) = setup.session("close-receipt-capacity");
    let call = setup.call(&session).await;
    let (connection, _first_peer) = connect(&setup.client, &call);
    let (mut next, _second_peer) = connect(&setup.client, &call);
    let address = next.resource().local_addr().unwrap();
    let job = match setup
        .pools
        .cleanup_stream_kernel_blocking_quarantined(connection, |_| {
            StreamKernelCloseObservation::NotAttempted
        }) {
        Ok(job) => job,
        Err(_) => panic!("original cleanup admission"),
    };
    let receipt = job.wait().await.unwrap();
    finished(&setup.pools).await;
    let entered = Arc::new(AtomicBool::new(false));
    let marker = Arc::clone(&entered);
    let (failure, mut returned) =
        match setup
            .pools
            .cleanup_stream_kernel_blocking_quarantined(next, move |_| {
                marker.store(true, Ordering::Release);
                StreamKernelCloseObservation::RequestAccepted
            }) {
            Ok(_) => panic!("held result cannot multiply original cleanup allowance"),
            Err(original) => original,
        };
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert!(!entered.load(Ordering::Acquire));
    assert_eq!(returned.resource().local_addr().unwrap(), address);
    returned.quarantine();
    drop(receipt);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Cleanup), 0);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 2);
}
