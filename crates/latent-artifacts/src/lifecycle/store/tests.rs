use super::*;

fn identity(label: &[u8]) -> LifecycleIdentity {
    LifecycleIdentity {
        scope: LifecycleScope::LocalUnscoped,
        release: crate::content_digest(label),
        package: None,
        completion: digest(label),
    }
}
fn publication(identity: &LifecycleIdentity, id: &str) -> ReleaseOperationReceipt {
    let actor = ReleaseActor {
        subject: "test-host".to_owned(),
        kind: ReleaseActorKind::Host,
    };
    let record = ReleaseLifecycleRecord {
        scope: identity.scope.clone(),
        release: identity.release.clone(),
        package: None,
        state: ReleaseLifecycleState::Admitted,
        generation: 1,
        actor: actor.clone(),
        reason: ReleaseLifecycleReason::Admitted,
        operation_id: id.to_owned(),
        policy: None,
        observed_at_unix_millis: None,
        evidence_revision_digest: None,
    };
    ReleaseOperationReceipt {
        operation_id: id.to_owned(),
        request_digest: blob(id.as_bytes()),
        scope: identity.scope.clone(),
        actor,
        action: ReleaseLifecycleAction::Publish,
        disposition: ReleaseOperationDisposition::Committed,
        reason: ReleaseLifecycleReason::Admitted,
        component_digest: Some(identity.release.clone()),
        package_manifest_digest: None,
        expected_generation: Some(0),
        record: Some(record),
        policy: None,
        observed_at_unix_millis: None,
    }
}
fn revocation(record: &ReleaseLifecycleRecord, id: &str) -> ReleaseOperationReceipt {
    let mut next = record.clone();
    next.state = ReleaseLifecycleState::Revoked;
    next.generation += 1;
    next.reason = ReleaseLifecycleReason::OperatorRevocation;
    next.operation_id = id.to_owned();
    ReleaseOperationReceipt {
        operation_id: id.to_owned(),
        request_digest: blob(id.as_bytes()),
        scope: record.scope.clone(),
        actor: record.actor.clone(),
        action: ReleaseLifecycleAction::Revoke,
        disposition: ReleaseOperationDisposition::Committed,
        reason: next.reason,
        component_digest: Some(record.release.clone()),
        package_manifest_digest: None,
        expected_generation: Some(record.generation),
        record: Some(next),
        policy: None,
        observed_at_unix_millis: None,
    }
}
#[test]
fn compact_capability_revokes_generation_and_owner_without_store_maps() {
    let id = identity(b"one");
    let record = publication(&id, "create").record.unwrap();
    let owner = Owner::new(None);
    let row = Row::new(&record);
    let token = ReleaseUseEligibility::new(
        LifecycleEligibility {
            owner: Arc::clone(&owner),
            row: Arc::clone(&row),
            generation: 1,
        },
        None,
    )
    .unwrap();
    let handle = LifecycleAuthorityHandle {
        owner: Arc::clone(&owner),
    };
    token.check_for_catalog(&handle).unwrap();
    token
        .authorize_tenant(&latent_core::TenantId("tenant".to_owned()))
        .unwrap();
    let other = LifecycleAuthorityHandle {
        owner: Owner::new(None),
    };
    assert!(!token.belongs_to_catalog(&other));
    let guard = owner.acquire().unwrap();
    let mut entered = false;
    let failure = token
        .with_current(&mut |_| {
            entered = true;
            Ok(())
        })
        .unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::Unavailable);
    assert_eq!(failure.message, "release-lifecycle-busy");
    assert!(failure.retryable);
    assert!(
        !entered,
        "a contended final start must return without entering"
    );
    drop(guard);
    token
        .with_current(&mut |checker| {
            checker.check()?;
            entered = true;
            Ok(())
        })
        .unwrap();
    assert!(entered);
    let revoked = revocation(&record, "revoke").record.unwrap();
    row.adopt(&revoked);
    assert!(token.check_current().is_err());
    assert!(token.belongs_to_catalog(&handle));
    owner.retire();
    let failure = token.check_current().unwrap_err();
    assert_eq!(failure.message, "release-lifecycle-unavailable");
    assert!(!failure.retryable);
}
#[test]
fn poisoned_fence_and_unhealthy_owner_are_never_reported_as_retryable_contention() {
    let owner = Owner::new(None);
    let poisoned = Arc::clone(&owner);
    assert!(std::thread::spawn(move || {
        let _guard = poisoned.acquire().unwrap();
        panic!("inject poisoned lifecycle fence");
    })
    .join()
    .is_err());
    let failure = owner.acquire().unwrap_err();
    assert_eq!(failure.message, "release-lifecycle-unavailable");
    assert!(!failure.retryable);

    let owner = Owner::new(None);
    owner.poison();
    let failure = owner.acquire().unwrap_err();
    assert_eq!(failure.message, "release-lifecycle-unavailable");
    assert!(!failure.retryable);
}
#[test]
fn no_local_mode_composite_accepts_a_package_identity() {
    let mut identity = identity(b"one");
    identity.package = Some(
        "sha256:0000000000000000000000000000000000000000000000000000000000000000"
            .parse()
            .unwrap(),
    );
    assert!(validation::identity(&identity, false).is_err());
}

#[cfg(unix)]
mod durable {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};
    static NEXT: AtomicU64 = AtomicU64::new(0);
    struct Root(PathBuf);
    impl Root {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!(
                "lsf-lifecycle-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            std::fs::create_dir(&root).unwrap();
            Self(root)
        }
        fn path(&self) -> PathBuf {
            self.0.join("lifecycle")
        }
    }
    impl Drop for Root {
        fn drop(&mut self) {
            assert!(self.0.starts_with(std::env::temp_dir()));
            std::fs::remove_dir_all(&self.0).unwrap();
        }
    }
    fn open(
        root: &Root,
        baseline: &[LifecycleIdentity],
        limits: LifecycleLimits,
    ) -> LifecycleStore {
        LifecycleStore::open(&root.path(), limits, None, baseline).unwrap()
    }
    fn commit(
        store: &LifecycleStore,
        receipt: ReleaseOperationReceipt,
        identity: Option<LifecycleIdentity>,
    ) -> Result<(), PlatformError> {
        let prepared = store.prepare(receipt, identity)?;
        store.with_prepared(&prepared, &mut |fence| {
            fence.commit(&prepared)?;
            Ok(())
        })
    }
    #[test]
    fn state_lock_contention_and_poisoning_have_distinct_read_errors() {
        let root = Root::new();
        let id = identity(b"read-state");
        let store = open(&root, std::slice::from_ref(&id), LifecycleLimits::default());
        let guard = store.state.lock().unwrap();
        for failure in [
            store.record(&id.release).unwrap_err(),
            store.identity(&id.release).unwrap_err(),
        ] {
            assert_eq!(failure.message, "release-lifecycle-busy");
            assert!(failure.retryable);
        }
        drop(guard);
        assert!(store.record(&id.release).unwrap().is_some());
        std::thread::scope(|scope| {
            assert!(scope
                .spawn(|| {
                    let _guard = store.state.lock().unwrap();
                    panic!("inject poisoned lifecycle state");
                })
                .join()
                .is_err());
        });
        let failure = store.record(&id.release).unwrap_err();
        assert_eq!(failure.message, "release-lifecycle-unavailable");
        assert!(!failure.retryable);
    }
    #[test]
    fn bootstrap_is_explicit_and_later_orphan_complete_never_admits() {
        let root = Root::new();
        let first = identity(b"old");
        let orphan = identity(b"orphan");
        let store = open(
            &root,
            std::slice::from_ref(&first),
            LifecycleLimits::default(),
        );
        let token = store.eligibility(&first.release, None).unwrap();
        drop(store);
        assert!(token.check_current().is_err());
        let reopened = open(
            &root,
            &[first.clone(), orphan.clone()],
            LifecycleLimits::default(),
        );
        assert!(reopened.record(&orphan.release).unwrap().is_none());
        assert!(reopened.eligibility(&orphan.release, None).is_err());
        assert!(reopened.eligibility(&first.release, None).is_ok());
    }
    #[test]
    fn each_roll_forward_boundary_recovers_exact_committed_row_and_receipt() {
        for point in 1..=4 {
            let root = Root::new();
            let identity = identity(b"new");
            let store = open(&root, &[], LifecycleLimits::default());
            persistence::FAIL.with(|value| value.set(point));
            assert!(commit(
                &store,
                publication(&identity, "create"),
                Some(identity.clone())
            )
            .is_err());
            assert!(matches!(
                store.operation(&identity.scope, "create").unwrap(),
                ReleaseOperationLookup::Uncertain
            ));
            drop(store);
            let reopened = open(
                &root,
                std::slice::from_ref(&identity),
                LifecycleLimits::default(),
            );
            assert_eq!(
                reopened
                    .record(&identity.release)
                    .unwrap()
                    .unwrap()
                    .generation,
                1
            );
            assert!(matches!(
                reopened.operation(&identity.scope, "create").unwrap(),
                ReleaseOperationLookup::Found(_)
            ));
        }
    }
    #[test]
    fn missing_latest_receipt_or_wrong_complete_identity_is_corruption() {
        let root = Root::new();
        let identity = identity(b"new");
        let store = open(&root, &[], LifecycleLimits::default());
        commit(
            &store,
            publication(&identity, "create"),
            Some(identity.clone()),
        )
        .unwrap();
        drop(store);
        let mut wrong = identity.clone();
        wrong.completion = [7; 32];
        assert!(
            LifecycleStore::open(&root.path(), LifecycleLimits::default(), None, &[wrong]).is_err()
        );
        std::fs::remove_file(root.path().join("receipts/000.json")).unwrap();
        assert!(
            LifecycleStore::open(&root.path(), LifecycleLimits::default(), None, &[identity])
                .is_err()
        );
    }
    #[test]
    fn exact_retry_and_terminal_revocation_cannot_resurrect() {
        let root = Root::new();
        let identity = identity(b"new");
        let store = open(&root, &[], LifecycleLimits::default());
        let receipt = publication(&identity, "create");
        commit(&store, receipt.clone(), Some(identity.clone())).unwrap();
        let token = store.eligibility(&identity.release, None).unwrap();
        let old = store.record(&identity.release).unwrap().unwrap();
        let revoke = revocation(&old, "revoke");
        commit(&store, revoke, None).unwrap();
        assert!(token.check_current().is_err());
        let replay = store.prepare(receipt, None).unwrap();
        assert!(replay.is_replay());
        assert_eq!(
            replay.receipt().record.as_ref().unwrap().state,
            ReleaseLifecycleState::Admitted
        );
        assert!(store.eligibility(&identity.release, None).is_err());
        let mut new = publication(&identity, "different");
        new.expected_generation = None;
        new.record = Some(old);
        assert!(store.prepare(new, Some(identity)).is_err());
    }
    #[test]
    fn receipt_ring_rollover_does_not_rewrite_existing_record_files() {
        let root = Root::new();
        let limits = LifecycleLimits {
            max_recent_operations: 3,
            ..LifecycleLimits::default()
        };
        let store = open(&root, &[], limits);
        let mut identities = Vec::new();
        let mut prior_bytes = Vec::new();
        for index in 0..12 {
            let id = identity(format!("release-{index}").as_bytes());
            let receipt = publication(&id, &format!("create-{index}"));
            io::WRITES.with(|value| value.set((0, 0)));
            commit(&store, receipt, Some(id.clone())).unwrap();
            let (writes, bytes) = io::WRITES.with(Cell::get);
            assert_eq!(
                writes, 4,
                "one intent, row, receipt, HEAD irrespective of catalog size"
            );
            assert!(
                bytes <= 32 * 1024,
                "small operation writes must remain bounded"
            );
            // Deterministic complexity assertion: every mutation only adds its
            // bounded row; all earlier persisted row bytes remain exact.
            for (previous, bytes) in identities.iter().zip(&prior_bytes) {
                assert_eq!(
                    io::required(
                        &persistence::row_path(&root.path(), previous).unwrap(),
                        limits.max_record_bytes
                    )
                    .unwrap(),
                    *bytes
                );
            }
            let bytes = io::required(
                &persistence::row_path(&root.path(), &id.release).unwrap(),
                limits.max_record_bytes,
            )
            .unwrap();
            identities.push(id.release.clone());
            prior_bytes.push(bytes);
        }
        assert_eq!(
            io::files(&root.path().join("receipts"), 4).unwrap().len(),
            3
        );
        assert!(matches!(
            store
                .operation(&LifecycleScope::LocalUnscoped, "create-0")
                .unwrap(),
            ReleaseOperationLookup::Unknown
        ));
        assert!(matches!(
            store
                .operation(&LifecycleScope::LocalUnscoped, "create-11")
                .unwrap(),
            ReleaseOperationLookup::Found(_)
        ));
    }
    #[test]
    fn prepared_cas_loses_cleanly_before_persistence() {
        let root = Root::new();
        let store = open(&root, &[], LifecycleLimits::default());
        let first = identity(b"first");
        let second = identity(b"second");
        let stale = store
            .prepare(publication(&first, "first"), Some(first.clone()))
            .unwrap();
        commit(&store, publication(&second, "second"), Some(second)).unwrap();
        assert!(store
            .with_prepared(&stale, &mut |fence| {
                fence.commit(&stale)?;
                Ok(())
            })
            .is_err());
        assert!(store.record(&first.release).unwrap().is_none());
    }

    struct RejectingAuthority;
    impl AdmissionAuthority for RejectingAuthority {
        fn verify(
            &self,
            _: &latent_core::TenantId,
            _: crate::PackageAdmissionUpload,
        ) -> Result<crate::VerifiedAdmission, PlatformError> {
            Err(unavailable())
        }
        fn recover(
            &self,
            _: &crate::AdmissionBinding,
            _: crate::PackageAdmissionUpload,
        ) -> Result<crate::VerifiedAdmission, PlatformError> {
            Err(unavailable())
        }
    }
    fn signed_identity() -> LifecycleIdentity {
        let mut identity = identity(b"signed");
        identity.scope = LifecycleScope::Tenant(latent_core::TenantId("tenant".to_owned()));
        identity.package = Some(crate::content_digest(b"package").0.parse().unwrap());
        identity
    }
    fn enforced(root: &Root, identity: &LifecycleIdentity) -> LifecycleStore {
        LifecycleStore::open(
            &root.path(),
            LifecycleLimits::default(),
            Some(Arc::new(RejectingAuthority)),
            std::slice::from_ref(identity),
        )
        .unwrap()
    }
    fn evidence(identity: &LifecycleIdentity, sequence: u8) -> LifecycleEvidence {
        let binding = crate::AdmissionBinding {
            tenant: identity.scope.tenant().unwrap().clone(),
            package: identity.package.clone().unwrap(),
            release: identity.release.clone(),
            receipt: vec![sequence],
        };
        LifecycleEvidence::prepare(
            identity,
            &binding,
            ReleaseEvidenceUpload {
                signatures: vec![crate::AdmissionEvidence {
                    manifest: vec![sequence, 1],
                    configuration: vec![sequence, 2],
                    payload: vec![sequence, 3],
                }],
                provenance: Vec::new(),
                sboms: Vec::new(),
            },
            LifecycleLimits::default(),
        )
        .unwrap()
    }
    fn renewal(
        store: &LifecycleStore,
        identity: &LifecycleIdentity,
        evidence: &LifecycleEvidence,
        id: &str,
    ) -> ReleaseOperationReceipt {
        let old = store.record(&identity.release).unwrap().unwrap();
        let mut record = old.clone();
        record.generation += 1;
        record.operation_id = id.to_owned();
        record.reason = ReleaseLifecycleReason::EvidenceRenewed;
        record.evidence_revision_digest = Some(evidence.digest().clone());
        ReleaseOperationReceipt {
            operation_id: id.to_owned(),
            request_digest: blob(id.as_bytes()),
            scope: record.scope.clone(),
            actor: record.actor.clone(),
            action: ReleaseLifecycleAction::RenewEvidence,
            disposition: ReleaseOperationDisposition::Committed,
            reason: record.reason,
            component_digest: Some(record.release.clone()),
            package_manifest_digest: Some(
                record.package.as_ref().unwrap().as_str().parse().unwrap(),
            ),
            expected_generation: Some(old.generation),
            record: Some(record),
            policy: None,
            observed_at_unix_millis: None,
        }
    }
    #[test]
    fn repeated_evidence_cutovers_keep_only_current_and_one_pending() {
        let root = Root::new();
        let identity = signed_identity();
        let store = enforced(&root, &identity);
        for sequence in 1..=6 {
            let revision = evidence(&identity, sequence);
            let receipt = renewal(&store, &identity, &revision, &format!("renew-{sequence}"));
            let prepared = store.prepare(receipt, None).unwrap();
            store.stage_evidence(&revision).unwrap();
            assert!(io::files(&root.path().join("evidence"), 3).unwrap().len() <= 2);
            store
                .with_prepared(&prepared, &mut |fence| {
                    fence.commit(&prepared)?;
                    Ok(())
                })
                .unwrap();
            assert_eq!(
                store
                    .read_evidence(&identity.release)
                    .unwrap()
                    .unwrap()
                    .0
                    .receipt,
                [sequence]
            );
            if sequence == 2 {
                // Simulate interruption after one old file was reclaimed. The
                // canonical owned inventory remains sufficient to finish GC.
                let selected = revision.digest().as_str()[7..].to_owned();
                for name in io::files(&root.path().join("evidence"), 3).unwrap() {
                    if name != selected {
                        std::fs::remove_file(
                            root.path().join("evidence").join(name).join("000.bin"),
                        )
                        .unwrap();
                    }
                }
            }
            store.reclaim_evidence().unwrap();
            assert_eq!(
                io::files(&root.path().join("evidence"), 3).unwrap().len(),
                1
            );
        }
        drop(store);
        let reopened = enforced(&root, &identity);
        assert_eq!(
            reopened
                .read_evidence(&identity.release)
                .unwrap()
                .unwrap()
                .0
                .receipt,
            [6]
        );
    }
    #[test]
    fn renewal_intent_recovery_keeps_new_evidence_and_reclaims_old() {
        let root = Root::new();
        let identity = signed_identity();
        let store = enforced(&root, &identity);
        let first = evidence(&identity, 1);
        let receipt = renewal(&store, &identity, &first, "first");
        store.stage_evidence(&first).unwrap();
        commit(&store, receipt, None).unwrap();
        let second = evidence(&identity, 2);
        let receipt = renewal(&store, &identity, &second, "second");
        store.stage_evidence(&second).unwrap();
        persistence::FAIL.with(|value| value.set(2));
        assert!(commit(&store, receipt, None).is_err());
        drop(store);
        let reopened = enforced(&root, &identity);
        assert_eq!(
            reopened
                .read_evidence(&identity.release)
                .unwrap()
                .unwrap()
                .0
                .receipt,
            [2]
        );
        assert_eq!(
            io::files(&root.path().join("evidence"), 3).unwrap().len(),
            1
        );
    }
    #[test]
    fn unknown_pending_files_fail_closed_without_deletion() {
        let root = Root::new();
        let identity = signed_identity();
        let store = enforced(&root, &identity);
        drop(store);
        let pending = root.path().join("evidence/PENDING");
        std::fs::create_dir(&pending).unwrap();
        std::fs::write(pending.join("unknown"), b"preserve").unwrap();
        assert!(LifecycleStore::open(
            &root.path(),
            LifecycleLimits::default(),
            Some(Arc::new(RejectingAuthority)),
            &[identity]
        )
        .is_err());
        assert_eq!(std::fs::read(pending.join("unknown")).unwrap(), b"preserve");
    }
}
