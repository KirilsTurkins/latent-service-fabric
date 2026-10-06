//! Real protected files, policy-backed local provider pins and atomic envelopes.
use super::*;
mod fixture;
use fixture::Fixture;
use latent_state::payload_references::{physical_owner_count, PayloadOwnerKind};

fn clock(now: u64) -> MaintenanceClock {
    MaintenanceClock {
        time: time(now),
        boot: [7; 32],
        monotonic_millis: now,
    }
}
fn publish(fixture: &Fixture, envelope: CompleteEnvelope) -> CommandRecord {
    match envelope.publish_with_payloads(&fixture.state, |authorities, payloads| {
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
            latent_effects::authority::EffectTime {
                unix_millis: 200,
                continuity_proven: true,
            },
        )?;
        Ok(())
    }) {
        PreparedDisposition::Confirmed { command, .. } => command,
        _ => panic!("expected original complete envelope to commit"),
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn physical_result_and_two_effect_owners_commit_together_and_response_expiry_releases_only_its_owner(
) {
    let fixture = Fixture::new();
    let claim = fixture.claim("physical-links");
    let view = fixture.state.snapshot().unwrap();
    let body = value(b"body");
    let intent = || StagedIntent {
        binding: "approved-event".into(),
        operation: "event".into(),
        payload: body.clone(),
        expires_at_millis: None,
    };
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        None,
        vec![intent(), intent()],
        body,
        &fixture.effects,
        time(200),
    )
    .unwrap();
    let first = fixture.capture().await;
    let identity = first.identity().clone();
    let attachments = vec![
        PayloadAttachment {
            target: PayloadAttachmentTarget::Result,
            payload: first,
        },
        PayloadAttachment {
            target: PayloadAttachmentTarget::Effect(0),
            payload: fixture.capture().await,
        },
        PayloadAttachment {
            target: PayloadAttachmentTarget::Effect(1),
            payload: fixture.capture().await,
        },
    ];
    let envelope = envelope
        .attach_verified_payloads(&view, &fixture.session, attachments)
        .unwrap();
    drop(view);
    let record = publish(&fixture, envelope);
    let view = fixture.state.snapshot().unwrap();
    let links = crate::atomic::payload_links::read(&view, &record)
        .unwrap()
        .unwrap();
    crate::atomic::payload_links::verify(&view, &record, &links).unwrap();
    assert_eq!(links.references.len(), 3);
    assert_eq!(physical_owner_count(&view, &identity).unwrap(), Some(3));
    drop(view);
    let maintenance = ResultMaintenanceOwner::default();
    maintenance
        .anchor(&fixture.state, None, clock(200), |_| Ok(()))
        .unwrap();
    maintenance
        .step(&fixture.state, clock(1200), |_| Ok(()))
        .unwrap();
    let view = fixture.state.snapshot().unwrap();
    let protected = CommandRecord::decode(
        &view
            .get(&crate::atomic::record::command_row_key(record.id))
            .unwrap()
            .unwrap(),
    )
    .unwrap();
    let links = crate::atomic::payload_links::read(&view, &protected)
        .unwrap()
        .unwrap();
    assert_eq!(links.references.len(), 2);
    assert!(links
        .references
        .iter()
        .all(|reference| reference.owner.kind == PayloadOwnerKind::Effect));
    assert_eq!(physical_owner_count(&view, &identity).unwrap(), Some(2));
    crate::atomic::payload_links::verify(&view, &protected, &links).unwrap();
    assert!(view
        .get(&crate::atomic::record::result_row_key(
            record.id,
            record.attempt
        ))
        .unwrap()
        .unwrap()
        .starts_with(b"LCE\0\x01"));
    drop(view);
    assert_eq!(
        fixture.provider.store().release_durable_reference(
            &TenantId("a".into()),
            &fixture.blob,
            &fixture.state,
            &|| Ok(())
        ),
        Err(latent_blobs::local::LocalBlobError::Busy)
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn lost_rejection_reply_reopen_and_paused_real_reader_survive_response_reference_release() {
    let mut fixture = Fixture::new();
    let claim = fixture.claim("physical-rejection");
    let view = fixture.state.snapshot().unwrap();
    let envelope = CompleteEnvelope::rejection(
        &view,
        claim,
        "business-rejected".into(),
        value(b"body"),
        time(200),
    )
    .unwrap();
    let pin = fixture.capture().await;
    let identity = pin.identity().clone();
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
    let record = publish(&fixture, envelope);
    let reader = fixture
        .provider
        .store()
        .capture_durable_reference(&TenantId("a".into()), &fixture.blob, &|| Ok(()))
        .unwrap();
    let ordinary = fixture
        .provider
        .store()
        .open_read(&TenantId("a".into()), &fixture.blob, &|| Ok(()))
        .unwrap();
    let (entered, observed) = std::sync::mpsc::channel();
    let (release, blocked) = std::sync::mpsc::channel();
    let worker = std::thread::spawn(move || {
        let checkpoints = std::sync::atomic::AtomicUsize::new(0);
        let mut bytes = [0; 4];
        let result = reader.reader().read(
            &latent_blobs::BlobRange {
                offset: 0,
                length: 4,
            },
            &mut bytes,
            &|| {
                if checkpoints.fetch_add(1, std::sync::atomic::Ordering::AcqRel) == 1 {
                    // The original native work and affine publication pin stay
                    // owned after the real FD read, before physical retirement.
                    entered.send(()).unwrap();
                    blocked
                        .recv_timeout(std::time::Duration::from_secs(5))
                        .unwrap();
                }
                Ok(())
            },
        );
        (reader, result, bytes)
    });
    observed
        .recv_timeout(std::time::Duration::from_secs(5))
        .unwrap();
    let old = std::mem::replace(
        &mut fixture.state,
        open(&fixture.root.path().join("placeholder.redb")),
    );
    drop(old);
    fixture.state = open(&fixture.root.path().join("state.redb"));
    let view = fixture.state.snapshot().unwrap();
    let links = crate::atomic::payload_links::read(&view, &record)
        .unwrap()
        .unwrap();
    crate::atomic::payload_links::verify(&view, &record, &links).unwrap();
    drop(view);
    let maintenance = ResultMaintenanceOwner::default();
    maintenance
        .anchor(&fixture.state, None, clock(200), |_| Ok(()))
        .unwrap();
    maintenance
        .step(&fixture.state, clock(1200), |_| Ok(()))
        .unwrap();
    let view = fixture.state.snapshot().unwrap();
    assert!(crate::atomic::payload_links::read(&view, &record)
        .unwrap()
        .is_none());
    assert_eq!(physical_owner_count(&view, &identity).unwrap(), Some(0));
    drop(view);
    assert_eq!(
        fixture.provider.store().release_durable_reference(
            &TenantId("a".into()),
            &fixture.blob,
            &fixture.state,
            &|| Ok(())
        ),
        Err(latent_blobs::local::LocalBlobError::Busy)
    );
    release.send(()).unwrap();
    let (reader, result, mut bytes) = worker.join().unwrap();
    assert_eq!(result.unwrap(), 4);
    assert_eq!(&bytes, b"body");
    drop(reader);
    fixture
        .provider
        .store()
        .release_durable_reference(
            &TenantId("a".into()),
            &fixture.blob,
            &fixture.state,
            &|| Ok(()),
        )
        .unwrap();
    assert_eq!(
        fixture
            .provider
            .store()
            .reclaim(4, &|| Ok(()))
            .unwrap()
            .objects,
        0
    );
    ordinary
        .read(
            &latent_blobs::BlobRange {
                offset: 0,
                length: 4,
            },
            &mut bytes,
            &|| Ok(()),
        )
        .unwrap();
    assert_eq!(&bytes, b"body");
    drop(ordinary);
    assert_eq!(
        fixture
            .provider
            .store()
            .reclaim(4, &|| Ok(()))
            .unwrap()
            .objects,
        1
    );
    assert_eq!(
        fixture
            .provider
            .store()
            .snapshot()
            .unwrap()
            .resident_disk_bytes,
        0
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn missing_reciprocal_owner_is_visible_recovery_failure_and_never_releases_required_bytes() {
    let fixture = Fixture::new();
    let claim = fixture.claim("physical-corruption");
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
    let record = publish(&fixture, envelope);
    let view = fixture.state.snapshot().unwrap();
    let links = crate::atomic::payload_links::read(&view, &record)
        .unwrap()
        .unwrap();
    let key = links.references[0].owner_key().unwrap();
    drop(view);
    fixture
        .state
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation { key, value: None }],
        })
        .unwrap();
    let view = fixture.state.snapshot().unwrap();
    let raw = view
        .get(&crate::atomic::record::command_row_key(record.id))
        .unwrap()
        .unwrap();
    assert_eq!(
        validate_linked_row(
            &view,
            &crate::atomic::record::command_row_key(record.id),
            &raw
        ),
        Err(latent_state::embedded::StoreError::Corrupt)
    );
    drop(view);
    let maintenance = ResultMaintenanceOwner::default();
    maintenance
        .anchor(&fixture.state, None, clock(200), |_| Ok(()))
        .unwrap();
    assert_eq!(
        maintenance.step(&fixture.state, clock(1200), |_| Ok(())),
        Err(AtomicError::Corrupt)
    );
    assert_eq!(
        fixture.provider.store().release_durable_reference(
            &TenantId("a".into()),
            &fixture.blob,
            &fixture.state,
            &|| Ok(())
        ),
        Err(latent_blobs::local::LocalBlobError::Corrupt)
    );
}
