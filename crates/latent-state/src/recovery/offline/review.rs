use super::{
    operation::Busy, OfflineOperation, OfflineRecoveryError, OfflineRecoverySource,
    RecoveryReviewRequest, CODEC_BYTES, OPERATION_SCRATCH_BYTES,
};
use crate::{
    embedded::{AtomicBatch, ExpectedRow, FencedStoreError, StoreError},
    recovery::{
        guard_key,
        resume::{
            NamespaceRecoveryView, NamespaceResumePlan, NamespaceResumeReceipt,
            NamespaceResumeRequest,
        },
        snapshot::validate_deadline,
        RecoveryGuard, RecoveryStatus,
    },
    store_io::StoreIoKind,
};
use std::{sync::Arc, time::Instant};

fn charge(source: &OfflineRecoverySource) -> Result<u64, OfflineRecoveryError> {
    let scratch = source.codecs.scratch_bytes();
    if scratch > CODEC_BYTES {
        return Err(OfflineRecoveryError::InvalidConfiguration);
    }
    OPERATION_SCRATCH_BYTES
        .checked_add(scratch)
        .ok_or(OfflineRecoveryError::InvalidConfiguration)
}

pub(super) fn inspect_namespace(
    source: &OfflineRecoverySource,
    operator_id: String,
    namespace: latent_core::StateNamespaceId,
    deadline: Instant,
) -> Result<OfflineOperation<NamespaceRecoveryView>, OfflineRecoveryError> {
    for identity in [&operator_id, &namespace.0] {
        crate::namespace::identity(identity)
            .map_err(|_| OfflineRecoveryError::InvalidConfiguration)?;
    }
    validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
    let bytes = charge(source)?;
    let operator = operator_id.clone();
    drop(operator_id);
    let selected = namespace.clone();
    drop(namespace);
    let tenant = latent_core::TenantId(source.tenant.clone());
    let busy = Busy::accept(source)?;
    let codecs = Arc::clone(&source.codecs);
    let inner = source
        .owner
        .with_store(StoreIoKind::Read, bytes, move |store| {
            let _busy = busy;
            let view = store.snapshot()?;
            Ok((|| {
                validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
                codecs
                    .authorize_namespace_inspection(&view, &operator, &selected)
                    .map_err(OfflineRecoveryError::Review)?;
                NamespaceRecoveryView::capture(&view, &tenant, &selected)
                    .map_err(OfflineRecoveryError::Input)
            })())
        })
        .map_err(OfflineRecoveryError::Protected)?;
    Ok(OfflineOperation { inner })
}

pub(super) fn resume(
    source: &OfflineRecoverySource,
    request: NamespaceResumeRequest,
    deadline: Instant,
) -> Result<OfflineOperation<NamespaceResumeReceipt>, OfflineRecoveryError> {
    request.validate().map_err(OfflineRecoveryError::Input)?;
    if request.scope.tenant.0 != source.tenant {
        return Err(OfflineRecoveryError::InvalidConfiguration);
    }
    validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
    let bytes = charge(source)?;
    let compact = request.clone();
    drop(request);
    let request = compact;
    let busy = Busy::accept(source)?;
    let codecs = Arc::clone(&source.codecs);
    let inner = source
        .owner
        .with_store(StoreIoKind::Write, bytes, move |store| {
            let _busy = busy;
            let view = store.snapshot()?;
            let prepared = (|| {
                validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
                codecs
                    .validate_view(&view)
                    .map_err(OfflineRecoveryError::Input)?
                    .inventory
                    .require_decoders(codecs.installed_formats())
                    .map_err(|_| OfflineRecoveryError::Input(StoreError::UnsupportedFormat))?;
                NamespaceResumePlan::prepare(&view, &request, |view, request, observed| {
                    codecs.review_namespace_resume(view, request, observed)
                })
                .map_err(OfflineRecoveryError::Review)
            })();
            drop(view);
            let plan = match prepared {
                Ok(plan) => plan,
                Err(error) => return Ok(Err(error)),
            };
            let receipt = plan.receipt().clone();
            match store.apply_fenced(plan.into_batch(), || {
                validate_deadline(deadline)?;
                codecs.accept_namespace_resume(&request)
            }) {
                Ok(()) => Ok(Ok(receipt)),
                Err(FencedStoreError::Store(error)) => Err(error),
                Err(FencedStoreError::Fence(error)) => Ok(Err(OfflineRecoveryError::Review(error))),
            }
        })
        .map_err(OfflineRecoveryError::Protected)?;
    Ok(OfflineOperation { inner })
}

pub(super) fn reconcile(
    source: &OfflineRecoverySource,
    request: RecoveryReviewRequest,
    deadline: Instant,
) -> Result<OfflineOperation<RecoveryGuard>, OfflineRecoveryError> {
    crate::namespace::identity(&request.operator_id)
        .map_err(|_| OfflineRecoveryError::InvalidConfiguration)?;
    if request.expected_guard.status() != RecoveryStatus::ReconciliationRequired
        || request.review_digest == [0; 32]
    {
        return Err(OfflineRecoveryError::InvalidConfiguration);
    }
    validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
    let bytes = charge(source)?;
    let compact = request.clone();
    drop(request);
    let request = compact;
    let busy = Busy::accept(source)?;
    let codecs = Arc::clone(&source.codecs);
    let inner = source
        .owner
        .with_store(StoreIoKind::Write, bytes, move |store| {
            let _busy = busy;
            let view = store.snapshot()?;
            let prepared = (|| {
                validate_deadline(deadline)?;
                codecs
                    .validate_view(&view)?
                    .inventory
                    .require_decoders(codecs.installed_formats())
                    .map_err(|_| StoreError::UnsupportedFormat)?;
                codecs.review_reconciliation(&view, &request)?;
                let bytes = view.get(&guard_key())?.ok_or(StoreError::Conflict)?;
                let actual = RecoveryGuard::decode(&bytes)?;
                if actual.status() == RecoveryStatus::ReviewAccepted {
                    if actual.snapshot_digest() != request.expected_guard.snapshot_digest()
                        || actual.operation_digest() != request.expected_guard.operation_digest()
                        || actual.window_digest() != request.expected_guard.window_digest()
                        || actual.review_digest() != request.review_digest
                    {
                        return Err(StoreError::Conflict);
                    }
                    return Ok((
                        AtomicBatch {
                            expectations: vec![ExpectedRow {
                                key: guard_key(),
                                value: Some(bytes),
                            }],
                            mutations: vec![],
                        },
                        actual,
                    ));
                }
                let batch = request.expected_guard.prepare_reviewed(
                    &view,
                    request.review_digest,
                    |_, _, _| Ok(()),
                )?;
                let accepted = RecoveryGuard::decode(
                    batch.mutations[0]
                        .value
                        .as_ref()
                        .ok_or(StoreError::Corrupt)?,
                )?;
                Ok((batch, accepted))
            })();
            drop(view);
            let (batch, accepted) = match prepared {
                Ok(prepared) => prepared,
                Err(error) => return Ok(Err(OfflineRecoveryError::Review(error))),
            };
            match store.apply_fenced(batch, || {
                validate_deadline(deadline)?;
                codecs.accept_reconciliation(&request)
            }) {
                Ok(()) => Ok(Ok(accepted)),
                Err(FencedStoreError::Store(error)) => Err(error),
                Err(FencedStoreError::Fence(error)) => Ok(Err(OfflineRecoveryError::Review(error))),
            }
        })
        .map_err(OfflineRecoveryError::Protected)?;
    Ok(OfflineOperation { inner })
}
