use super::{
    admission, capacity, corrupt, fs, io_error, read_bounded_file, shared_content, sync_dir,
    write_synced, ArtifactBlobDigest, BTreeMap, DirectoryArtifactRepository, Path, PlatformError,
    PublicationRef, ReleaseLifecycleState, State, VecDeque, WebLifecycleRecord,
    WebOperationReceipt, EVIDENCE, HEAD, PUBLICATIONS,
};
use crate::{
    package::{artifact_blob_digest, validate_package_json, PackageLimits},
    LifecycleLimits, ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseOperationDisposition,
};
use serde::{de::DeserializeOwned, Deserialize, Serialize};

pub(super) const INITIALIZED: &str = "INITIALIZED";
const INITIALIZED_BYTES: &[u8] = b"lsf-web-catalog-v1\n";

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Header {
    format_version: u32,
    records: usize,
    operations: usize,
}
#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Row {
    pub(super) record: WebLifecycleRecord,
    #[serde(with = "crate::web::codec::blob")]
    pub(super) completion: ArtifactBlobDigest,
}
pub(super) struct Recovered {
    pub(super) rows: Vec<Row>,
    pub(super) receipts: VecDeque<WebOperationReceipt>,
    pub(super) bytes: usize,
}

/// Each typed line has independent lexical/allocation limits. This avoids a
/// catalog-sized JSON array or unbounded recursive deserialization on restart.
pub(super) fn encode_line<T: Serialize>(value: &T, limit: usize) -> Result<Vec<u8>, PlatformError> {
    let bytes = serde_json::to_vec(value).map_err(|_| corrupt("web-control-encoding"))?;
    if bytes.len() > limit {
        return Err(capacity());
    }
    Ok(bytes)
}
fn decode_line<T: DeserializeOwned + Serialize>(
    bytes: &[u8],
    limit: usize,
) -> Result<T, PlatformError> {
    if bytes.is_empty() || bytes.len() > limit {
        return Err(corrupt("web-control-line-size"));
    }
    validate_package_json(
        bytes,
        PackageLimits {
            max_document_bytes: limit,
            max_depth: 8,
            max_nodes: 1024,
            ..PackageLimits::default()
        },
    )?;
    let value: T = serde_json::from_slice(bytes).map_err(|_| corrupt("web-control-shape"))?;
    if encode_line(&value, limit)? != bytes {
        return Err(corrupt("web-control-noncanonical"));
    }
    Ok(value)
}
fn append<T: Serialize>(
    bytes: &mut Vec<u8>,
    value: &T,
    line: usize,
    maximum: usize,
) -> Result<(), PlatformError> {
    let encoded = encode_line(value, line)?;
    if bytes
        .len()
        .checked_add(encoded.len())
        .and_then(|n| n.checked_add(73))
        .is_none_or(|n| n > maximum)
    {
        return Err(capacity());
    }
    bytes.extend_from_slice(&encoded);
    bytes.push(b'\n');
    Ok(())
}
pub(super) fn encode(
    state: &State,
    limits: LifecycleLimits,
    maximum: usize,
) -> Result<Vec<u8>, PlatformError> {
    if state.entries.len() > limits.max_records
        || state.receipts.len() > limits.max_recent_operations
    {
        return Err(capacity());
    }
    let mut bytes = Vec::new();
    append(
        &mut bytes,
        &Header {
            format_version: 1,
            records: state.entries.len(),
            operations: state.receipts.len(),
        },
        512,
        maximum,
    )?;
    for entry in state.entries.values() {
        validate_record(&entry.record)?;
        encode_line(&entry.record, limits.max_record_bytes)?;
        append(
            &mut bytes,
            &Row {
                record: entry.record.clone(),
                completion: entry.completion.clone(),
            },
            limits.max_record_bytes + 128,
            maximum,
        )?;
    }
    for receipt in &state.receipts {
        append(&mut bytes, receipt, limits.max_receipt_bytes, maximum)?;
    }
    let checksum = artifact_blob_digest(&bytes);
    bytes.extend_from_slice(checksum.as_str().as_bytes());
    bytes.push(b'\n');
    Ok(bytes)
}
pub(super) fn read(
    root: &Path,
    limits: LifecycleLimits,
    maximum: usize,
) -> Result<Recovered, PlatformError> {
    shared_content::regular(&root.join(HEAD))?;
    let bytes = read_bounded_file(&root.join(HEAD), maximum, "web lifecycle")?;
    if bytes.len() < 73 || bytes.last() != Some(&b'\n') {
        return Err(corrupt("web-head-truncated"));
    }
    let boundary = bytes.len() - 72;
    let (body, checksum) = bytes.split_at(boundary);
    if body.last() != Some(&b'\n')
        || artifact_blob_digest(body).as_str().as_bytes() != &checksum[..71]
    {
        return Err(corrupt("web-head-checksum"));
    }
    let mut lines = body.split(|byte| *byte == b'\n');
    let header: Header = decode_line(lines.next().ok_or_else(|| corrupt("web-head-empty"))?, 512)?;
    if header.format_version != 1
        || header.records > limits.max_records
        || header.operations > limits.max_recent_operations
    {
        return Err(corrupt("web-head-count"));
    }
    let mut rows = Vec::new();
    let mut ids = BTreeMap::new();
    let mut previous = None;
    for _ in 0..header.records {
        let row: Row = decode_line(
            lines
                .next()
                .ok_or_else(|| corrupt("web-head-row-missing"))?,
            limits.max_record_bytes + 128,
        )?;
        validate_record(&row.record)?;
        encode_line(&row.record, limits.max_record_bytes)?;
        let id = &row.record.publication.id;
        if previous.as_ref().is_some_and(|old| old >= id) {
            return Err(corrupt("web-head-row-order"));
        }
        previous = Some(id.clone());
        ids.insert(row.record.publication.clone(), row.record.generation);
        rows.push(row);
    }
    let mut receipts = VecDeque::new();
    let mut operations = std::collections::BTreeSet::new();
    for _ in 0..header.operations {
        let receipt: WebOperationReceipt = decode_line(
            lines
                .next()
                .ok_or_else(|| corrupt("web-head-receipt-missing"))?,
            limits.max_receipt_bytes,
        )?;
        validate_receipt(&receipt)?;
        if ids
            .get(&receipt.publication)
            .is_none_or(|generation| *generation < receipt.resulting_generation)
            || !operations.insert((
                receipt.publication.scope.clone(),
                receipt.operation_id.clone(),
            ))
        {
            return Err(corrupt("web-receipt-association"));
        }
        receipts.push_back(receipt);
    }
    if lines.next() != Some(&[][..]) || lines.next().is_some() {
        return Err(corrupt("web-head-trailing-content"));
    }
    Ok(Recovered {
        rows,
        receipts,
        bytes: bytes.len(),
    })
}
pub(super) fn validate_record(row: &WebLifecycleRecord) -> Result<(), PlatformError> {
    row.actor.validate()?;
    crate::ReleaseOperationPrecondition {
        operation_id: row.operation_id.clone(),
        expected_generation: row.generation,
    }
    .validate()?;
    if row.publication.scope.tenant().is_none()
        || row.generation == 0
        || row.publication != PublicationRef::package(row.publication.scope.clone(), &row.package)?
    {
        return Err(corrupt("web-lifecycle-association"));
    }
    let valid = match row.state {
        ReleaseLifecycleState::Admitted => matches!(
            row.reason,
            ReleaseLifecycleReason::Admitted | ReleaseLifecycleReason::EvidenceRenewed
        ),
        ReleaseLifecycleState::Revoked => matches!(
            row.reason,
            ReleaseLifecycleReason::OperatorRevocation
                | ReleaseLifecycleReason::SecurityIncident
                | ReleaseLifecycleReason::CorruptContent
        ),
        ReleaseLifecycleState::Retired => matches!(
            row.reason,
            ReleaseLifecycleReason::Superseded
                | ReleaseLifecycleReason::EndOfSupport
                | ReleaseLifecycleReason::OperatorRetirement
        ),
    };
    if !valid {
        return Err(corrupt("web-lifecycle-reason"));
    }
    Ok(())
}
fn validate_receipt(receipt: &WebOperationReceipt) -> Result<(), PlatformError> {
    receipt.actor.validate()?;
    crate::ReleaseOperationPrecondition {
        operation_id: receipt.operation_id.clone(),
        expected_generation: receipt.expected_generation,
    }
    .validate()?;
    if receipt.format_version != 1
        || receipt.disposition != ReleaseOperationDisposition::Committed
        || receipt.expected_generation.checked_add(1) != Some(receipt.resulting_generation)
        || (receipt.action == ReleaseLifecycleAction::Publish && receipt.expected_generation != 0)
    {
        return Err(corrupt("web-operation-receipt"));
    }
    Ok(())
}
/// The only replacement operation. Temporary files never provide authority.
pub(super) fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), PlatformError> {
    let temporary = path.with_extension("next");
    if temporary.try_exists().map_err(io_error)? {
        shared_content::regular(&temporary)?;
        fs::remove_file(&temporary).map_err(io_error)?;
    }
    if path.try_exists().map_err(io_error)? {
        shared_content::regular(path)?;
    }
    write_synced(&temporary, bytes)?;
    fs::rename(&temporary, path).map_err(io_error)?;
    sync_dir(path.parent().ok_or_else(|| corrupt("web-control-parent"))?)
}
impl DirectoryArtifactRepository {
    pub(super) fn web_head_limit(&self) -> usize {
        self.lifecycle_limits
            .max_total_metadata_bytes
            .min(self.config.max_index_bytes)
    }
    pub(super) fn activate_web(&self, state: &mut State) -> Result<(), PlatformError> {
        if state.enabled {
            return Ok(());
        }
        let root = self.web_path();
        fs::create_dir_all(root.join(PUBLICATIONS)).map_err(io_error)?;
        fs::create_dir_all(root.join(EVIDENCE)).map_err(io_error)?;
        let bytes = encode(state, self.lifecycle_limits, self.web_head_limit())?;
        atomic_write(&root.join(HEAD), &bytes)?;
        atomic_write(&root.join(INITIALIZED), INITIALIZED_BYTES)?;
        sync_dir(&root)?;
        sync_dir(&self.root)?;
        // Older binaries accept only v1 and fail before shared-blob recovery/GC.
        atomic_write(
            &self.root.join(admission::WEB_MODE_FILE),
            admission::WEB_MODE,
        )?;
        state.enabled = true;
        state.head_bytes = bytes.len();
        Ok(())
    }
    pub(super) fn web_enabled(&self) -> Result<bool, PlatformError> {
        let marker = self.root.join(admission::WEB_MODE_FILE);
        if !marker.try_exists().map_err(io_error)? {
            return Ok(false);
        }
        Ok(read_bounded_file(&marker, 64, "admission mode")? == admission::WEB_MODE)
    }
    pub(super) fn check_web_initialized(&self) -> Result<(), PlatformError> {
        let marker = self.web_path().join(INITIALIZED);
        shared_content::regular(&marker)?;
        if read_bounded_file(&marker, 64, "web initialization")? != INITIALIZED_BYTES {
            return Err(corrupt("web-initialization-marker"));
        }
        Ok(())
    }
}
