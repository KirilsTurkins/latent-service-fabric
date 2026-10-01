//! Controlled external gateway peer: host cleanup is not downstream rollback.
//! Invoked by the existing lost-mutation regression, using the production broker,
//! original activation budget, `IoRuntime` and `HttpProvider`. No new host import.
use super::*;
use std::sync::atomic::AtomicUsize;
use tokio::{sync::oneshot, task::JoinSet};

const ACCEPTED: &[u8] =
    b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\nConnection: close\r\n\r\npeer-accepted";

pub(super) async fn assert_external_gateway_ownership_boundary() {
    tokio::time::timeout(Duration::from_secs(10), exercise_boundary())
        .await
        .expect("bounded external gateway ownership experiment");
}

async fn exercise_boundary() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let active = Arc::new(AtomicUsize::new(0));
    let applied = Arc::new(AtomicUsize::new(0));
    let (started, accepted) = oneshot::channel();
    let (release, retire) = oneshot::channel();
    // JoinSet aborts owned peers on test failure. A dropped JoinHandle alone
    // would detach the very work whose lifetime this regression is checking.
    let mut peers = JoinSet::new();
    let peer_active = active.clone();
    let peer_applied = applied.clone();
    peers.spawn(async move {
        let (mut first, _) = listener.accept().await.unwrap();
        let first_request = read_request(&mut first).await;
        assert!(first_request.starts_with(b"POST /allowed HTTP/1.1\r\n"));
        assert!(first_request.ends_with(b"submit:first"));
        // This is a controlled downstream-effect witness, not an SMTP server
        // or proof of a remote database transaction. No HTTP reply is sent.
        peer_active.fetch_add(1, Ordering::AcqRel);
        peer_applied.fetch_add(1, Ordering::AcqRel);
        started.send(()).unwrap();

        // A fresh activation must connect independently while the first
        // external owner is still alive. No guest/session continuation is used.
        let (mut second, _) = listener.accept().await.unwrap();
        let second_request = read_request(&mut second).await;
        assert!(second_request.ends_with(b"submit:second"));
        peer_applied.fetch_add(1, Ordering::AcqRel);
        second.write_all(ACCEPTED).await.unwrap();
        drop(second);

        // Only this explicit witness retires the external operation. Closing
        // the HTTP transport or refunding the LSF ledger cannot do it.
        retire.await.unwrap();
        let mut byte = [0];
        assert_eq!(first.read(&mut byte).await.unwrap(), 0);
        drop(first);
        peer_active.fetch_sub(1, Ordering::AcqRel);
    });

    let f = Fixture::new(config(port));
    let (first, control) = f.session(5000);
    let observer = first.observer();
    let mut input = request(port, HttpMethod::Post);
    input.body = Some(b"submit:first".to_vec());
    let mut operation = f.provider.start(&first, input).unwrap();
    tokio::select! {
        _ = &mut operation => panic!("gateway withheld the acknowledgement"),
        result = accepted => result.unwrap(),
    }
    assert_eq!(active.load(Ordering::Acquire), 1);
    assert_eq!(applied.load(Ordering::Acquire), 1);
    control.probe.0.store(true, Ordering::Release);
    let completion = operation.await.unwrap();
    assert!(matches!(completion.response, Err(HttpError::Uncertain)));
    drop(completion);
    drop(first);
    assert!(observer.is_quiescent());
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    assert_eq!(f.pools.snapshot().unwrap().running_requests, 0);
    assert_eq!(f.pools.snapshot().unwrap().connections, 0);
    assert_eq!(active.load(Ordering::Acquire), 1);
    assert_eq!(applied.load(Ordering::Acquire), 1);

    let (fresh, _) = f.session(5000);
    let fresh_observer = fresh.observer();
    let mut input = request(port, HttpMethod::Post);
    input.body = Some(b"submit:second".to_vec());
    let completion = f.provider.start(&fresh, input).unwrap().await.unwrap();
    let response = completion.response.unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(response.body(), b"peer-accepted");
    drop(completion.owner);
    drop(response);
    drop(fresh);
    assert!(fresh_observer.is_quiescent());
    assert_eq!(active.load(Ordering::Acquire), 1);
    assert_eq!(applied.load(Ordering::Acquire), 2);
    release.send(()).unwrap();
    peers.join_next().await.unwrap().unwrap();
    assert!(peers.is_empty());
    assert_eq!(active.load(Ordering::Acquire), 0);
    assert_eq!(applied.load(Ordering::Acquire), 2);
    f.clean().await;
}
