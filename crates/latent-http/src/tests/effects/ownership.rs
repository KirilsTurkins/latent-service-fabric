use super::*;
use tokio::net::TcpListener;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unpolled_acceptance_releases_prepaid_buffers_and_never_opens_a_socket() {
    let endpoint = Endpoint::new(Arc::new(Clock(AtomicU64::new(100))), Fault::Normal).await;
    let fixture = Fixture::new(endpoint.port, endpoint.root_certificate.clone(), 2000).await;
    let before = fixture.snapshot().await;
    let (authority, payload, mut record) = fixture.retained(30, b"not yet committed to send");
    let (context, _attempt, operation) = fixture.accepted(&authority, payload, &mut record);
    assert!(fixture.snapshot().await.metadata_bytes > before.metadata_bytes);
    assert_eq!(endpoint.attempts(), (0, 0));
    drop(operation); // No poll and no send marker: known nonexecution.
    context.retire().unwrap();
    assert_eq!(fixture.snapshot().await, before);
    fixture.finish().await;
    endpoint.finish(0).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn current_credentials_rotate_and_revocation_or_expiry_denies_new_effect_acceptance() {
    let endpoint = Endpoint::new(Arc::new(Clock(AtomicU64::new(100))), Fault::Normal).await;
    let mut fixture = Fixture::new(endpoint.port, endpoint.root_certificate.clone(), 2000).await;
    assert_eq!(
        fixture.run(31, b"first").await.receipt.disposition,
        Disposition::ProviderAcknowledged
    );
    fixture.rotate().await;
    endpoint.token("synthetic-beta");
    assert_eq!(
        fixture
            .run(32, b"current secret generation")
            .await
            .receipt
            .disposition,
        Disposition::ProviderAcknowledged
    );
    let (authority, payload, mut record) =
        fixture.retained(33, b"retained before publication revoke");
    let attempt = record.claim(1, fixture.clock.observe()).unwrap();
    let mut context = fixture
        .authority
        .accept(&authority, attempt.attempt(), fixture.clock.observe())
        .unwrap();
    fixture.rule.policy_revision = 2;
    fixture.rule.enabled = false;
    fixture.authority.publish(fixture.rule.clone()).unwrap();
    assert_eq!(
        context.accept_with(&authority, 1, fixture.clock.observe(), |_grant| {
            panic!("revoked publication/namespace must not reach adapter")
        }),
        Err(AuthorityError::PolicyBlocked)
    );
    context.retire().unwrap();
    drop(payload);
    fixture.rule.policy_revision = 3;
    fixture.rule.enabled = true;
    fixture.authority.publish(fixture.rule.clone()).unwrap();
    let (authority, payload, mut record) = fixture.retained(34, b"expires before polling");
    let (context, attempt, operation) = fixture.accepted(&authority, payload, &mut record);
    record.begin_send(&attempt).unwrap();
    fixture.clock.0.store(10_100, Ordering::SeqCst);
    let result = watched(operation).await;
    assert_eq!(result.receipt.disposition, Disposition::Expired);
    assert!(result.retry.is_none());
    context.retire().unwrap();
    assert_eq!(endpoint.attempts(), (2, 0));
    fixture.finish().await;
    endpoint.finish(2).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn credential_epoch_replacement_fails_closed_before_send_and_requires_current_effect_rule() {
    use latent_capabilities::broker::secrets::CredentialScope;
    let endpoint = Endpoint::new(Arc::new(Clock(AtomicU64::new(100))), Fault::Normal).await;
    let mut fixture = Fixture::new(endpoint.port, endpoint.root_certificate.clone(), 2000).await;
    let (authority, payload, mut record) = fixture.retained(35, b"old epoch accepted but unpolled");
    let (context, attempt, operation) = fixture.accepted(&authority, payload, &mut record);
    let origin = fixture.http.provider.inner.config.destinations[0]
        .origin
        .clone();
    let binding = fixture
        .secrets
        .bind_credential(
            CredentialScope {
                tenant: TenantId("a".into()),
                provider_id: "http".into(),
                origin,
            },
            "effect-auth".into(),
        )
        .unwrap();
    fixture.adapter.replace_credential(2, binding).unwrap();
    record.begin_send(&attempt).unwrap();
    assert_eq!(
        watched(operation).await.receipt.disposition,
        Disposition::PolicyBlocked
    );
    context.retire().unwrap();
    assert_eq!(endpoint.attempts(), (0, 0));
    fixture.rule.policy_revision = 2;
    fixture.rule.credential_epoch = 2;
    fixture.authority.publish(fixture.rule.clone()).unwrap();
    assert_eq!(
        fixture
            .run(36, b"current approved epoch")
            .await
            .receipt
            .disposition,
        Disposition::ProviderAcknowledged
    );
    fixture.secrets.reload(1, vec![]).unwrap().await.unwrap();
    assert_eq!(
        fixture
            .run(37, b"revoked protected material")
            .await
            .receipt
            .disposition,
        Disposition::PolicyBlocked
    );
    assert_eq!(endpoint.attempts(), (1, 0));
    fixture.finish().await;
    endpoint.finish(1).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn caller_loss_during_send_or_read_keeps_physical_owner_until_real_socket_retirement() {
    for during_send in [true, false] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let (root, acceptor) = certificate();
        let (started, ready) = tokio::sync::oneshot::channel();
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut stream = acceptor.accept(stream).await.unwrap();
            if during_send {
                assert_eq!(stream.read(&mut [0]).await.unwrap(), 1);
            } else {
                assert!(endpoint::read_wire(&mut stream).await.is_some());
            }
            started.send(()).unwrap();
            let mut buffer = [0; 4096];
            loop {
                match watched(stream.read(&mut buffer)).await {
                    Ok(0) | Err(_) => break,
                    Ok(_) => {}
                }
            }
            // The retired first socket is insufficient evidence of nonexecution.
            // A subsequent status lookup gets an explicit ambiguous response.
            let (stream, _) = listener.accept().await.unwrap();
            let mut stream = acceptor.accept(stream).await.unwrap();
            let lookup = endpoint::read_wire(&mut stream).await.unwrap();
            assert_eq!(lookup.method, "GET");
            let _ = stream
                .write_all(b"HTTP/1.1 404 Absent\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                .await;
        });
        let fixture = Fixture::new(port, root, 1000).await;
        let (authority, payload, mut record) = fixture.retained(38, &vec![b'x'; 65_536]);
        let (context, attempt, operation) = fixture.accepted(&authority, payload, &mut record);
        record.begin_send(&attempt).unwrap();
        let (completed, completion) = tokio::sync::oneshot::channel();
        let physical = tokio::spawn(async move {
            let outcome = operation.await;
            context.retire().unwrap();
            let disposition = outcome.receipt.disposition;
            let _ = completed.send(outcome);
            disposition
        });
        watched(ready).await.unwrap();
        drop(completion); // Simulate caller cancellation; it owns no provider future.
        assert_eq!(fixture.authority.owners().unwrap().physical, 1);
        assert_eq!(fixture.snapshot().await.connections, 1);
        assert_eq!(watched(physical).await.unwrap(), Disposition::Uncertain);
        watched(server).await.unwrap();
        assert_eq!(fixture.snapshot().await.connections, 0);
        fixture.finish().await;
    }
}
