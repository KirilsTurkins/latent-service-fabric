use super::{
    capacity, corrupt, denied, error, persistence, ArtifactBlobDigest, Entry,
    PackageAdmissionUpload, PlatformError, PlatformErrorCode, PublicationRef,
    ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseMutationContext,
    ReleaseOperationDisposition, State, WebOperationReceipt,
};
use sha2::{Digest, Sha256};

pub(super) fn receipt(
    context: &ReleaseMutationContext,
    reference: &PublicationRef,
    action: ReleaseLifecycleAction,
    reason: ReleaseLifecycleReason,
    payload: &ArtifactBlobDigest,
) -> Result<WebOperationReceipt, PlatformError> {
    context.validate()?;
    if context.scope != reference.scope || context.scope.tenant().is_none() {
        return Err(denied());
    }
    let operation = context.operation.as_ref().ok_or_else(|| {
        error(
            PlatformErrorCode::InvalidArgument,
            "web-operation-precondition-required",
        )
    })?;
    let resulting_generation = operation
        .expected_generation
        .checked_add(1)
        .ok_or_else(capacity)?;
    let bytes = persistence::encode_line(
        &(
            reference,
            &context.actor,
            &operation.operation_id,
            operation.expected_generation,
            action,
            reason,
            payload.as_str(),
        ),
        4096,
    )?;
    let mut hash = Sha256::new();
    hash.update(b"lsf-web-operation-v1\0");
    hash.update(bytes);
    Ok(WebOperationReceipt {
        format_version: 1,
        publication: reference.clone(),
        operation_id: operation.operation_id.clone(),
        action,
        actor: context.actor.clone(),
        expected_generation: operation.expected_generation,
        resulting_generation,
        disposition: ReleaseOperationDisposition::Committed,
        reason,
        request_digest: format!("sha256:{:x}", hash.finalize())
            .parse()
            .map_err(|_| corrupt("web-request-digest"))?,
    })
}
pub(super) fn check_generation(
    state: &State,
    receipt: &WebOperationReceipt,
) -> Result<(), PlatformError> {
    let generation = state
        .entries
        .get(&receipt.publication.id)
        .map_or(0, |entry| entry.record.generation);
    if generation != receipt.expected_generation {
        return Err(error(
            PlatformErrorCode::StateConflict,
            "web-generation-conflict",
        ));
    }
    Ok(())
}
/// Exact raw request, excluding the authority's newly produced receipt. Retry
/// remains inspectable after proof expiry/revocation without granting new use.
pub(super) fn upload_digest(upload: &PackageAdmissionUpload) -> ArtifactBlobDigest {
    fn field(hash: &mut Sha256, value: &[u8]) {
        hash.update((value.len() as u64).to_le_bytes());
        hash.update(value);
    }
    let mut hash = Sha256::new();
    hash.update(b"lsf-web-upload-v1\0");
    field(&mut hash, &upload.manifest);
    field(&mut hash, &upload.configuration);
    hash.update((upload.layers.len() as u64).to_le_bytes());
    for (path, bytes) in &upload.layers {
        field(&mut hash, path.as_bytes());
        field(&mut hash, bytes);
    }
    for entries in [&upload.signatures, &upload.provenance, &upload.sboms] {
        hash.update((entries.len() as u64).to_le_bytes());
        for evidence in entries {
            field(&mut hash, &evidence.manifest);
            field(&mut hash, &evidence.configuration);
            field(&mut hash, &evidence.payload);
        }
    }
    format!("sha256:{:x}", hash.finalize())
        .parse()
        .expect("SHA-256")
}
pub(super) fn updated(
    state: &State,
    receipt: &WebOperationReceipt,
    entry: Entry,
    maximum: usize,
) -> State {
    let mut next = state.clone();
    next.entries.insert(receipt.publication.id.clone(), entry);
    if next.receipts.len() == maximum {
        next.receipts.pop_front();
    }
    next.receipts.push_back(receipt.clone());
    next
}
