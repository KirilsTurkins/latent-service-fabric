//! Real local blob, policy-backed capability session, and engine handoff.
use super::*;
mod fixture;
use fixture::Fixture;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_captured_blob_pin_moves_into_atomic_result_and_effect_owners() {
    let fixture = Fixture::new();
    let claim = fixture.claim("physical-handoff");
    let view = fixture.state.snapshot().unwrap();
    let body = value(b"body");
    let staged = StagedIntent {
        binding: "approved-event".into(),
        operation: "event".into(),
        payload: body.clone(),
        expires_at_millis: None,
    };
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        None,
        vec![staged],
        body,
        &fixture.effects,
        time(200),
    )
    .unwrap();
    let result = fixture.capture().await;
    let physical = result.identity().clone();
    let effect = fixture.capture().await;
    assert_eq!(
        fixture.provider.store().release_durable_reference(
            &TenantId("a".into()),
            &fixture.blob,
            &fixture.state,
            &|| Ok(()),
        ),
        Err(latent_blobs::local::LocalBlobError::Busy)
    );
    let envelope = envelope
        .attach_verified_payloads(
            &view,
            &fixture.session,
            vec![
                PayloadAttachment {
                    target: PayloadAttachmentTarget::Result,
                    payload: result,
                },
                PayloadAttachment {
                    target: PayloadAttachmentTarget::Effect(0),
                    payload: effect,
                },
            ],
        )
        .unwrap();
    drop(view);
    let command = match envelope.publish_with_payloads(&fixture.state, |authorities, payloads| {
        fixture
            .session
            .check_liveness()
            .map_err(|_| AtomicError::PermissionDenied)?;
        for payload in payloads {
            if !payload.uses_session(&fixture.session)
                || !payload
                    .matches_provider(&fixture.session)
                    .map_err(|_| AtomicError::PermissionDenied)?
            {
                return Err(AtomicError::PermissionDenied);
            }
        }
        let _fence = fixture.effects.commit_fence(
            authorities,
            EffectTime {
                unix_millis: 200,
                continuity_proven: true,
            },
        )?;
        Ok(())
    }) {
        PreparedDisposition::Confirmed { command, .. } => *command,
        _ => panic!("expected committed physical payload owners"),
    };
    let view = fixture.state.snapshot().unwrap();
    let links = super::super::payload_links::read(&view, &command)
        .unwrap()
        .unwrap();
    super::super::payload_links::verify(&view, &command, &links).unwrap();
    assert_eq!(links.references.len(), 2);
    let required_key = links.references[0].owner_key().unwrap();
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        Some(2)
    );
    drop(view);
    assert_eq!(
        fixture.provider.store().release_durable_reference(
            &TenantId("a".into()),
            &fixture.blob,
            &fixture.state,
            &|| Ok(()),
        ),
        Err(latent_blobs::local::LocalBlobError::Busy)
    );
    let Fixture {
        authority,
        provider,
        state,
        blob,
        session,
        effects,
        _root: root,
    } = fixture;
    drop(session);
    drop(provider);
    drop(effects);
    drop(authority);
    drop(state);
    let state = open(&root.path().join("state.redb"));
    let view = state.snapshot().unwrap();
    let quota = latent_state::tenant::inspect(&view, &TenantId("a".into()))
        .unwrap()
        .unwrap()
        .quota;
    let mut census = latent_state::tenant::TenantCensus::capture(
        &view,
        &[quota],
        latent_state::tenant::INSTALLED_GLOBAL_ALLOWANCE,
        std::time::Instant::now() + std::time::Duration::from_secs(20),
    )
    .unwrap();
    validate_view_observed(&view, |view, key, bytes| {
        if *key == latent_state::store_identity::StoreIdentity::row_key() {
            latent_state::store_identity::StoreIdentity::validate_row(key, bytes)
        } else {
            accounted::installed_codec(view, key, bytes)
        }
    }, |view, key, bytes| {
        use latent_state::embedded::StoreError;
        let contribution = match tenant_census_contribution(view, key, bytes) {
            Err(StoreError::UnsupportedFormat) => match latent_state::tenant::census_contribution(view, key, bytes) {
                Err(StoreError::UnsupportedFormat) => latent_effects::dispatch_store::DispatchCatalog::tenant_census_contribution(view, key, bytes),
                result => result,
            },
            result => result,
        }?;
        census.observe(key, bytes, contribution)
    }).unwrap();
    census.finish().unwrap();
    drop(view);
    let store = latent_blobs::local::LocalBlobStore::open_durable(
        &root.path().join("blobs"),
        "private",
        latent_blobs::local::LocalBlobLimits {
            maximum_objects: 4,
            maximum_object_bytes: 64,
            maximum_disk_bytes: 65536,
            maximum_stages: 4,
            maximum_stage_bytes: 128,
            maximum_handles: 8,
            maximum_chunk_bytes: 8,
            ..latent_blobs::local::LocalBlobLimits::default()
        },
        &state,
    )
    .unwrap();
    let view = state.snapshot().unwrap();
    let bytes = view.get(&required_key).unwrap().unwrap();
    store
        .verify_required_reference(&view, &required_key, &bytes, &|| Ok(()))
        .unwrap();
    let mut inventory = latent_blobs::local::RequiredBlobInventory::begin(&store, &view).unwrap();
    assert_eq!(
        inventory
            .next_page(&store, &view, 1, 1024, &|| Ok(()))
            .unwrap(),
        (1, false)
    );
    assert_eq!(
        inventory
            .next_page(&store, &view, 1, 1024, &|| Ok(()))
            .unwrap(),
        (1, true)
    );
    drop(view);
    let reader = store
        .open_read(&TenantId("a".into()), &blob, &|| Ok(()))
        .unwrap();
    let mut body = [0; 4];
    reader
        .read(
            &latent_blobs::BlobRange {
                offset: 0,
                length: 4,
            },
            &mut body,
            &|| Ok(()),
        )
        .unwrap();
    assert_eq!(&body, b"body");
    drop(reader);
    assert_eq!(
        store.release_durable_reference(&TenantId("a".into()), &blob, &state, &|| Ok(())),
        Err(latent_blobs::local::LocalBlobError::Busy)
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_publish_and_revoked_final_fence_cannot_install_captured_references() {
    let fixture = Fixture::new();
    let claim = fixture.claim("physical-refusal");
    let view = fixture.state.snapshot().unwrap();
    let make = |claim| {
        CompleteEnvelope::success(
            &view,
            claim,
            None,
            vec![],
            value(b"body"),
            &fixture.effects,
            time(200),
        )
        .unwrap()
    };
    let pin = fixture.capture().await;
    let physical = pin.identity().clone();
    let envelope = make(claim)
        .attach_verified_payloads(
            &view,
            &fixture.session,
            vec![PayloadAttachment {
                target: PayloadAttachmentTarget::Result,
                payload: pin,
            }],
        )
        .unwrap();
    let claim = match envelope.publish(&fixture.state, |_| {
        panic!("ordinary publish bypassed payload fence")
    }) {
        PreparedDisposition::KnownNotCommitted {
            command,
            reason: AtomicError::Invalid,
        } => *command,
        _ => panic!("expected ordinary publish refusal"),
    };
    let pin = fixture.capture().await;
    let envelope = make(claim)
        .attach_verified_payloads(
            &view,
            &fixture.session,
            vec![PayloadAttachment {
                target: PayloadAttachmentTarget::Result,
                payload: pin,
            }],
        )
        .unwrap();
    drop(view);
    assert!(matches!(
        envelope.publish_with_payloads(&fixture.state, |_, _| Err(AtomicError::PermissionDenied)),
        PreparedDisposition::KnownNotCommitted {
            reason: AtomicError::PermissionDenied,
            ..
        }
    ));
    let view = fixture.state.snapshot().unwrap();
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        None
    );
    let (command, result) = inspect(
        &view,
        &fixture.input("physical-refusal").key,
        time(201),
        |_, _| Ok(()),
    )
    .unwrap();
    assert_eq!(command.outcome(), Outcome::Pending);
    assert!(result.is_none());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn captured_blob_cannot_be_attached_through_a_different_activation_session() {
    let fixture = Fixture::new();
    let (request, control) = fixture.authority.request("foreign-activation");
    let foreign = fixture.authority.session(&request, &control);
    let claim = fixture.claim("foreign-payload-session");
    let view = fixture.state.snapshot().unwrap();
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        None,
        vec![],
        value(b"body"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    let pin = fixture.capture().await;
    let physical = pin.identity().clone();
    assert!(matches!(
        envelope.attach_verified_payloads(
            &view,
            &foreign,
            vec![PayloadAttachment {
                target: PayloadAttachmentTarget::Result,
                payload: pin
            },]
        ),
        Err(AtomicError::PermissionDenied)
    ));
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        None
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn same_store_label_does_not_bind_a_different_engine_view() {
    let fixture = Fixture::new();
    let claim = fixture.claim("foreign-store-view");
    let view = fixture.state.snapshot().unwrap();
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        None,
        vec![],
        value(b"body"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    drop(view);
    let foreign = open(&fixture._root.path().join("foreign.redb"));
    let view = foreign.snapshot().unwrap();
    let identity =
        latent_state::store_identity::StoreIdentity::new("payload-envelope-a".into()).unwrap();
    let initialization = identity.prepare_initialization(&view).unwrap().unwrap();
    drop(view);
    foreign.apply(initialization).unwrap();
    let pin = fixture.capture().await;
    let view = foreign.snapshot().unwrap();
    assert!(matches!(
        envelope.attach_verified_payloads(
            &view,
            &fixture.session,
            vec![PayloadAttachment {
                target: PayloadAttachmentTarget::Result,
                payload: pin
            },]
        ),
        Err(AtomicError::PermissionDenied)
    ));
    drop(view);
    let claim = fixture.claim("foreign-store-publication");
    let view = fixture.state.snapshot().unwrap();
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        None,
        vec![],
        value(b"body"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    let pin = fixture.capture().await;
    let envelope = envelope
        .attach_verified_payloads(
            &view,
            &fixture.session,
            vec![PayloadAttachment {
                target: PayloadAttachmentTarget::Result,
                payload: pin,
            }],
        )
        .unwrap();
    drop(view);
    assert!(matches!(
        envelope
            .publish_with_payloads(&foreign, |_, _| panic!("foreign engine reached acceptance")),
        PreparedDisposition::KnownNotCommitted {
            reason: AtomicError::PermissionDenied,
            ..
        }
    ));
}
