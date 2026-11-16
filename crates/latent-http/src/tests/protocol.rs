use super::*;
use crate::protocol::{
    ProtocolBody, ProtocolHeader, ProtocolPage, ProtocolRequest, ProtocolScope, ProtocolTransport,
};
use http_body_util::BodyExt;
use std::time::Instant;
use zeroize::Zeroizing;

fn configured(port: u16, root: Vec<u8>) -> (Fixture, ProtocolTransport) {
    let mut cfg = config(port);
    cfg.destinations[0].origin.scheme = "https".into();
    cfg.destinations[0].allowed_request_headers.clear();
    cfg.destinations[0].redirect_destinations.clear();
    cfg.extra_roots.push(root);
    let f = Fixture::new(cfg.clone());
    let transport =
        ProtocolTransport::new(f.pools.clone(), &f.provider.inner.installed, cfg).unwrap();
    (f, transport)
}
fn input(port: u16, body: ProtocolBody) -> ProtocolRequest {
    ProtocolRequest {
        method: "POST".into(),
        path_and_query: "/allowed?uploads=".into(),
        headers: vec![ProtocolHeader {
            name: "host".into(),
            value: Zeroizing::new(format!("localhost:{port}")),
            sensitive: false,
        }],
        body,
    }
}
#[tokio::test]
async fn pages_stream_exact_ranges_and_outlive_dropped_body_owners() {
    let f = Fixture::new(config(12345));
    let baseline = f.pools.snapshot().unwrap().metadata_bytes;
    assert!(ProtocolPage::allocate(&f.pools, 65537).is_err());
    let mut page = ProtocolPage::allocate(&f.pools, 4096).unwrap();
    page.append(&[7; 4096]).unwrap();
    assert!(page.append(&[8]).is_err());
    let pages = vec![Arc::new(page)];
    assert!(ProtocolBody::from_pages(&f.pools, &pages, 0..4097).is_err());
    let mut body = ProtocolBody::from_pages(&f.pools, &pages, 4090..4096).unwrap();
    let frame = body.frame().await.unwrap().unwrap().into_data().unwrap();
    assert_eq!(frame.as_ref(), &[7; 6]);
    assert!(body.frame().await.is_none());
    drop((body, pages));
    assert!(f.pools.snapshot().unwrap().metadata_bytes > baseline);
    drop(frame);
    assert_eq!(f.pools.snapshot().unwrap().metadata_bytes, baseline);
    f.clean().await;
}

#[tokio::test]
async fn protocol_frame_admission_matches_ranges_empty_pages_and_original_pool() {
    use crate::protocol::protocol_accounting_layout;
    let f = Fixture::new(config(12345));
    let baseline = f.pools.snapshot().unwrap().metadata_bytes;
    let mut pages = Vec::new();
    for bytes in [b"".as_slice(), b"ab", b"", b"cde", b"", b"f"] {
        let mut page = ProtocolPage::allocate(&f.pools, 8).unwrap();
        page.append(bytes).unwrap();
        pages.push(Arc::new(page));
    }
    let page_total = f.pools.snapshot().unwrap().metadata_bytes;
    let (entry, frame_charge) = protocol_accounting_layout();
    let body_charge = 1024 + pages.len() * entry.max(32);
    eprintln!(
        "protocol page entry={entry}; frame Box={}, charge={frame_charge}",
        frame_charge - 64
    );

    let mut empty = ProtocolBody::from_pages(&f.pools, &pages, 3..3).unwrap();
    assert_eq!(
        f.pools.snapshot().unwrap().metadata_bytes,
        page_total + body_charge
    );
    assert!(empty.frame().await.is_none());
    drop(empty);
    assert_eq!(f.pools.snapshot().unwrap().metadata_bytes, page_total);

    // Cancelling after one frame releases the body and all four unissued
    // frame reservations, while the emitted frame keeps its own original one.
    let mut partial = ProtocolBody::from_pages(&f.pools, &pages, 1..6).unwrap();
    assert_eq!(
        f.pools.snapshot().unwrap().metadata_bytes,
        page_total + body_charge + 5 * frame_charge
    );
    let held = partial.frame().await.unwrap().unwrap().into_data().unwrap();
    assert_eq!(&held[..], b"b");
    drop(partial);
    assert_eq!(
        f.pools.snapshot().unwrap().metadata_bytes,
        page_total + frame_charge
    );
    drop(held);
    assert_eq!(f.pools.snapshot().unwrap().metadata_bytes, page_total);

    let mut body = ProtocolBody::from_pages(&f.pools, &pages, 1..5).unwrap();
    let prepaid = page_total + body_charge + 3 * frame_charge;
    assert_eq!(f.pools.snapshot().unwrap().metadata_bytes, prepaid);
    let mut frames = Vec::new();
    for (expected, remaining) in [(b"b".as_slice(), 3), (b"", 3), (b"cde", 0)] {
        let frame = body.frame().await.unwrap().unwrap().into_data().unwrap();
        assert_eq!(&frame[..], expected);
        assert_eq!(body.length(), remaining);
        assert_eq!(f.pools.snapshot().unwrap().metadata_bytes, prepaid);
        frames.push(frame);
    }
    assert!(body.frame().await.is_none());
    drop((body, pages));
    assert_eq!(
        f.pools.snapshot().unwrap().metadata_bytes,
        baseline + 3 * (8 + 512) + 3 * frame_charge
    );
    drop(frames);
    assert_eq!(f.pools.snapshot().unwrap().metadata_bytes, baseline);
    f.clean().await;
}

#[tokio::test]
async fn protocol_frame_owner_refuses_before_poll_and_rolls_back_partial_admission() {
    use crate::protocol::protocol_accounting_layout;
    use latent_capabilities::broker::pools::ProviderPoolLimits;
    let f = Fixture::new(config(12345));
    let mut first = ProtocolPage::allocate(&f.pools, 8).unwrap();
    first.append(b"a").unwrap();
    let mut second = ProtocolPage::allocate(&f.pools, 8).unwrap();
    second.append(b"b").unwrap();
    let pages = vec![Arc::new(first), Arc::new(second)];
    let before = f.pools.snapshot().unwrap().metadata_bytes;
    let (entry, frame_charge) = protocol_accounting_layout();
    let body_charge = 1024 + pages.len() * entry.max(32);
    let limit = ProviderPoolLimits::default().maximum_metadata_bytes;
    // Leave enough for the body and first frame, but one byte too little for
    // the second frame. The first prepaid guard must be rolled back too.
    let mut remaining = limit - before - body_charge - 2 * frame_charge + 1;
    let mut padding = Vec::new();
    let held = remaining;
    while remaining != 0 {
        let part = remaining.min(1024 * 1024);
        padding.push(f.pools.reserve_protocol_metadata(part).unwrap());
        remaining -= part;
    }
    assert!(matches!(
        ProtocolBody::from_pages(&f.pools, &pages, 0..2),
        Err(HttpError::BudgetExhausted)
    ));
    assert_eq!(f.pools.snapshot().unwrap().metadata_bytes, before + held);
    drop(padding);
    assert_eq!(f.pools.snapshot().unwrap().metadata_bytes, before);
    drop(pages);
    f.clean().await;
}

#[tokio::test]
async fn protocol_frame_and_page_keep_their_independent_original_pool_charges() {
    use crate::protocol::protocol_accounting_layout;
    let pages_owner = Fixture::new(config(12345));
    let body_owner = Fixture::new(config(12346));
    let page_base = pages_owner.pools.snapshot().unwrap().metadata_bytes;
    let body_base = body_owner.pools.snapshot().unwrap().metadata_bytes;
    let mut page = ProtocolPage::allocate(&pages_owner.pools, 8).unwrap();
    page.append(b"data").unwrap();
    let page = Arc::new(page);
    let mut body = ProtocolBody::from_pages(&body_owner.pools, &[Arc::clone(&page)], 1..4).unwrap();
    let frame = body.frame().await.unwrap().unwrap().into_data().unwrap();
    assert_eq!(&frame[..], b"ata");
    let (_, frame_charge) = protocol_accounting_layout();
    drop((body, page));
    assert_eq!(
        pages_owner.pools.snapshot().unwrap().metadata_bytes,
        page_base + 8 + 512
    );
    assert_eq!(
        body_owner.pools.snapshot().unwrap().metadata_bytes,
        body_base + frame_charge
    );
    drop(frame);
    assert_eq!(
        pages_owner.pools.snapshot().unwrap().metadata_bytes,
        page_base
    );
    assert_eq!(
        body_owner.pools.snapshot().unwrap().metadata_bytes,
        body_base
    );
    pages_owner.clean().await;
    body_owner.clean().await;
}

#[tokio::test]
async fn protocol_frame_poll_never_readmits_after_pool_retirement() {
    let f = Fixture::new(config(12345));
    let mut page = ProtocolPage::allocate(&f.pools, 8).unwrap();
    page.append(b"data").unwrap();
    let page = Arc::new(page);
    let mut body = ProtocolBody::from_pages(&f.pools, &[Arc::clone(&page)], 0..4).unwrap();
    f.pools.retire();
    assert!(f.pools.reserve_protocol_metadata(1).is_err());
    let frame = body.frame().await.unwrap().unwrap().into_data().unwrap();
    assert_eq!(&frame[..], b"data");
    assert!(body.frame().await.is_none());
    drop((frame, body, page));
    f.clean().await;
}

#[tokio::test]
async fn protocol_frame_guard_outlives_actual_slice_drop_and_unwind() {
    use crate::protocol::{observe_slice_drop, protocol_accounting_layout};
    use std::sync::atomic::{AtomicBool, Ordering};
    let f = Fixture::new(config(12345));
    let baseline = f.pools.snapshot().unwrap().metadata_bytes;
    let (_, frame_charge) = protocol_accounting_layout();
    for mode in 0..3 {
        let mut page = ProtocolPage::allocate(&f.pools, 8).unwrap();
        page.append(b"payload").unwrap();
        let page = Arc::new(page);
        let mut body = ProtocolBody::from_pages(&f.pools, &[Arc::clone(&page)], 0..7).unwrap();
        let frame = body.frame().await.unwrap().unwrap().into_data().unwrap();
        let clone = frame.clone();
        drop(frame);
        let observed = Arc::new(AtomicBool::new(false));
        let check = Arc::clone(&observed);
        let pools = Arc::clone(&f.pools);
        observe_slice_drop(
            &page,
            Box::new(move || {
                assert_eq!(
                    pools.snapshot().unwrap().metadata_bytes,
                    baseline + 8 + 512 + frame_charge
                );
                check.store(true, Ordering::SeqCst);
                assert!(mode != 1, "controlled Slice destructor unwind");
            }),
        );
        drop((body, page));
        assert_eq!(
            f.pools.snapshot().unwrap().metadata_bytes,
            baseline + 8 + 512 + frame_charge
        );
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(move || {
            if mode == 2 {
                let _frame = clone;
                panic!("controlled caller unwind");
            }
            drop(clone);
        }));
        assert_eq!(result.is_err(), mode != 0);
        assert!(observed.load(Ordering::SeqCst));
        assert_eq!(f.pools.snapshot().unwrap().metadata_bytes, baseline);
    }
    f.clean().await;
}
#[tokio::test]
async fn operator_protocol_uses_real_tls_and_closes_the_actual_connection() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (root, acceptor) = super::tls::certificate();
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut stream = acceptor.accept(stream).await.unwrap();
        let received = read_request(&mut stream).await;
        let split = received.windows(4).position(|b| b == b"\r\n\r\n").unwrap() + 4;
        assert!(std::str::from_utf8(&received[..split])
            .unwrap()
            .to_lowercase()
            .contains("content-length: 4110"));
        let body = &received[split..];
        assert_eq!(&body[..6], &[b'a'; 6]);
        assert_eq!(&body[6..4102], &[b'b'; 4096]);
        assert_eq!(&body[4102..], &[b'c'; 8]);
        stream.write_all(b"HTTP/1.1 206 Partial Content\r\nContent-Length: 3\r\nX-Amz-Version-Id: exact-version\r\n\r\nabc").await.unwrap();
        let ended = tokio::time::timeout(Duration::from_secs(1), stream.read(&mut [0]))
            .await
            .unwrap();
        assert!(matches!(ended, Ok(0)) || ended.is_err());
    });
    let (f, transport) = configured(port, root);
    let mut pages = Vec::new();
    for value in *b"abc" {
        let mut page = ProtocolPage::allocate(&f.pools, 4096).unwrap();
        page.append(&vec![value; 4096]).unwrap();
        pages.push(Arc::new(page));
    }
    let body = ProtocolBody::from_pages(&f.pools, &pages, 4090..8200).unwrap();
    let permit = transport
        .maintenance(Instant::now() + Duration::from_secs(2), 1)
        .unwrap();
    let request = permit.begin_request().unwrap();
    let mut received = Vec::new();
    let response = transport
        .exchange(
            ProtocolScope::Maintenance(&request),
            input(port, body),
            3,
            &mut |b| {
                received.extend_from_slice(b);
                Ok(())
            },
        )
        .await
        .unwrap();
    assert_eq!(response.status, 206);
    assert_eq!(response.body_bytes, 3);
    assert_eq!(received, b"abc");
    assert!(response
        .headers
        .contains(&("x-amz-version-id".into(), "exact-version".into())));
    assert_eq!(f.pools.snapshot().unwrap().connections, 0);
    assert_eq!(f.pools.snapshot().unwrap().idle_connections, 0);
    drop((response, request, permit, pages, transport));
    server.await.unwrap();
    f.clean().await;
}
#[tokio::test]
async fn protocol_deadline_retains_uncertainty_after_an_actual_request_write() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (root, acceptor) = super::tls::certificate();
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut stream = acceptor.accept(stream).await.unwrap();
        read_request(&mut stream).await;
        let ended = tokio::time::timeout(Duration::from_secs(1), stream.read(&mut [0]))
            .await
            .unwrap();
        assert!(matches!(ended, Ok(0)) || ended.is_err());
    });
    let (f, transport) = configured(port, root);
    let permit = transport
        .maintenance(Instant::now() + Duration::from_millis(500), 1)
        .unwrap();
    let request = permit.begin_request().unwrap();
    let result = transport
        .exchange(
            ProtocolScope::Maintenance(&request),
            input(port, ProtocolBody::empty(&f.pools).unwrap()),
            32,
            &mut |_| Ok(()),
        )
        .await;
    let Err(failure) = result else {
        panic!("unanswered mutation must not succeed")
    };
    assert_eq!(failure.error, HttpError::DeadlineExceeded);
    assert!(failure.request_started);
    assert_eq!(f.pools.snapshot().unwrap().connections, 0);
    drop((request, permit, transport));
    server.await.unwrap();
    f.clean().await;
}
