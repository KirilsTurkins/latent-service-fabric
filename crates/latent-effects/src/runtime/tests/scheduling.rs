use super::*;

#[tokio::test]
async fn indexed_hot_tenant_backlog_does_not_starve_cold_tenant_or_allocate_backlog_workers() {
    let fixture = Fixture::new().await;
    for index in 1..=40 {
        fixture
            .seed(index, "hot-tenant", "old-publication", profile("test.v1"))
            .await;
    }
    let cold = fixture
        .seed(41, "cold-tenant", "new-publication", profile("test.v1"))
        .await;
    let (adapter, mut entered) = Adapter::new("test.v1", Some("hot-tenant"));
    let mut dispatcher = fixture
        .start(config(), vec![adapter.clone()], None)
        .await
        .unwrap();
    let first = event(&mut entered).await;
    let second = event(&mut entered).await;
    let hot = if first.ticket.is_some() {
        first
    } else {
        second
    };
    wait_disposition(&fixture, &cold, Disposition::ProviderAcknowledged).await;
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 2);
    let snapshot = dispatcher.refresh_counts().await.unwrap();
    assert_eq!(snapshot.durable.pending, 39);
    assert_eq!(snapshot.durable.active, 1);
    assert_eq!(snapshot.durable.acknowledged, 1);
    assert_eq!(snapshot.accepted_effects, 1);
    assert_eq!(snapshot.live_tenants, 1);
    assert_eq!(snapshot.live_workers, 3);
    assert!(snapshot.retained_attempt_bytes < 2 * DispatcherConfig::ATTEMPT_BYTES);
    dispatcher.close();
    adapter.gates.release(hot.ticket.unwrap()).unwrap();
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 2);
    fixture.finish().await;
}

#[tokio::test]
async fn exact_retained_profile_inventory_blocks_missing_decoder_without_redirecting() {
    let fixture = Fixture::new().await;
    let old = fixture
        .seed(1, "tenant-a", "old-publication", profile("old.v1"))
        .await;
    let new = fixture
        .seed(2, "tenant-a", "new-publication", profile("new.v1"))
        .await;
    let (new_adapter, mut entered) = Adapter::new("new.v1", None);
    let mut dispatcher = fixture
        .start(config(), vec![new_adapter.clone()], None)
        .await
        .unwrap();
    event(&mut entered).await;
    wait_disposition(&fixture, &old, Disposition::PolicyBlocked).await;
    wait_disposition(&fixture, &new, Disposition::ProviderAcknowledged).await;
    let first = dispatcher
        .required_profile_page(None, 1, 4096)
        .await
        .unwrap();
    assert_eq!(first.rows.len(), 1);
    assert_eq!(first.rows[0].profile, profile("old.v1"));
    assert_eq!(first.rows[0].command, old.link().command);
    assert_eq!(first.rows[0].namespace_incarnation, 7);
    assert!(first.rows[0].unresolved);
    let second = dispatcher
        .required_profile_page(first.resume, 1, 4096)
        .await
        .unwrap();
    assert_eq!(second.rows[0].profile, profile("new.v1"));
    assert_eq!(new_adapter.sent.load(Ordering::SeqCst), 1);
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn compatible_retained_decoders_dispatch_old_and_new_publications_without_reinterpreting_payloads(
) {
    let fixture = Fixture::new().await;
    let old = fixture
        .seed(1, "tenant-a", "old-publication", profile("old.v1"))
        .await;
    let new = fixture
        .seed(2, "tenant-a", "new-publication", profile("new.v1"))
        .await;
    let (old_adapter, mut old_entered) = Adapter::new("old.v1", None);
    let (new_adapter, mut new_entered) = Adapter::new("new.v1", None);
    let mut dispatcher = fixture
        .start(
            config(),
            vec![old_adapter.clone(), new_adapter.clone()],
            None,
        )
        .await
        .unwrap();
    assert_eq!(event(&mut old_entered).await.effect, old.link().effect);
    assert_eq!(event(&mut new_entered).await.effect, new.link().effect);
    wait_disposition(&fixture, &old, Disposition::ProviderAcknowledged).await;
    wait_disposition(&fixture, &new, Disposition::ProviderAcknowledged).await;
    let retained = fixture.record(&old).await.authority().unwrap();
    assert_eq!(retained.scope().publication, "old-publication");
    assert_eq!(retained.link().command, "command-1");
    assert_eq!(retained.link().commit, "commit-1");
    assert_eq!(retained.payload_digest(), old.payload_digest());
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn pause_and_current_revocation_prevent_claim_without_refunding_unrelated_live_work() {
    let fixture = Fixture::new().await;
    let authority = fixture
        .seed(1, "tenant-a", "publication", profile("test.v1"))
        .await;
    let (adapter, _entered) = Adapter::new("test.v1", None);
    let mut dispatcher = fixture
        .start(
            DispatcherConfig {
                start_paused: true,
                ..config()
            },
            vec![adapter.clone()],
            None,
        )
        .await
        .unwrap();
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::Pending
    );
    let paused = dispatcher.snapshot().unwrap();
    assert_eq!(paused.claims, 0);
    assert_eq!(paused.retained_attempt_bytes, 0);
    assert!(paused.live_workers > 0);
    let mut revoked = rule("tenant-a", "publication", profile("test.v1"));
    revoked.policy_revision = 2;
    revoked.enabled = false;
    fixture.authority.publish(revoked).unwrap();
    dispatcher.resume().unwrap();
    wait_disposition(&fixture, &authority, Disposition::PolicyBlocked).await;
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 0);
    assert_eq!(dispatcher.snapshot().unwrap().physical_owners, 0);
    assert_eq!(dispatcher.snapshot().unwrap().claims, 0);
    dispatcher.pause();
    fixture.clock.continuous.store(false, Ordering::SeqCst);
    assert_eq!(
        dispatcher.resume(),
        Err(DispatcherError::Authority(
            AuthorityError::ClockDiscontinuity
        ))
    );
    assert!(dispatcher.snapshot().unwrap().paused);
    fixture.clock.continuous.store(true, Ordering::SeqCst);
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn publication_inventory_continues_only_from_an_authorized_original_effect() {
    use latent_state::embedded::StoreError;

    let fixture = Fixture::new().await;
    for index in 1..=40 {
        let (tenant, publication) = match index % 4 {
            1 => ("tenant-a", "other-publication"),
            3 => ("tenant-b", "retiring-publication"),
            _ => ("tenant-a", "retiring-publication"),
        };
        fixture
            .seed(index, tenant, publication, profile("test.v1"))
            .await;
    }
    fixture
        .store
        .with_store(StoreIoKind::RecoveryRead, 1024 * 1024, move |store| {
            let view = store.snapshot()?;
            let page = |after: Option<&str>| {
                DispatchCatalog::publication_effect_page(
                    &view,
                    "tenant-a",
                    "orders",
                    7,
                    "retiring-publication",
                    after,
                    &mut || Ok(()),
                )
            };
            let first = page(None)?;
            assert_eq!(first.effects.len(), 16);
            for (index, effect) in (2..=32).step_by(2).zip(&first.effects) {
                assert_eq!(effect.effect_id, format!("{index:064x}"));
                assert_eq!(effect.disposition, Disposition::Pending);
                assert_eq!(effect.command_id, format!("command-{index}"));
            }
            assert_eq!(
                first.after_effect.as_deref(),
                Some(first.effects[15].effect_id.as_str())
            );
            let second = page(first.after_effect.as_deref())?;
            assert_eq!(second.effects.len(), 4);
            assert_eq!(second.effects[0].effect_id, format!("{:064x}", 34));
            assert!(second.after_effect.is_none());
            assert!(matches!(
                page(Some(&format!("{:064x}", 3))),
                Err(StoreError::Conflict)
            ));
            assert!(matches!(
                page(Some(&format!("{:064x}", 1))),
                Err(StoreError::Conflict)
            ));
            Ok(())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    fixture.finish().await;
}
