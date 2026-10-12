//! The installed owner must reserve its guard inside the original finite batch.
use super::*;
use std::sync::atomic::AtomicUsize;

const RECEIPT: &[u8] = b"bounded-retained-test-receipt-v1";
const PREFIX: &[u8] = b"bounded-retained-test-v1\0";

struct BoundedCodecs {
    inner: Arc<Codecs>,
    expectations: usize,
    includes_guard: bool,
    accepted: AtomicUsize,
}

fn row(index: usize) -> RowKey {
    let mut key = PREFIX.to_vec();
    key.extend_from_slice(&u32::try_from(index).unwrap().to_be_bytes());
    RowKey {
        family: Family::Maintenance,
        key,
    }
}

impl RecoveryCodecs for BoundedCodecs {
    fn runtime_digest(&self) -> [u8; 32] {
        self.inner.runtime_digest()
    }
    fn retained_bytes(&self) -> u64 {
        self.inner.retained_bytes()
    }
    fn scratch_bytes(&self) -> u64 {
        self.inner.scratch_bytes()
    }
    fn installed_formats(&self) -> &[RetainedFormat] {
        self.inner.installed_formats()
    }
    fn validate_row(&self, view: &ReadView, key: &RowKey, value: &[u8]) -> Result<(), StoreError> {
        if *key == row(0) && value == RECEIPT {
            Ok(())
        } else {
            self.inner.validate_row(view, key, value)
        }
    }
    fn validate_view(&self, view: &ReadView) -> Result<SnapshotClosure, StoreError> {
        // Preserve the complete original installed validation, extending it only
        // for this fixture's closed maintenance receipt.
        for family in super::super::super::snapshot::FAMILIES {
            let mut resume = None;
            loop {
                let page = view.scan_after(family, b"", resume.as_deref(), 128, 4 * 1024 * 1024)?;
                for (key, value) in page.rows {
                    self.validate_row(view, &key, &value)?;
                }
                resume = page.resume;
                if resume.is_none() {
                    break;
                }
            }
        }
        Ok(SnapshotClosure {
            inventory: RetainedInventory::default(),
            required_artifacts: vec![artifact()],
        })
    }
    fn verify_artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError> {
        self.inner.verify_artifact(artifact)
    }
    fn review_backup(
        &self,
        view: &ReadView,
        metadata: &SnapshotMetadata,
        file: &SnapshotFile,
    ) -> Result<(), StoreError> {
        self.inner.review_backup(view, metadata, file)
    }
    fn authorize_inspection(
        &self,
        view: &ReadView,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError> {
        self.inner.authorize_inspection(view, request)
    }
    fn review_restore(
        &self,
        view: &ReadView,
        window: &RestoreWindow,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError> {
        self.inner.review_restore(view, window, request)
    }
    fn prepare_retained_reconciliation(
        &self,
        view: &ReadView,
        _request: &RetainedReconciliationRequest,
    ) -> Result<PreparedRetainedReconciliation, StoreError> {
        let ordinary = self.expectations - usize::from(self.includes_guard);
        let mut expectations = (0..ordinary)
            .map(|index| ExpectedRow {
                key: row(index),
                value: None,
            })
            .collect::<Vec<_>>();
        if self.includes_guard {
            let key = super::super::super::guard_key();
            expectations.push(ExpectedRow {
                value: view.get(&key)?,
                key,
            });
        }
        Ok(PreparedRetainedReconciliation {
            batch: AtomicBatch {
                expectations,
                mutations: vec![RowMutation {
                    key: row(0),
                    value: Some(RECEIPT.to_vec()),
                }],
            },
            receipt: RECEIPT.to_vec(),
            replay: false,
        })
    }
    fn accept_retained_reconciliation(
        &self,
        _request: &RetainedReconciliationRequest,
    ) -> Result<(), StoreError> {
        self.accepted.fetch_add(1, Ordering::AcqRel);
        Ok(())
    }
}

#[test]
fn protected_retained_reconciliation_reserves_the_guard_inside_the_original_expectation_bound() {
    for (expectations, includes_guard, refusal) in [
        (256, false, Some(StoreError::Capacity)),
        (255, false, None),
        (256, true, None),
        (257, true, Some(StoreError::Invalid)),
    ] {
        let directory = root();
        let original = populated_owner(directory.path());
        let guard = RecoveryGuard::staging([1; 32], [2; 32], [3; 32]).unwrap();
        let completed_guard = guard.prepare_completed().unwrap().mutations[0]
            .value
            .clone()
            .unwrap();
        wait(
            original
                .with_store(StoreIoKind::Write, 1024 * 1024, move |store| {
                    store.apply(guard.prepare_staging()?)?;
                    store.apply(guard.prepare_completed()?)
                })
                .unwrap(),
        )
        .unwrap()
        .unwrap();
        finish(&original);
        let codecs = Arc::new(BoundedCodecs {
            inner: codecs(),
            expectations,
            includes_guard,
            accepted: AtomicUsize::new(0),
        });
        let source = wait(
            OfflineRecoverySource::start_review(
                ProtectedStoreConfig::bounded_linux(directory.path().into()),
                "tenant".into(),
                codecs.clone(),
            )
            .unwrap(),
        )
        .unwrap();
        let result = wait(
            source
                .reconcile_retained(
                    RetainedReconciliationRequest {
                        operator_id: "operator".into(),
                        operation_id: "bounded-original".into(),
                        payload: b"closed-fixture-request".to_vec(),
                    },
                    Instant::now() + WATCHDOG,
                )
                .unwrap(),
        );
        match refusal {
            Some(error) => assert_eq!(result, Err(OfflineRecoveryError::Review(error))),
            None => assert_eq!(result, Ok(RECEIPT.to_vec())),
        }
        assert_eq!(
            codecs.accepted.load(Ordering::Acquire),
            usize::from(refusal.is_none())
        );
        let observed = wait(
            source
                .owner
                .with_store(StoreIoKind::Read, 1024 * 1024, |store| {
                    let view = store.snapshot()?;
                    assert_eq!(
                        RecoveryGuard::capture(&view)?.unwrap().status(),
                        RecoveryStatus::ReconciliationRequired
                    );
                    Ok((
                        view.get(&super::super::super::guard_key())?,
                        view.get(&row(0))?,
                    ))
                })
                .unwrap(),
        )
        .unwrap()
        .unwrap();
        assert_eq!(observed.0, Some(completed_guard));
        assert_eq!(observed.1, refusal.is_none().then(|| RECEIPT.to_vec()));
        assert_eq!(source.snapshot().unwrap().accepted, 0);
        close(&source);
        assert_eq!(source.snapshot().unwrap().retained_bytes, 0);
    }
}
