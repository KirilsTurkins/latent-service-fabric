use super::*;
#[tokio::test]
async fn shared_idle_connection_owns_no_activation_and_reuses_the_real_socket() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        for _ in 0..2 {
            read_request(&mut stream).await;
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
                .await
                .unwrap();
        }
        let mut byte = [0];
        assert_eq!(stream.read(&mut byte).await.unwrap(), 0);
    });
    let f = Fixture::new(config(port));
    for _ in 0..2 {
        let (session, _) = f.session(5000);
        let observer = session.observer();
        let done = f
            .provider
            .start(&session, request(port, HttpMethod::Get))
            .unwrap()
            .await
            .unwrap();
        assert!(done.response.is_ok());
        drop(done);
        drop(session);
        assert!(observer.is_quiescent());
        assert_eq!(
            f.io.snapshot(),
            latent_capabilities::broker::io::IoSnapshot::default()
        );
        assert_eq!(f.pools.snapshot().unwrap().idle_connections, 1);
    }
    f.clean().await;
    server.await.unwrap();
}
#[tokio::test]
async fn healthy_inflight_requests_share_bounded_provider_capacity() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (first, accepted) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut a, _) = listener.accept().await.unwrap();
        read_request(&mut a).await;
        first.send(()).unwrap();
        let (mut b, _) = listener.accept().await.unwrap();
        read_request(&mut b).await;
        for stream in [&mut a, &mut b] {
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                .await
                .unwrap();
        }
    });
    let f = Fixture::new(config(port));
    let (one, _) = f.session(5000);
    let (two, _) = f.session(5000);
    let mut first = f
        .provider
        .start(&one, request(port, HttpMethod::Get))
        .unwrap();
    tokio::select! {_=&mut first=>panic!("server waits for concurrent peer"),_=accepted=>{}}
    let second = f
        .provider
        .start(&two, request(port, HttpMethod::Get))
        .unwrap();
    let (a, b) = tokio::join!(first, second);
    let a = a.unwrap();
    let b = b.unwrap();
    assert!(a.response.is_ok());
    assert!(b.response.is_ok());
    drop(a);
    drop(b);
    drop(one);
    drop(two);
    server.await.unwrap();
    f.clean().await;
}

#[tokio::test]
async fn queue_revocation_denies_fresh_dispatch_and_zero_budget_never_connects() {
    use latent_core::{ActivationBudget, BudgetProfile, ClockSample, EffectiveActivationBudget};
    use latent_policy::capability::{MutationRequest, RecordKind};
    use std::time::Instant;
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let f = Fixture::new(config(port));
    let (mut request_zero, mut control) = f.request("no-egress", 5000);
    request_zero.budget.outbound_requests = 0;
    request_zero.activation.budget = request_zero.budget.clone();
    control.budget = ActivationBudget::with_profile(
        EffectiveActivationBudget::admit_profile_at(
            BudgetProfile::Phase3,
            &request_zero.budget,
            &request_zero.budget,
            &request_zero.budget,
            None,
            ClockSample::system_now(),
        )
        .unwrap(),
        BudgetProfile::Phase3,
    )
    .unwrap();
    let session = f
        .broker
        .open_session(f.plan.clone(), &request_zero, &control, &f.publication)
        .unwrap();
    assert!(matches!(
        f.provider
            .start(&session, request(port, HttpMethod::Get))
            .unwrap()
            .await,
        Err(HttpError::BudgetExhausted)
    ));
    drop(session);
    let (session, _) = f.session(5000);
    let future = f
        .provider
        .start(&session, request(port, HttpMethod::Get))
        .unwrap();
    f.policies
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "revoke",
                expected_revision: 2,
                document: None,
            },
            Instant::now() + Duration::from_secs(2),
            |_| Ok(()),
        )
        .unwrap();
    assert!(matches!(future.await, Err(HttpError::PermissionDenied)));
    assert!(
        tokio::time::timeout(Duration::from_millis(30), listener.accept())
            .await
            .is_err()
    );
    drop(session);
    f.clean().await;
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn cancelling_a_connect_stalled_by_full_accept_backlog_closes_its_owner() {
    let socket = tokio::net::TcpSocket::new_v4().unwrap();
    socket.bind("127.0.0.1:0".parse().unwrap()).unwrap();
    let listener = socket.listen(1).unwrap();
    let address = listener.local_addr().unwrap();
    let _first = tokio::net::TcpStream::connect(address).await.unwrap();
    let _second = tokio::net::TcpStream::connect(address).await.unwrap();
    let f = Fixture::new(config(address.port()));
    let (session, control) = f.session(5000);
    let mut operation = f
        .provider
        .start(&session, request(address.port(), HttpMethod::Get))
        .unwrap();
    tokio::select! {_=&mut operation=>panic!("full Linux accept backlog must stall the connect"),()=tokio::time::sleep(Duration::from_millis(40))=>{}}
    assert_eq!(f.pools.snapshot().unwrap().connections, 1);
    control.probe.0.store(true, Ordering::Release);
    let done = operation.await.unwrap();
    assert!(matches!(done.response, Err(HttpError::Cancelled)));
    drop(done);
    drop(session);
    assert_eq!(f.pools.snapshot().unwrap().connections, 0);
    f.clean().await;
}
#[tokio::test]
async fn cancelling_a_partial_mutation_write_is_uncertain_and_closes_the_socket() {
    let socket = tokio::net::TcpSocket::new_v4().unwrap();
    socket.set_recv_buffer_size(4096).unwrap();
    socket.bind("127.0.0.1:0".parse().unwrap()).unwrap();
    let listener = socket.listen(1).unwrap();
    let port = listener.local_addr().unwrap().port();
    let (started, received) = tokio::sync::oneshot::channel();
    let (release, wait) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = [0; 4096];
        let mut count = stream.read(&mut bytes).await.unwrap();
        assert!(count > 0);
        started.send(()).unwrap();
        wait.await.unwrap();
        loop {
            let n = tokio::time::timeout(Duration::from_secs(2), stream.read(&mut bytes))
                .await
                .unwrap()
                .unwrap();
            if n == 0 {
                break;
            }
            count += n;
            assert!(count < 512 * 1024);
        }
        count
    });
    let mut cfg = config(port);
    cfg.limits.maximum_request_body_bytes = 512 * 1024;
    let f = Fixture::new(cfg);
    let (session, control) = f.session(5000);
    let mut input = request(port, HttpMethod::Post);
    input.body = Some(vec![42; 512 * 1024]);
    let mut operation = f.provider.start(&session, input).unwrap();
    tokio::select! {_=&mut operation=>panic!("peer cannot accept the entire body"),_=received=>{}}
    assert!(f.io.snapshot().staged_bytes >= 512 * 1024);
    control.probe.0.store(true, Ordering::Release);
    let done = operation.await.unwrap();
    assert!(matches!(done.response, Err(HttpError::Uncertain)));
    drop(done);
    drop(session);
    release.send(()).unwrap();
    assert!(server.await.unwrap() < 512 * 1024);
    f.clean().await;
}

#[tokio::test]
async fn unpolled_input_and_stale_credential_epochs_cannot_escape_ownership() {
    let f = Fixture::new(config(12345));
    let (session, _) = f.session(5000);
    let observer = session.observer();
    let mut input = request(12345, HttpMethod::Post);
    input.body = Some(vec![0; 4096]);
    let invocation = f.provider.start(&session, input).unwrap();
    assert!(f.io.snapshot().staged_bytes >= 4096);
    drop(session);
    assert!(!observer.is_quiescent());
    drop(invocation);
    assert!(observer.is_quiescent());
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    let (session, _) = f.session(5000);
    let replacement = HttpProvider::install(
        f.pools.clone(),
        "http",
        2,
        1,
        config(12345),
        &[HttpCredential {
            destination: 0,
            name: "authorization",
            value: "rotated-private",
        }],
    )
    .unwrap();
    assert_eq!(
        f.provider.reference().configuration_digest(),
        replacement.reference().configuration_digest()
    );
    assert!(matches!(
        f.provider.start(&session, request(12345, HttpMethod::Get)),
        Err(HttpError::PermissionDenied)
    ));
    assert!(matches!(
        replacement.start(&session, request(12345, HttpMethod::Get)),
        Err(HttpError::PermissionDenied)
    ));
    drop(session);
    drop(replacement);
    f.clean().await;
}
