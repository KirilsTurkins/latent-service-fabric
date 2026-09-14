use super::*;
use server::{Reply, Server};

#[tokio::test]
async fn aggregate_plaintext_exhaustion_rejects_before_opening_another_connection() {
    let mut held_reply = Reply::value(1, "Alpha");
    held_reply.gated = true;
    let server = Server::new(vec![held_reply, Reply::value(1, "Alpha")]).await;
    let mut config = server.config.clone();
    config.limits.maximum_value_bytes = 8;
    config.limits.maximum_response_bytes = 1024;
    config.limits.maximum_plaintext_bytes = 3 * 1024 + 8 + 65536;
    let maximum = config.limits.maximum_plaintext_bytes;
    let f = setup::fixture(config, None).await;
    let (session, _) = f.session("bounded-concurrent-plaintext");
    let first = f.provider.read(&session, "allowed".into()).unwrap();
    tokio::pin!(first);
    tokio::select! {
        _ = server.event.notified() => (),
        _ = tokio::time::sleep(Duration::from_secs(1)) => panic!("server request deadline"),
        _ = &mut first => panic!("held response completed"),
    }
    assert_eq!(
        f.provider.snapshot().unwrap().retained_plaintext_bytes,
        maximum
    );
    assert!(matches!(
        f.provider.read(&session, "allowed".into()).unwrap().await,
        Err(SecretError::Unavailable)
    ));
    assert_eq!(f.provider.snapshot().unwrap().remote_read_attempts, 1);
    assert_eq!(
        f.provider.snapshot().unwrap().retained_plaintext_bytes,
        maximum
    );
    server.release.notify_one();
    // The newer failed request still fences the older selected sequence.
    assert!(matches!(first.await, Err(SecretError::Unavailable)));
    drop(session);
    setup::idle(&f).await;
    assert_eq!(f.provider.snapshot().unwrap().retained_plaintext_bytes, 0);
    assert_eq!(invoke(&f, 0).await, marker(b'A', b'1', 5));
    shutdown(&f).await;
    server.close().await;
}

#[tokio::test]
async fn replacement_requires_a_fresh_plan_and_keeps_old_owners_until_drain() {
    use latent_capabilities::broker::secrets::CredentialScope;
    let server = Server::new(vec![Reply::value(1, "Alpha"), Reply::value(1, "Alpha")]).await;
    let f = setup::fixture(server.config.clone(), None).await;
    let (old_session, _) = f.session("old-provider-generation");
    let held = f
        .provider
        .read(&old_session, "allowed".into())
        .unwrap()
        .await
        .unwrap();
    let credentials = ["tests", "other"]
        .into_iter()
        .map(|tenant| {
            f.secrets
                .bind_credential(
                    CredentialScope {
                        tenant: TenantId(tenant.into()),
                        provider_id: "secrets".into(),
                        origin: server.config.transport.destinations[0].origin.clone(),
                    },
                    "vault-auth".into(),
                )
                .unwrap()
        })
        .collect();
    let next = VaultSecretProvider::install(
        f.pools.clone(),
        "secrets",
        2,
        1,
        server.config.clone(),
        credentials,
        f.secret_clock.clone(),
    )
    .unwrap();
    let rejected = match f.provider.read(&old_session, "allowed".into()) {
        Ok(future) => future.await,
        Err(error) => Err(error),
    };
    assert!(rejected.is_err());
    assert!(f.provider.snapshot().unwrap().retained_plaintext_bytes > 0);
    // Accepted old work retains its physical owners; explicit close prevents
    // any still-pending copy and keeps the value charged until held is dropped.
    f.provider.close();
    assert!(f.provider.snapshot().unwrap().retained_plaintext_bytes > 0);
    assert!(matches!(
        held.disclose(&mut |_| panic!("closed old provider copied")),
        Err(SecretError::Unavailable)
    ));
    drop(old_session);
    let reference = next.reference();
    let definition = latent_artifacts::package::artifact_blob_digest(b"secret-fixture-binding-v1");
    let compile = || {
        f.broker.compile_invocation_plan(
            &f.revision,
            Some(&latent_core::DeploymentId("secret-deployment".into())),
            &[CapabilityBindingSpec {
                definition_digest: Some(&definition),
                provider: &reference,
                imported_operations: &["read".into()],
                policy_ids: &["p".into()],
                provider_binding_id: "binding",
                deployment_restriction_json: br#"{"operations":[]}"#,
            }],
            &f.publication,
            &[],
            &[],
            &[],
            None,
            Instant::now() + Duration::from_secs(1),
        )
    };
    assert!(compile().is_err()); // Existing binding still authorizes epoch one.
    let expected = f
        .policies
        .get(
            "tests",
            latent_policy::capability::RecordKind::ProviderBinding,
            "binding",
            8192,
            Instant::now() + Duration::from_secs(1),
        )
        .unwrap()
        .value()
        .as_ref()
        .unwrap()
        .revision;
    f.policies.mutate(latent_policy::capability::MutationRequest {
        tenant: "tests", actor: "operator", id: "binding",
        kind: latent_policy::capability::RecordKind::ProviderBinding,
        operation_id: "replace-vault-binding", expected_revision: expected,
        document: Some(&serde_json::to_vec(&serde_json::json!({
            "formatVersion":1,"tenant":"tests","capability":component::CAP,
            "providerProfile":latent_secrets::vault::VAULT_SECRETS_PROFILE,
            "configurationDigest":reference.configuration_digest(),"configurationEpoch":2,
            "restriction":{"operations":[]}
        })).unwrap()),
    }, Instant::now() + Duration::from_secs(1), |_| Ok(())).unwrap();
    let plan = compile().unwrap();
    let (request, control) = f.request("fresh-provider-generation", 0);
    let session = f
        .broker
        .open_session(plan, &request, &control, &f.publication)
        .unwrap();
    let value = next
        .read(&session, "allowed".into())
        .unwrap()
        .await
        .unwrap();
    let lowered = value
        .disclose(&mut |v| assert_eq!(v.bytes, b"Alpha"))
        .unwrap();
    drop((lowered, session));
    assert_eq!(next.snapshot().unwrap().configuration_epoch, 2);
    next.close();
    shutdown(&f).await;
    server.close().await;
}

#[tokio::test]
async fn malformed_oversized_and_denied_responses_are_redacted_and_reclaimed() {
    let replies = [
        (403, "raw-token-diagnostic".into()),
        (404, "raw-secret-diagnostic".into()),
        (200, "{\"data\":null,\"data\":{}}".into()),
        (200, "x".repeat(70000)),
        (200, Reply::value(1, "too-large").body),
    ];
    let server = Server::new(
        replies
            .into_iter()
            .map(|(status, body)| Reply {
                status,
                body,
                gated: false,
            })
            .collect(),
    )
    .await;
    let mut config = server.config.clone();
    config.limits.maximum_value_bytes = 8;
    let f = setup::fixture(config, None).await;
    for error in [1001, 1000, 1003, 1003, 1003] {
        assert_eq!(invoke(&f, 0).await, error);
        let snapshot = f.provider.snapshot().unwrap();
        assert_eq!(
            (snapshot.cached_values, snapshot.retained_plaintext_bytes),
            (0, 0)
        );
    }
    assert_eq!(f.provider.snapshot().unwrap().remote_read_attempts, 5);
    shutdown(&f).await;
    server.close().await;
}

#[tokio::test]
async fn evicted_disclosures_keep_plaintext_charged_until_their_last_owner_drops() {
    let server = Server::new(vec![Reply::value(1, "Alpha"), Reply::value(1, "Alpha")]).await;
    let mut config = server.config.clone();
    config.limits.maximum_value_bytes = 8;
    config.limits.maximum_cache_bytes = 8;
    config.limits.maximum_cache_entries = 1;
    let f = setup::fixture(config, None).await;
    let (session, control) = f.session("bounded-retention");
    let first = f
        .provider
        .read(&session, "allowed".into())
        .unwrap()
        .await
        .unwrap();
    let second = f
        .provider
        .read(&session, "opaque".into())
        .unwrap()
        .await
        .unwrap();
    let snapshot = f.provider.snapshot().unwrap();
    assert_eq!(
        (
            snapshot.cached_values,
            snapshot.cached_bytes,
            snapshot.retained_plaintext_bytes
        ),
        (1, 8, 16)
    );
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        2
    );
    drop(first);
    assert_eq!(f.provider.snapshot().unwrap().retained_plaintext_bytes, 8);
    f.provider.close();
    assert_eq!(f.provider.snapshot().unwrap().retained_plaintext_bytes, 8);
    let mut copied = false;
    assert!(matches!(
        second.disclose(&mut |_| copied = true),
        Err(SecretError::Unavailable)
    ));
    assert!(!copied);
    drop(session);
    assert_eq!(f.provider.snapshot().unwrap().retained_plaintext_bytes, 0);
    shutdown(&f).await;
    server.close().await;
}

#[tokio::test]
async fn a_late_response_cannot_replace_or_disclose_an_older_latest_version() {
    let mut late = Reply::value(1, "Alpha");
    late.gated = true;
    let server = Server::new(vec![late, Reply::value(2, "Beta")]).await;
    let f = setup::fixture(server.config.clone(), None).await;
    let (session, control) = f.session("same-reference-concurrent-reads");
    let older = f.provider.read(&session, "allowed".into()).unwrap();
    tokio::pin!(older);
    tokio::select! {
        _ = server.event.notified() => (),
        _ = tokio::time::sleep(Duration::from_secs(1)) => panic!("server request deadline"),
        _ = &mut older => panic!("held first response completed"),
    }
    let newer = f
        .provider
        .read(&session, "allowed".into())
        .unwrap()
        .await
        .unwrap();
    server.release.notify_one();
    assert!(matches!(older.await, Err(SecretError::Unavailable)));
    let mut copied = false;
    let lowered = newer
        .disclose(&mut |value| {
            assert_eq!(value.bytes, b"Beta");
            assert_eq!(value.version, "2");
            copied = true;
        })
        .unwrap();
    assert!(copied);
    drop(lowered);
    let cached = f
        .provider
        .read(&session, "allowed".into())
        .unwrap()
        .await
        .unwrap();
    let lowered = cached
        .disclose(&mut |value| assert_eq!(value.version, "2"))
        .unwrap();
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        2
    );
    drop((lowered, session));
    setup::idle(&f).await;
    shutdown(&f).await;
    server.close().await;
}
