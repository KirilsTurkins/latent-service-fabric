//! Real local blob, policy-backed capability session, and engine handoff.
use super::*;
mod fixture;
use fixture::Fixture;

const CHILD_BOUNDARY: &[u8] = b"PAYLOAD_PROCESS_BOUNDARY";
const CHILD_TEST: &str = "atomic::tests::payloads::owned_payload_process_child";

/// Producer for the separate standalone protected-startup qualification. The
/// orchestrator owns and removes the temporary parent after both processes exit.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the standalone linked-payload qualification orchestrator"]
async fn export_standalone_linked_payload() {
    use std::io::Write;
    let report = std::path::PathBuf::from(
        std::env::var_os("LSF_LINKED_PAYLOAD_REPORT").expect("orchestrator report path"),
    );
    assert_eq!(
        std::fs::canonicalize(report.parent().unwrap()).unwrap(),
        std::fs::canonicalize(std::env::temp_dir()).unwrap()
    );
    let fixture = Fixture::for_standalone_recovery();
    let claim = fixture.claim("standalone-recovery-proof");
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
        envelope.publish_with_payloads(&fixture.state, |authorities, payloads| {
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
        }),
        PreparedDisposition::Confirmed { .. }
    ));
    let Fixture {
        authority,
        provider,
        state,
        blob: _,
        session,
        effects,
        _root: root,
    } = fixture;
    drop(session);
    drop(provider);
    drop(effects);
    drop(authority);
    drop(state);
    let path = root.keep();
    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(report)
        .unwrap()
        .write_all(path.as_os_str().as_encoded_bytes())
        .unwrap();
}

fn stop_at_boundary() -> ! {
    use std::io::Write;
    println!("{}", std::str::from_utf8(CHILD_BOUNDARY).unwrap());
    std::io::stdout().flush().unwrap();
    loop {
        std::thread::park();
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn owned_payload_process_child() {
    let Ok(report) = std::env::var("LSF_PAYLOAD_CHILD_REPORT") else {
        return;
    };
    let before = std::env::var("LSF_PAYLOAD_CHILD_BEFORE").unwrap() == "true";
    let fixture = Fixture::new();
    std::fs::write(report, fixture._root.path().to_str().unwrap()).unwrap();
    let claim = fixture.claim("process-payload");
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
    if before {
        let _ = envelope.publish_with_payloads(&fixture.state, |_, _| stop_at_boundary());
    } else {
        let _ = envelope.publish_payload_checkpoint(
            &fixture.state,
            |_, _| Ok(()),
            || stop_at_boundary(),
        );
    }
    panic!("the parent must terminate the original process at its observed boundary");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn process_loss_before_and_after_commit_preserves_blob_custody() {
    use latent_test_process::process::{OwnedProcess, ProcessLimits};
    use sha2::{Digest, Sha256};
    for before in [true, false] {
        let root = tempfile::tempdir().unwrap();
        let report = root.path().join("child-root.txt");
        let mut command = std::process::Command::new(std::env::current_exe().unwrap());
        command
            .args(["--exact", CHILD_TEST, "--nocapture"])
            .env("TMPDIR", root.path())
            .env("LSF_PAYLOAD_CHILD_REPORT", &report)
            .env("LSF_PAYLOAD_CHILD_BEFORE", before.to_string());
        let child = OwnedProcess::spawn(command, ProcessLimits::default()).unwrap();
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(20);
        let mut observed = false;
        while std::time::Instant::now() < deadline {
            if child
                .stdout_snapshot()
                .unwrap()
                .windows(CHILD_BOUNDARY.len())
                .any(|window| window == CHILD_BOUNDARY)
            {
                observed = true;
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(5)).await;
        }
        let retired = child.terminate().await.unwrap();
        assert!(
            observed && !retired.status.success(),
            "original process did not reach its payload boundary"
        );
        let child_root = std::path::PathBuf::from(std::fs::read_to_string(report).unwrap());
        assert!(child_root.starts_with(root.path()));
        let state = open(&child_root.join("state.redb"));
        let view = state.snapshot().unwrap();
        let page = view
            .scan_after(Family::Command, b"command-v1\0", None, 2, 128 * 1024)
            .unwrap();
        assert_eq!(page.rows.len(), 1);
        let command = CommandRecord::decode(&page.rows[0].1).unwrap();
        assert_eq!(
            command.outcome(),
            if before {
                Outcome::Pending
            } else {
                Outcome::Committed
            }
        );
        let owners =
            latent_state::payload_references::required_owner_page(&view, None, 2, 2048).unwrap();
        assert_eq!(owners.references.len(), usize::from(!before));
        validate_payload_census(&view);
        drop(view);
        let owner = latent_blobs::local::LocalBlobStore::open_durable(
            &child_root.join("blobs"),
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
        let blob = latent_blobs::BlobReference {
            digest: latent_core::BlobDigest(format!(
                "sha256:{:x}",
                latent_core::digest::HexDigest(Sha256::digest(b"body"))
            )),
            size_bytes: 4,
            media_type: "application/octet-stream".into(),
            tenant: TenantId("a".into()),
            metadata: latent_core::Metadata::new(),
        };
        let reader = owner
            .open_read(&TenantId("a".into()), &blob, &|| Ok(()))
            .unwrap();
        let mut bytes = [0; 4];
        reader
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
        let release =
            owner.release_durable_reference(&TenantId("a".into()), &blob, &state, &|| Ok(()));
        assert_eq!(
            release,
            Err(if before {
                latent_blobs::local::LocalBlobError::Corrupt
            } else {
                latent_blobs::local::LocalBlobError::Busy
            })
        );
    }
}

fn validate_payload_census(
    view: &latent_state::embedded::ReadView,
) -> latent_state::tenant::TenantUsage {
    use latent_state::{
        embedded::StoreError,
        tenant::{self, TenantCensus, INSTALLED_GLOBAL_ALLOWANCE},
    };
    let record = tenant::inspect(view, &TenantId("a".into()))
        .unwrap()
        .unwrap();
    let mut census = TenantCensus::capture(
        view,
        &[record.quota],
        INSTALLED_GLOBAL_ALLOWANCE,
        std::time::Instant::now() + std::time::Duration::from_secs(20),
    )
    .unwrap();
    validate_view_observed(
        view,
        |view, key, bytes| {
            if *key == latent_state::store_identity::StoreIdentity::row_key() {
                latent_state::store_identity::StoreIdentity::validate_row(key, bytes)
            } else {
                accounted::installed_codec(view, key, bytes)
            }
        },
        |view, key, bytes| {
            let contribution = match tenant_census_contribution(view, key, bytes) {
                Err(StoreError::UnsupportedFormat) => match tenant::census_contribution(
                    view, key, bytes,
                ) {
                    Err(StoreError::UnsupportedFormat) => {
                        latent_effects::dispatch_store::DispatchCatalog::tenant_census_contribution(
                            view, key, bytes,
                        )
                    }
                    result => result,
                },
                result => result,
            }?;
            census.observe(key, bytes, contribution)
        },
    )
    .unwrap();
    census.finish().unwrap();
    record.usage
}

fn publish_payload_envelope(fixture: &Fixture, envelope: CompleteEnvelope) -> CommandRecord {
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
            EffectTime {
                unix_millis: 200,
                continuity_proven: true,
            },
        )?;
        Ok(())
    }) {
        PreparedDisposition::Confirmed { command, .. } => *command,
        _ => panic!("expected atomic payload disposition"),
    }
}

fn state_scope_a() -> StateScope {
    StateScope {
        tenant: TenantId("a".into()),
        namespace: StateNamespaceId("aggregate".into()),
        incarnation: 1,
        state_schema: schema(),
        entity: None,
        mode: StateMode::Command,
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn bounded_engine_failure_keeps_original_blob_and_recovers_the_durable_outcome() {
    let fixture = Fixture::with_state_limit(Some(2 * 1024 * 1024));
    let claim = fixture.claim("blob-engine-failure");
    let view = fixture.state.snapshot().unwrap();
    let mut session =
        StateSession::open(&view, state_scope_a(), SessionLimits::default(), |_, _| {
            Ok(())
        })
        .unwrap();
    let bytes = vec![0x5a; 64 * 1024];
    for index in 0..32 {
        session
            .put(
                &view,
                format!("pressure/{index:02}").into_bytes(),
                value(&bytes),
                |_, _| Ok(()),
            )
            .unwrap();
    }
    let state = session.seal(&view, |_, _| Ok(())).unwrap();
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"body"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    let pin = fixture.capture().await;
    let physical = pin.identity().clone();
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
        envelope.publish_with_payloads(&fixture.state, |_, _| Ok(())),
        PreparedDisposition::RecoveryRequired { .. }
    ));
    assert!(fixture
        .provider
        .store()
        .release_durable_reference(
            &TenantId("a".into()),
            &fixture.blob,
            &fixture.state,
            &|| Ok(())
        )
        .is_err());
    assert_eq!(
        fixture
            .provider
            .store()
            .reclaim(1, &|| Ok(()))
            .unwrap()
            .objects,
        0
    );
    let key = fixture.input("blob-engine-failure").key;
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
    let (command, result) = inspect(&view, &key, time(201), |_, _| Ok(())).unwrap();
    let count = latent_state::payload_references::physical_owner_count(&view, &physical).unwrap();
    match command.outcome() {
        Outcome::Pending => {
            assert!(result.is_none());
            assert_eq!(count, None);
        }
        Outcome::Committed => {
            assert!(result.is_some());
            assert_eq!(count, Some(1));
        }
        _ => panic!("unexpected recovered disposition"),
    }
    drop(view);
    let owner = latent_blobs::local::LocalBlobStore::open_durable(
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
    let reader = owner
        .open_read(&TenantId("a".into()), &blob, &|| Ok(()))
        .unwrap();
    let mut readback = [0; 4];
    reader
        .read(
            &latent_blobs::BlobRange {
                offset: 0,
                length: 4,
            },
            &mut readback,
            &|| Ok(()),
        )
        .unwrap();
    assert_eq!(&readback, b"body");
}
fn state_mutation(
    view: &latent_state::embedded::ReadView,
    bytes: Option<&[u8]>,
) -> latent_state::session::StatePlan {
    let mut session =
        StateSession::open(view, state_scope_a(), SessionLimits::default(), |_, _| {
            Ok(())
        })
        .unwrap();
    if let Some(bytes) = bytes {
        session
            .put(view, b"attached".to_vec(), value(bytes), |_, _| Ok(()))
            .unwrap();
    } else {
        session
            .delete(view, b"attached".to_vec(), |_, _| Ok(()))
            .unwrap();
    }
    session.seal(view, |_, _| Ok(())).unwrap()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_state_replacement_retires_only_its_old_payload_after_commit() {
    let fixture = Fixture::new();
    let cell_key =
        latent_state::session::state_payload_cell_key(&state_scope_a(), b"attached").unwrap();
    let claim = fixture.claim("ordinary-detach-seed");
    let view = fixture.state.snapshot().unwrap();
    let state = state_mutation(&view, Some(b"body"));
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    let pin = fixture.capture().await;
    let physical = pin.identity().clone();
    let envelope = envelope
        .attach_verified_payloads(
            &view,
            &fixture.session,
            vec![PayloadAttachment {
                target: PayloadAttachmentTarget::State(b"attached".to_vec()),
                payload: pin,
            }],
        )
        .unwrap();
    drop(view);
    publish_payload_envelope(&fixture, envelope);
    let reader = fixture
        .provider
        .store()
        .open_read(&TenantId("a".into()), &fixture.blob, &|| Ok(()))
        .unwrap();

    let claim = fixture.claim("ordinary-detach-rebind");
    let view = fixture.state.snapshot().unwrap();
    let state = state_mutation(&view, Some(b"body"));
    let envelope = CompleteEnvelope::success_captured(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap()
    .reconcile_replaced_state_payloads(&view)
    .unwrap();
    let pin = fixture.capture().await;
    assert!(matches!(
        envelope.attach_verified_payloads(
            &view,
            &fixture.session,
            vec![PayloadAttachment {
                target: PayloadAttachmentTarget::State(b"attached".to_vec()),
                payload: pin,
            }],
        ),
        Err(AtomicError::Invalid)
    ));
    drop(view);

    let claim = fixture.claim_unbound("ordinary-detach-foreign");
    let view = fixture.state.snapshot().unwrap();
    let state = state_mutation(&view, Some(b"new"));
    let envelope = CompleteEnvelope::success_captured(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    drop(view);
    let foreign = open(&fixture._root.path().join("foreign-ordinary-detach.redb"));
    let foreign_view = foreign.snapshot().unwrap();
    assert!(matches!(
        envelope.reconcile_replaced_state_payloads(&foreign_view),
        Err(AtomicError::PermissionDenied)
    ));
    drop(foreign_view);

    let claim = fixture.claim_unbound("ordinary-detach-replace");
    let view = fixture.state.snapshot().unwrap();
    let state = state_mutation(&view, Some(b"new"));
    let envelope = CompleteEnvelope::success_captured(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    drop(view);
    let claim = match envelope.publish(&fixture.state, |_| panic!("unreconciled owner accepted")) {
        PreparedDisposition::KnownNotCommitted {
            command,
            reason: AtomicError::UnsupportedFormat,
        } => *command,
        _ => panic!("expected unreconciled state reference refusal"),
    };
    let view = fixture.state.snapshot().unwrap();
    let state = state_mutation(&view, Some(b"new"));
    let envelope = CompleteEnvelope::success_captured(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap()
    .reconcile_replaced_state_payloads(&view)
    .unwrap();
    drop(view);
    let claim = match envelope.publish(&foreign, |_| panic!("foreign store reached acceptance")) {
        PreparedDisposition::KnownNotCommitted {
            command,
            reason: AtomicError::PermissionDenied,
        } => *command,
        _ => panic!("expected original engine binding refusal"),
    };
    let view = fixture.state.snapshot().unwrap();
    let state = state_mutation(&view, Some(b"new"));
    let envelope = CompleteEnvelope::success_captured(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap()
    .reconcile_replaced_state_payloads(&view)
    .unwrap();
    drop(view);
    // A concurrent accepted command advances the namespace and usage fences.
    // The stale replacement must not retire the old payload owner.
    drop(fixture.claim_unbound("ordinary-detach-competing"));
    let claim = match envelope.publish(&fixture.state, |_| Ok(())) {
        PreparedDisposition::KnownNotCommitted {
            command,
            reason: AtomicError::Conflict,
        } => *command,
        _ => panic!("expected stale replacement conflict"),
    };
    let view = fixture.state.snapshot().unwrap();
    assert!(
        latent_state::session::retained_state_payload_reference(&view, &cell_key)
            .unwrap()
            .is_some()
    );
    let state = state_mutation(&view, Some(b"new"));
    let envelope = CompleteEnvelope::success_captured(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap()
    .reconcile_replaced_state_payloads(&view)
    .unwrap();
    drop(view);
    let claim = match envelope.publish(&fixture.state, |_| Err(AtomicError::PermissionDenied)) {
        PreparedDisposition::KnownNotCommitted {
            command,
            reason: AtomicError::PermissionDenied,
        } => *command,
        _ => panic!("expected state authority refusal"),
    };
    let view = fixture.state.snapshot().unwrap();
    assert!(
        latent_state::session::retained_state_payload_reference(&view, &cell_key)
            .unwrap()
            .is_some()
    );
    assert_eq!(validate_payload_census(&view).payload_bytes, 4);
    let state = state_mutation(&view, Some(b"new"));
    let envelope = CompleteEnvelope::success_captured(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap()
    .reconcile_replaced_state_payloads(&view)
    .unwrap();
    drop(view);
    assert!(matches!(
        envelope.publish(&fixture.state, |_| Ok(())),
        PreparedDisposition::Confirmed { .. }
    ));
    let view = fixture.state.snapshot().unwrap();
    assert!(
        latent_state::session::retained_state_payload_reference(&view, &cell_key)
            .unwrap()
            .is_none()
    );
    assert_eq!(validate_payload_census(&view).payload_bytes, 0);
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        Some(0)
    );
    drop(view);
    assert!(fixture
        .provider
        .store()
        .release_durable_reference(
            &TenantId("a".into()),
            &fixture.blob,
            &fixture.state,
            &|| Ok(()),
        )
        .unwrap());
    assert_eq!(
        fixture
            .provider
            .store()
            .reclaim(1, &|| Ok(()))
            .unwrap()
            .objects,
        0
    );
    let mut bytes = [0; 4];
    reader
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
    drop(reader);
    assert_eq!(
        fixture
            .provider
            .store()
            .reclaim(1, &|| Ok(()))
            .unwrap()
            .objects,
        1
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn state_attachment_replacement_and_delete_share_one_physical_owner_fence() {
    let fixture = Fixture::new();
    let cell_key =
        latent_state::session::state_payload_cell_key(&state_scope_a(), b"attached").unwrap();
    let claim = fixture.claim("state-attach");
    let view = fixture.state.snapshot().unwrap();
    let state = state_mutation(&view, Some(b"body"));
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    let pin = fixture.capture().await;
    let physical = pin.identity().clone();
    let envelope = envelope
        .attach_verified_payloads(
            &view,
            &fixture.session,
            vec![PayloadAttachment {
                target: PayloadAttachmentTarget::State(b"attached".to_vec()),
                payload: pin,
            }],
        )
        .unwrap();
    drop(view);
    publish_payload_envelope(&fixture, envelope);
    let view = fixture.state.snapshot().unwrap();
    let first = latent_state::session::retained_state_payload_reference(&view, &cell_key)
        .unwrap()
        .unwrap();
    assert_eq!(validate_payload_census(&view).payload_bytes, 4);
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        Some(1)
    );
    drop(view);
    let reader = fixture
        .provider
        .store()
        .open_read(&TenantId("a".into()), &fixture.blob, &|| Ok(()))
        .unwrap();

    let claim = fixture.claim("state-replace");
    let view = fixture.state.snapshot().unwrap();
    let state = state_mutation(&view, Some(b"body"));
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
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
                target: PayloadAttachmentTarget::State(b"attached".to_vec()),
                payload: pin,
            }],
        )
        .unwrap();
    drop(view);
    let claim = match envelope
        .publish_with_payloads(&fixture.state, |_, _| Err(AtomicError::PermissionDenied))
    {
        PreparedDisposition::KnownNotCommitted {
            command,
            reason: AtomicError::PermissionDenied,
        } => *command,
        _ => panic!("expected final-fence refusal"),
    };
    let view = fixture.state.snapshot().unwrap();
    assert_eq!(
        latent_state::session::retained_state_payload_reference(&view, &cell_key)
            .unwrap()
            .unwrap(),
        first
    );
    assert_eq!(validate_payload_census(&view).payload_bytes, 4);
    let state = state_mutation(&view, Some(b"body"));
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
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
                target: PayloadAttachmentTarget::State(b"attached".to_vec()),
                payload: pin,
            }],
        )
        .unwrap();
    drop(view);
    publish_payload_envelope(&fixture, envelope);
    let view = fixture.state.snapshot().unwrap();
    let second = latent_state::session::retained_state_payload_reference(&view, &cell_key)
        .unwrap()
        .unwrap();
    assert_eq!(validate_payload_census(&view).payload_bytes, 4);
    assert_ne!(
        first.reference.owner.generation,
        second.reference.owner.generation
    );
    assert!(view
        .get(&first.reference.owner_key().unwrap())
        .unwrap()
        .is_none());
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        Some(1)
    );
    drop(view);

    let claim = fixture.claim("state-delete");
    let view = fixture.state.snapshot().unwrap();
    let state = state_mutation(&view, None);
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    let envelope = envelope
        .attach_verified_payloads(&view, &fixture.session, vec![])
        .unwrap();
    drop(view);
    let foreign = open(&fixture._root.path().join("foreign-state-delete.redb"));
    let view = foreign.snapshot().unwrap();
    let identity =
        latent_state::store_identity::StoreIdentity::new("payload-envelope-a".into()).unwrap();
    let initialization = identity.prepare_initialization(&view).unwrap().unwrap();
    drop(view);
    foreign.apply(initialization).unwrap();
    let claim = match envelope
        .publish_with_payloads(&foreign, |_, _| panic!("foreign delete reached acceptance"))
    {
        PreparedDisposition::KnownNotCommitted {
            command,
            reason: AtomicError::PermissionDenied,
        } => *command,
        _ => panic!("expected foreign engine refusal"),
    };
    let view = fixture.state.snapshot().unwrap();
    let state = state_mutation(&view, None);
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    let envelope = envelope
        .attach_verified_payloads(&view, &fixture.session, vec![])
        .unwrap();
    drop(view);
    publish_payload_envelope(&fixture, envelope);
    let view = fixture.state.snapshot().unwrap();
    assert!(
        latent_state::session::retained_state_payload_reference(&view, &cell_key)
            .unwrap()
            .is_none()
    );
    assert_eq!(validate_payload_census(&view).payload_bytes, 0);
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        Some(0)
    );
    drop(view);
    assert!(fixture
        .provider
        .store()
        .release_durable_reference(
            &TenantId("a".into()),
            &fixture.blob,
            &fixture.state,
            &|| Ok(())
        )
        .unwrap());
    assert_eq!(
        fixture
            .provider
            .store()
            .reclaim(1, &|| Ok(()))
            .unwrap()
            .objects,
        0
    );
    let mut bytes = [0; 4];
    reader
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
    drop(reader);
    assert_eq!(
        fixture
            .provider
            .store()
            .reclaim(1, &|| Ok(()))
            .unwrap()
            .objects,
        1
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn state_replacement_with_new_blob_preserves_an_already_open_old_reader() {
    let fixture = Fixture::new();
    let mut writer = fixture
        .provider
        .store()
        .create(
            &TenantId("a".into()),
            "application/octet-stream",
            Some(4),
            &|| Ok(()),
        )
        .unwrap();
    writer.write(0, b"new!", &|| Ok(())).unwrap();
    let replacement = writer.seal(&|| Ok(())).unwrap();
    let claim = fixture.claim("state-old-blob");
    let view = fixture.state.snapshot().unwrap();
    let state = state_mutation(&view, Some(b"body"));
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    let old = fixture.capture().await;
    let old_identity = old.identity().clone();
    let envelope = envelope
        .attach_verified_payloads(
            &view,
            &fixture.session,
            vec![PayloadAttachment {
                target: PayloadAttachmentTarget::State(b"attached".to_vec()),
                payload: old,
            }],
        )
        .unwrap();
    drop(view);
    publish_payload_envelope(&fixture, envelope);
    let reader = fixture
        .provider
        .store()
        .open_read(&TenantId("a".into()), &fixture.blob, &|| Ok(()))
        .unwrap();

    let claim = fixture.claim("state-new-blob");
    let view = fixture.state.snapshot().unwrap();
    let state = state_mutation(&view, Some(b"new!"));
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    let pin = fixture.capture_blob(&replacement).await;
    let new_identity = pin.identity().clone();
    let envelope = envelope
        .attach_verified_payloads(
            &view,
            &fixture.session,
            vec![PayloadAttachment {
                target: PayloadAttachmentTarget::State(b"attached".to_vec()),
                payload: pin,
            }],
        )
        .unwrap();
    drop(view);
    publish_payload_envelope(&fixture, envelope);
    let view = fixture.state.snapshot().unwrap();
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &old_identity).unwrap(),
        Some(0)
    );
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &new_identity).unwrap(),
        Some(1)
    );
    assert_eq!(validate_payload_census(&view).payload_bytes, 4);
    drop(view);
    assert!(fixture
        .provider
        .store()
        .release_durable_reference(
            &TenantId("a".into()),
            &fixture.blob,
            &fixture.state,
            &|| Ok(())
        )
        .unwrap());
    assert_eq!(
        fixture
            .provider
            .store()
            .reclaim(1, &|| Ok(()))
            .unwrap()
            .objects,
        0
    );
    let mut old_bytes = [0; 4];
    reader
        .read(
            &latent_blobs::BlobRange {
                offset: 0,
                length: 4,
            },
            &mut old_bytes,
            &|| Ok(()),
        )
        .unwrap();
    assert_eq!(&old_bytes, b"body");
    drop(reader);
    assert_eq!(
        fixture
            .provider
            .store()
            .reclaim(1, &|| Ok(()))
            .unwrap()
            .objects,
        1
    );
    let new_reader = fixture
        .provider
        .store()
        .open_read(&TenantId("a".into()), &replacement, &|| Ok(()))
        .unwrap();
    let mut new_bytes = [0; 4];
    new_reader
        .read(
            &latent_blobs::BlobRange {
                offset: 0,
                length: 4,
            },
            &mut new_bytes,
            &|| Ok(()),
        )
        .unwrap();
    assert_eq!(&new_bytes, b"new!");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn deleting_state_keeps_the_shared_unresolved_effect_payload() {
    let fixture = Fixture::new();
    let claim = fixture.claim("state-and-effect");
    let view = fixture.state.snapshot().unwrap();
    let state = state_mutation(&view, Some(b"body"));
    let intent = StagedIntent {
        binding: "approved-event".into(),
        operation: "event".into(),
        payload: value(b"body"),
        expires_at_millis: None,
    };
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        Some(state),
        vec![intent],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    let state_pin = fixture.capture().await;
    let physical = state_pin.identity().clone();
    let effect_pin = fixture.capture().await;
    let envelope = envelope
        .attach_verified_payloads(
            &view,
            &fixture.session,
            vec![
                PayloadAttachment {
                    target: PayloadAttachmentTarget::State(b"attached".to_vec()),
                    payload: state_pin,
                },
                PayloadAttachment {
                    target: PayloadAttachmentTarget::Effect(0),
                    payload: effect_pin,
                },
            ],
        )
        .unwrap();
    drop(view);
    publish_payload_envelope(&fixture, envelope);
    let view = fixture.state.snapshot().unwrap();
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        Some(2)
    );
    validate_payload_census(&view);
    drop(view);
    let claim = fixture.claim("delete-shared-state");
    let view = fixture.state.snapshot().unwrap();
    let state = state_mutation(&view, None);
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        Some(state),
        vec![],
        value(b"ok"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    let envelope = envelope
        .attach_verified_payloads(&view, &fixture.session, vec![])
        .unwrap();
    drop(view);
    publish_payload_envelope(&fixture, envelope);
    let view = fixture.state.snapshot().unwrap();
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        Some(1)
    );
    let page =
        latent_state::payload_references::required_physical_page(&view, &physical, None, 2, 2048)
            .unwrap();
    assert_eq!(page.references.len(), 1);
    assert_eq!(
        page.references[0].owner.kind,
        latent_state::payload_references::PayloadOwnerKind::Effect
    );
    validate_payload_census(&view);
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
async fn rejected_result_retains_real_blob_until_response_expiry() {
    let fixture = Fixture::new();
    let claim = fixture.claim("rejected-blob");
    let view = fixture.state.snapshot().unwrap();
    let envelope =
        CompleteEnvelope::rejection(&view, claim, "declined".into(), value(b"body"), time(200))
            .unwrap();
    let pin = fixture.capture().await;
    let physical = pin.identity().clone();
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
    let command = publish_payload_envelope(&fixture, envelope);
    assert_eq!(command.outcome(), Outcome::Rejected);
    let view = fixture.state.snapshot().unwrap();
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        Some(1)
    );
    validate_payload_census(&view);
    drop(view);
    // Keep the real physical reader paused across the clock-driven expiry.
    let reader = fixture
        .provider
        .store()
        .open_read(&TenantId("a".into()), &fixture.blob, &|| Ok(()))
        .unwrap();
    let owner = ResultMaintenanceOwner::default();
    let clock = |now| MaintenanceClock {
        time: time(now),
        boot: [7; 32],
        monotonic_millis: now,
    };
    owner
        .anchor(&fixture.state, None, clock(200), |_| Ok(()))
        .unwrap();
    owner.step(&fixture.state, clock(1100), |_| Ok(())).unwrap();
    let view = fixture.state.snapshot().unwrap();
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        Some(0)
    );
    assert_eq!(validate_payload_census(&view).payload_bytes, 0);
    drop(view);
    assert!(fixture
        .provider
        .store()
        .release_durable_reference(
            &TenantId("a".into()),
            &fixture.blob,
            &fixture.state,
            &|| Ok(())
        )
        .unwrap());
    assert_eq!(
        fixture
            .provider
            .store()
            .reclaim(1, &|| Ok(()))
            .unwrap()
            .objects,
        0
    );
    let mut bytes = [0; 4];
    reader
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
    drop(reader);
    assert_eq!(
        fixture
            .provider
            .store()
            .reclaim(1, &|| Ok(()))
            .unwrap()
            .objects,
        1
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn response_expiry_keeps_real_shared_effect_blobs_until_reviewed_purge() {
    use latent_effects::{
        authority::EffectTime,
        dispatch::{AttemptReceipt, Disposition},
        dispatch_store::DispatchCatalog,
    };
    let fixture = Fixture::new();
    let claim = fixture.claim("response-effect-blob");
    let key = fixture.input("response-effect-blob").key;
    let view = fixture.state.snapshot().unwrap();
    let intent = || StagedIntent {
        binding: "approved-event".into(),
        operation: "event".into(),
        payload: value(b"body"),
        expires_at_millis: None,
    };
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        None,
        vec![intent(), intent()],
        value(b"body"),
        &fixture.effects,
        time(200),
    )
    .unwrap();
    let result_pin = fixture.capture().await;
    let physical = result_pin.identity().clone();
    let effect_pin = fixture.capture().await;
    let second_effect_pin = fixture.capture().await;
    let envelope = envelope
        .attach_verified_payloads(
            &view,
            &fixture.session,
            vec![
                PayloadAttachment {
                    target: PayloadAttachmentTarget::Result,
                    payload: result_pin,
                },
                PayloadAttachment {
                    target: PayloadAttachmentTarget::Effect(0),
                    payload: effect_pin,
                },
                PayloadAttachment {
                    target: PayloadAttachmentTarget::Effect(1),
                    payload: second_effect_pin,
                },
            ],
        )
        .unwrap();
    drop(view);
    publish_payload_envelope(&fixture, envelope);
    // The original physical reader remains live while the response expires
    // and both independent effects go through reviewed terminal handling.
    let reader = fixture
        .provider
        .store()
        .open_read(&TenantId("a".into()), &fixture.blob, &|| Ok(()))
        .unwrap();
    let effect_clock = |now| EffectTime {
        unix_millis: now,
        continuity_proven: true,
    };
    let epoch =
        DispatchCatalog::begin_exclusive_epoch(&fixture.state, effect_clock(202), None).unwrap();
    let view = fixture.state.snapshot().unwrap();
    let due = DispatchCatalog::due_page(&view, 202, None, 1, 4096).unwrap();
    let uncertain_effect = due.rows[0].effect.clone();
    drop(view);
    let claim =
        DispatchCatalog::claim(&fixture.state, epoch, &due.rows[0], effect_clock(202)).unwrap();
    DispatchCatalog::begin_send(&fixture.state, epoch, &claim.attempt, effect_clock(203)).unwrap();
    assert_eq!(
        DispatchCatalog::complete(
            &fixture.state,
            epoch,
            &claim.attempt,
            AttemptReceipt {
                disposition: Disposition::Uncertain,
                reason: "lost-response-after-send".into(),
                provider_receipt: None,
                observed_at_millis: 204,
            },
            None,
            effect_clock(204),
        )
        .unwrap(),
        Disposition::Uncertain
    );
    let view = fixture.state.snapshot().unwrap();
    let due = DispatchCatalog::due_page(&view, 205, None, 1, 4096).unwrap();
    let failed_effect = due.rows[0].effect.clone();
    assert_ne!(failed_effect, uncertain_effect);
    drop(view);
    let claim =
        DispatchCatalog::claim(&fixture.state, epoch, &due.rows[0], effect_clock(205)).unwrap();
    assert_eq!(
        DispatchCatalog::complete(
            &fixture.state,
            epoch,
            &claim.attempt,
            AttemptReceipt {
                disposition: Disposition::KnownFailed,
                reason: "known-failure-before-send".into(),
                provider_receipt: None,
                observed_at_millis: 206,
            },
            None,
            effect_clock(206),
        )
        .unwrap(),
        Disposition::KnownFailed
    );
    let owner = ResultMaintenanceOwner::default();
    let clock = |now| MaintenanceClock {
        time: time(now),
        boot: [7; 32],
        monotonic_millis: now,
    };
    owner
        .anchor(&fixture.state, None, clock(200), |_| Ok(()))
        .unwrap();
    owner.step(&fixture.state, clock(1100), |_| Ok(())).unwrap();
    let view = fixture.state.snapshot().unwrap();
    let (record, result) = inspect(&view, &key, time(1100), |_, _| Ok(())).unwrap();
    assert!(result.is_none());
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        Some(2)
    );
    assert_eq!(
        DispatchCatalog::history_page(&view, &uncertain_effect, None, 128, 4096)
            .unwrap()
            .rows[0]
            .receipt
            .disposition,
        Disposition::Uncertain
    );
    assert_eq!(
        DispatchCatalog::history_page(&view, &failed_effect, None, 128, 4096)
            .unwrap()
            .rows[0]
            .receipt
            .disposition,
        Disposition::KnownFailed
    );
    validate_payload_census(&view);
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
    let request = RetentionRequest {
        key,
        expected_command_digest: RetentionRequest::command_digest(&record).unwrap(),
        actor: "operator".into(),
        operation_id: "review".into(),
        policy: "retention".into(),
        retain_until_millis: 5300,
        inbox_expires_at_millis: None,
    };
    let first_review = owner
        .terminalize(&fixture.state, &request, clock(5200), |_, _, _| Ok(()))
        .unwrap();
    assert!(!first_review.complete);
    assert!(
        owner
            .terminalize(&fixture.state, &request, clock(5200), |_, _, _| Ok(()))
            .unwrap()
            .complete
    );
    let view = fixture.state.snapshot().unwrap();
    assert_eq!(
        DispatchCatalog::history_page(&view, &uncertain_effect, None, 128, 4096)
            .unwrap()
            .rows[0]
            .receipt
            .disposition,
        Disposition::Uncertain
    );
    assert_eq!(
        DispatchCatalog::history_page(&view, &failed_effect, None, 128, 4096)
            .unwrap()
            .rows[0]
            .receipt
            .disposition,
        Disposition::KnownFailed
    );
    drop(view);
    owner
        .purge(&fixture.state, &request, clock(5300), |_, _, _| Ok(()))
        .unwrap();
    let view = fixture.state.snapshot().unwrap();
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        Some(1)
    );
    validate_payload_census(&view);
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
    owner
        .purge(&fixture.state, &request, clock(5300), |_, _, _| Ok(()))
        .unwrap();
    let view = fixture.state.snapshot().unwrap();
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        Some(0)
    );
    validate_payload_census(&view);
    drop(view);
    assert!(fixture
        .provider
        .store()
        .release_durable_reference(
            &TenantId("a".into()),
            &fixture.blob,
            &fixture.state,
            &|| Ok(())
        )
        .unwrap());
    assert_eq!(
        fixture
            .provider
            .store()
            .reclaim(1, &|| Ok(()))
            .unwrap()
            .objects,
        0
    );
    let mut bytes = [0; 4];
    reader
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
    drop(reader);
    assert_eq!(
        fixture
            .provider
            .store()
            .reclaim(1, &|| Ok(()))
            .unwrap()
            .objects,
        1
    );
}

fn protected_recovery(
    root: &std::path::Path,
) -> latent_state::protected_store::ProtectedStoreStartup {
    use latent_state::{
        embedded::StoreError,
        protected_store::{ProtectedStoreConfig, ProtectedStoreOwner},
    };
    let mut config = ProtectedStoreConfig::bounded_linux(root.to_path_buf());
    config.file_name = "state.redb".into();
    let blobs = root.join("blobs");
    ProtectedStoreOwner::start_validated_view(config, 4096, move |view| {
        validate_view(view, |view, key, bytes| {
            if *key == latent_state::store_identity::StoreIdentity::row_key() {
                latent_state::store_identity::StoreIdentity::validate_row(key, bytes)
            } else {
                accounted::installed_codec(view, key, bytes)
            }
        })?;
        latent_effects::dispatch_store::DispatchCatalog::validate_view(view)?;
        let owner = latent_blobs::local::LocalBlobStore::open_durable_for_view(
            &blobs,
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
            view,
        )
        .map_err(|_| StoreError::Corrupt)?;
        let mut inventory = latent_blobs::local::RequiredBlobInventory::begin(&owner, view)
            .map_err(|_| StoreError::Corrupt)?;
        loop {
            let (_, done) = inventory
                .next_page(&owner, view, 1, 1024, &|| Ok(()))
                .map_err(|_| StoreError::Corrupt)?;
            if done {
                return Ok(());
            }
        }
    })
    .unwrap()
}

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
    drop(inventory);
    drop(store);
    drop(state);
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    std::fs::set_permissions(
        root.path().join("state.redb"),
        std::fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    let protected = protected_recovery(root.path()).await.unwrap();
    protected.close();
    let drained = protected
        .drain_async(
            std::time::Instant::now() + std::time::Duration::from_secs(10),
            std::future::pending(),
        )
        .unwrap()
        .await;
    assert!(drained.snapshot.physically_retired());
    drop(protected);
    let object = std::fs::read_dir(root.path().join("blobs/objects"))
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    std::fs::write(object.join("data"), b"evil").unwrap();
    assert!(matches!(
        protected_recovery(root.path()).await,
        Err(latent_state::protected_store::ProtectedStoreError::Store(
            latent_state::embedded::StoreError::Corrupt
        ))
    ));
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
    let mut claim = fixture.claim("foreign-payload-session");
    assert_eq!(
        claim.bind_payload_session(&foreign),
        Err(AtomicError::Conflict)
    );
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
async fn closed_bound_session_cannot_cross_final_payload_acceptance() {
    let fixture = Fixture::new();
    let claim = fixture.claim("closed-payload-session");
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
    fixture.session.close();
    assert!(matches!(
        envelope.publish_with_payloads(&fixture.state, |_, _| panic!(
            "closed session reached host acceptance"
        )),
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
