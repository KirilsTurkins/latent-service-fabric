//! Finite logical snapshot stream from one selected-engine MVCC view. These
//! blocking functions belong to the protected store's fixed physical workers.
//! No database-file copying, provider calls, credentials or public artifacts.

use crate::{
    embedded::{EmbeddedStore, Family, ReadView, RowKey, StoreError},
    namespace::{
        catalog::NamespaceCatalog,
        compatibility::{RetainedCount, RetainedFormat, RetainedInventory, SchemaId},
        history::NamespaceHistory,
        NamespaceRecord, NamespaceStatus,
    },
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fmt::Write as _,
    io::{Read, Seek, SeekFrom, Write},
    time::{Duration, Instant},
};

const MAGIC: &[u8] = b"latent-offline-snapshot\0\x02";
const ENGINE: &str = crate::embedded::STORE_FORMAT;
pub const SNAPSHOT_ROWS: u64 = 65_536;
pub const SNAPSHOT_LOGICAL_BYTES: u64 = 128 * 1024 * 1024;
pub const SNAPSHOT_FILE_BYTES: u64 = 160 * 1024 * 1024;
pub const MANIFEST_BYTES: usize = 1024 * 1024;
pub const SNAPSHOT_NAMESPACES: usize = 128;
pub const SNAPSHOT_ARTIFACTS: usize = 128;
pub const SNAPSHOT_DURATION: Duration = Duration::from_mins(1);
const PAGE_BYTES: usize = 4 * 1024 * 1024;
pub(super) const FAMILIES: [Family; 10] = [
    Family::Namespace,
    Family::State,
    Family::Tombstone,
    Family::Command,
    Family::Result,
    Family::Outbox,
    Family::Attempt,
    Family::Inbox,
    Family::PayloadReference,
    Family::Maintenance,
];

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RequiredArtifact {
    /// Exact immutable source association, such as schema hash/publication ID.
    #[serde(deserialize_with = "limits::identity")]
    pub identity: String,
    pub digest: [u8; 32],
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SnapshotMetadata {
    /// Original operator/audit context. A full-unit snapshot captures every
    /// namespace; this descriptive field is neither a row filter nor a grant.
    #[serde(deserialize_with = "limits::identity")]
    pub tenant: String,
    #[serde(deserialize_with = "limits::identity")]
    pub operation_id: String,
    #[serde(deserialize_with = "limits::identity")]
    pub operator_id: String,
    pub runtime_digest: [u8; 32],
    #[serde(deserialize_with = "limits::formats")]
    pub decoder_formats: Vec<RetainedFormat>,
    #[serde(deserialize_with = "limits::artifacts")]
    pub required_artifacts: Vec<RequiredArtifact>,
}

impl SnapshotMetadata {
    pub fn validate(&self) -> Result<(), StoreError> {
        for identity in [&self.tenant, &self.operation_id, &self.operator_id] {
            crate::namespace::identity(identity).map_err(|_| StoreError::Invalid)?;
        }
        if self.runtime_digest == [0; 32] || self.required_artifacts.len() > SNAPSHOT_ARTIFACTS {
            return Err(StoreError::Invalid);
        }
        RetainedInventory::default()
            .require_decoders(&self.decoder_formats)
            .map_err(|_| StoreError::UnsupportedFormat)?;
        for (index, artifact) in self.required_artifacts.iter().enumerate() {
            crate::namespace::identity(&artifact.identity).map_err(|_| StoreError::Invalid)?;
            if artifact.digest == [0; 32]
                || self.required_artifacts[..index]
                    .iter()
                    .any(|prior| prior.identity == artifact.identity)
            {
                return Err(StoreError::Invalid);
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NamespaceSnapshot {
    #[serde(deserialize_with = "limits::record")]
    pub record: Vec<u8>,
    #[serde(deserialize_with = "limits::record")]
    pub history: Vec<u8>,
}

impl NamespaceSnapshot {
    pub fn decode(&self) -> Result<(NamespaceRecord, NamespaceHistory), StoreError> {
        let record = NamespaceRecord::decode(&self.record).map_err(|_| StoreError::Corrupt)?;
        let history = NamespaceHistory::decode(&self.history).map_err(|_| StoreError::Corrupt)?;
        history
            .check_namespace(&record)
            .map_err(|_| StoreError::Corrupt)?;
        if record.encode().map_err(|_| StoreError::Corrupt)? != self.record
            || history.encode().map_err(|_| StoreError::Corrupt)? != self.history
        {
            return Err(StoreError::Corrupt);
        }
        Ok((record, history))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct InventoryEntry {
    format: RetainedFormat,
    count: RetainedCount,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SnapshotManifest {
    #[serde(deserialize_with = "limits::identity")]
    format: String,
    #[serde(deserialize_with = "limits::identity")]
    engine: String,
    /// Observed exact bytes, never permission to replace a destination owner.
    #[serde(deserialize_with = "limits::record")]
    pub source_store_identity: Vec<u8>,
    pub metadata: SnapshotMetadata,
    #[serde(deserialize_with = "limits::namespaces")]
    pub namespaces: Vec<NamespaceSnapshot>,
    pub rows: u64,
    pub logical_bytes: u64,
    pub rows_digest: [u8; 32],
    #[serde(deserialize_with = "limits::inventory")]
    inventory: Vec<InventoryEntry>,
}

impl SnapshotManifest {
    pub fn inventory(&self) -> Result<RetainedInventory, StoreError> {
        if self.inventory.len() > crate::namespace::compatibility::RETAINED_FORMATS {
            return Err(StoreError::Capacity);
        }
        let mut inventory = RetainedInventory::default();
        for (index, entry) in self.inventory.iter().enumerate() {
            if index > 0 && self.inventory[index - 1].format >= entry.format {
                return Err(StoreError::Corrupt);
            }
            inventory
                .observe(entry.format.clone(), entry.count)
                .map_err(|_| StoreError::Corrupt)?;
        }
        Ok(inventory)
    }

    pub fn validate(&self) -> Result<(), StoreError> {
        self.metadata.validate()?;
        if self.format != "latent.offline-snapshot.v2" || self.engine != ENGINE {
            return Err(StoreError::UnsupportedFormat);
        }
        if crate::store_identity::StoreIdentity::decode(&self.source_store_identity)?.encode()
            != self.source_store_identity
        {
            return Err(StoreError::Corrupt);
        }
        if self.namespaces.is_empty()
            || self.namespaces.len() > SNAPSHOT_NAMESPACES
            || self.rows == 0
            || self.rows > SNAPSHOT_ROWS
            || self.logical_bytes > SNAPSHOT_LOGICAL_BYTES
            || self.rows_digest == [0; 32]
        {
            return Err(StoreError::Capacity);
        }
        let mut identities = std::collections::BTreeSet::new();
        for namespace in &self.namespaces {
            let (record, _) = namespace.decode()?;
            if record.status == NamespaceStatus::Active
                || !identities.insert((
                    record.tenant.0.clone(),
                    record.id.0.clone(),
                    record.version.incarnation,
                ))
            {
                return Err(StoreError::Conflict);
            }
            let schema = SchemaId::parse(&record.state_schema).map_err(|_| StoreError::Corrupt)?;
            if !self
                .metadata
                .required_artifacts
                .iter()
                .any(|artifact| artifact.identity == schema.as_str())
            {
                return Err(StoreError::Corrupt);
            }
        }
        require_schema_artifacts(&self.metadata, &self.namespaces)?;
        self.inventory()?
            .require_decoders(&self.metadata.decoder_formats)
            .map_err(|_| StoreError::UnsupportedFormat)
    }

    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.validate()?;
        let bytes = serde_json::to_vec(self).map_err(|_| StoreError::Invalid)?;
        if bytes.len() > MANIFEST_BYTES {
            return Err(StoreError::Capacity);
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if bytes.is_empty() || bytes.len() > MANIFEST_BYTES {
            return Err(StoreError::Capacity);
        }
        let manifest: Self = serde_json::from_slice(bytes).map_err(|_| StoreError::Corrupt)?;
        manifest.validate()?;
        // Canonical metadata and duplicate-key refusal: serde's closed fields
        // reject repeats and unknowns; accepted bytes have one exact encoding.
        if manifest.encode()? != bytes {
            return Err(StoreError::Corrupt);
        }
        Ok(manifest)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SnapshotReceipt {
    pub snapshot_digest: [u8; 32],
    pub manifest_digest: [u8; 32],
    pub file_bytes: u64,
    pub manifest: SnapshotManifest,
}

pub struct SnapshotClosure {
    pub inventory: RetainedInventory,
    /// Required exact immutable associations collected by the installed linked
    /// row owners, including still-retained original publication/schema inputs.
    pub required_artifacts: Vec<RequiredArtifact>,
}

/// Source-engine faults are separate from operator-file, review and deadline
/// refusal. A failed output never quarantines a healthy source database.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SnapshotError {
    Source(StoreError),
    Review(StoreError),
    Output,
    Deadline,
    Capacity,
}

impl SnapshotError {
    pub(crate) fn source(error: StoreError) -> Self {
        match error {
            StoreError::SnapshotExpired => Self::Deadline,
            StoreError::Capacity => Self::Capacity,
            StoreError::Conflict | StoreError::Invalid | StoreError::UnsupportedFormat => {
                Self::Review(error)
            }
            _ => Self::Source(error),
        }
    }
}

impl SnapshotClosure {
    pub fn require_declared(&self, metadata: &SnapshotMetadata) -> Result<(), StoreError> {
        if self.required_artifacts.len() > SNAPSHOT_ARTIFACTS {
            return Err(StoreError::Capacity);
        }
        for (index, artifact) in self.required_artifacts.iter().enumerate() {
            if self.required_artifacts[..index]
                .iter()
                .any(|prior| prior.identity == artifact.identity)
                || !metadata.required_artifacts.contains(artifact)
            {
                return Err(StoreError::Corrupt);
            }
        }
        self.inventory
            .require_decoders(&metadata.decoder_formats)
            .map_err(|_| StoreError::UnsupportedFormat)
    }
}

/// Export after physical quiescence. A linked-row validator and immutable
/// artifact verifier are mandatory; app schema declarations are not decoders.
#[cfg(test)]
pub(crate) fn export_snapshot(
    store: &EmbeddedStore,
    metadata: SnapshotMetadata,
    output: &mut impl Write,
    deadline: Instant,
    validate: impl FnOnce(&ReadView) -> Result<SnapshotClosure, StoreError>,
    verify_artifact: impl FnMut(&RequiredArtifact) -> Result<(), StoreError>,
) -> Result<SnapshotReceipt, SnapshotError> {
    export_reviewed_snapshot(
        store,
        metadata,
        output,
        deadline,
        |view| validate(view).map_err(SnapshotError::source),
        verify_artifact,
    )
}

/// Same bounded producer with typed installed-owner review failures. A catalog,
/// current-authority or decoder refusal never becomes a physical source fault.
pub(crate) fn export_reviewed_snapshot(
    store: &EmbeddedStore,
    metadata: SnapshotMetadata,
    output: &mut impl Write,
    deadline: Instant,
    validate: impl FnOnce(&ReadView) -> Result<SnapshotClosure, SnapshotError>,
    mut verify_artifact: impl FnMut(&RequiredArtifact) -> Result<(), StoreError>,
) -> Result<SnapshotReceipt, SnapshotError> {
    metadata.validate().map_err(SnapshotError::Review)?;
    validate_deadline(deadline).map_err(SnapshotError::source)?;
    if store.live_views() != 0 {
        return Err(SnapshotError::Review(StoreError::Conflict));
    }
    let view = store.snapshot().map_err(SnapshotError::source)?;
    let source_store_identity = crate::store_identity::StoreIdentity::inspect(&view)
        .map_err(SnapshotError::source)?
        .ok_or(SnapshotError::Review(StoreError::UnsupportedFormat))?
        .encode();
    let namespaces = capture_namespaces(&view).map_err(SnapshotError::source)?;
    let closure = validate(&view)?;
    closure
        .require_declared(&metadata)
        .map_err(SnapshotError::Review)?;
    let inventory = closure.inventory;
    require_schema_artifacts(&metadata, &namespaces).map_err(SnapshotError::Review)?;
    for artifact in &metadata.required_artifacts {
        verify_artifact(artifact).map_err(SnapshotError::Review)?;
    }
    let mut sink = SnapshotWriter {
        output,
        hash: Sha256::new(),
        bytes: 0,
        deadline,
    };
    sink.write(MAGIC)?;
    let observed = visit_view_checked(&view, deadline, |header, key, value| {
        for bytes in [&header[..], &key.key, value] {
            sink.write(bytes)?;
        }
        Ok(())
    })
    .map_err(|error| match error {
        RowWalkError::Source(error) => SnapshotError::source(error),
        RowWalkError::Visit(error) => error,
    })?;
    let manifest = SnapshotManifest {
        format: "latent.offline-snapshot.v2".into(),
        engine: ENGINE.into(),
        source_store_identity,
        metadata,
        namespaces,
        rows: observed.rows,
        logical_bytes: observed.logical_bytes,
        rows_digest: observed.digest,
        inventory: inventory
            .entries()
            .iter()
            .map(|(format, count)| InventoryEntry {
                format: format.clone(),
                count: *count,
            })
            .collect(),
    };
    let encoded = manifest.encode().map_err(SnapshotError::Review)?;
    sink.write(&[0])?;
    sink.write(
        &u32::try_from(encoded.len())
            .map_err(|_| SnapshotError::Capacity)?
            .to_le_bytes(),
    )?;
    sink.write(&encoded)?;
    let manifest_digest: [u8; 32] = Sha256::digest(&encoded).into();
    sink.write(&manifest_digest)?;
    sink.output.flush().map_err(|_| SnapshotError::Output)?;
    checkpoint(deadline).map_err(SnapshotError::source)?;
    Ok(SnapshotReceipt {
        snapshot_digest: sink.hash.finalize().into(),
        manifest_digest,
        file_bytes: sink.bytes,
        manifest,
    })
}

/// Descriptive summary of one bounded coherent native row walk. It provides
/// neither quiescence proof nor permission to read, restore, or resume work.
pub struct RowSummary {
    pub rows: u64,
    pub logical_bytes: u64,
    pub digest: [u8; 32],
}

/// The same bounded canonical row walk backs export and exact recovery-window
/// capture, including attempt/inbox/clock changes without namespace increments.
pub fn visit_view(
    view: &ReadView,
    deadline: Instant,
    visit: impl FnMut(&[u8; 8], &RowKey, &[u8]) -> Result<(), StoreError>,
) -> Result<RowSummary, StoreError> {
    visit_view_checked(view, deadline, visit).map_err(|error| match error {
        RowWalkError::Source(error) | RowWalkError::Visit(error) => error,
    })
}

enum RowWalkError<E> {
    Source(StoreError),
    Visit(E),
}

fn visit_view_checked<E>(
    view: &ReadView,
    deadline: Instant,
    mut visit: impl FnMut(&[u8; 8], &RowKey, &[u8]) -> Result<(), E>,
) -> Result<RowSummary, RowWalkError<E>> {
    validate_deadline(deadline).map_err(RowWalkError::Source)?;
    let mut rows = 0u64;
    let mut logical_bytes = 0u64;
    let mut rows_hash = Sha256::new();
    for family in FAMILIES {
        let mut resume = None;
        loop {
            checkpoint(deadline).map_err(RowWalkError::Source)?;
            let page = view
                .scan_after(family, b"", resume.as_deref(), 128, PAGE_BYTES)
                .map_err(RowWalkError::Source)?;
            for (key, value) in page.rows {
                rows = rows
                    .checked_add(1)
                    .ok_or(RowWalkError::Source(StoreError::Capacity))?;
                logical_bytes = logical_bytes
                    .checked_add(
                        u64::try_from(key.key.len() + value.len() + 1)
                            .map_err(|_| RowWalkError::Source(StoreError::Capacity))?,
                    )
                    .ok_or(RowWalkError::Source(StoreError::Capacity))?;
                if rows > SNAPSHOT_ROWS || logical_bytes > SNAPSHOT_LOGICAL_BYTES {
                    return Err(RowWalkError::Source(StoreError::Capacity));
                }
                let header = row_header(&key, &value).map_err(RowWalkError::Source)?;
                for bytes in [&header[..], &key.key, &value] {
                    rows_hash.update(bytes);
                }
                visit(&header, &key, &value).map_err(RowWalkError::Visit)?;
            }
            match page.resume {
                Some(next) => resume = Some(next),
                None => break,
            }
        }
    }
    Ok(RowSummary {
        rows,
        logical_bytes,
        digest: rows_hash.finalize().into(),
    })
}

/// Inspect the exact bounded stream before any staged destination is created.
/// Installed row codecs validate every row; full cross-row/payload closure must
/// additionally validate the staged view before recovery can become usable.
pub fn inspect_snapshot(
    input: &mut (impl Read + Seek),
    deadline: Instant,
    mut validate_row: impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError>,
) -> Result<SnapshotReceipt, StoreError> {
    input
        .seek(SeekFrom::Start(0))
        .map_err(|_| StoreError::Unavailable)?;
    let first = inspect_stream(input, deadline, &mut validate_row, None)?;
    // The manifest follows the row stream. A second bounded pass compares its
    // current history projections with the actual archived NSH rows, retaining
    // only the finite namespace roster rather than all historical row bodies.
    input
        .seek(SeekFrom::Start(0))
        .map_err(|_| StoreError::Unavailable)?;
    let second = inspect_stream(input, deadline, &mut validate_row, Some(&first.manifest))?;
    if first != second {
        return Err(StoreError::Corrupt);
    }
    Ok(second)
}

fn inspect_stream(
    input: &mut impl Read,
    deadline: Instant,
    validate_row: &mut impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError>,
    expected: Option<&SnapshotManifest>,
) -> Result<SnapshotReceipt, StoreError> {
    validate_deadline(deadline)?;
    let mut histories = expected
        .map(|manifest| {
            manifest
                .namespaces
                .iter()
                .map(|snapshot| {
                    let (record, _) = snapshot.decode()?;
                    let key = crate::namespace::history::history_key(
                        &record.tenant,
                        &record.id,
                        record.version.incarnation,
                    )
                    .map_err(|_| StoreError::Corrupt)?;
                    let legacy = NamespaceHistory::initial(&record)
                        .encode()
                        .map_err(|_| StoreError::Corrupt)?
                        == snapshot.history;
                    Ok((key, snapshot.history.as_slice(), false, legacy))
                })
                .collect::<Result<Vec<_>, StoreError>>()
        })
        .transpose()?
        .unwrap_or_default();
    let mut reader = SnapshotReader {
        input,
        hash: Sha256::new(),
        bytes: 0,
        deadline,
    };
    if reader.read(MAGIC.len())? != MAGIC {
        return Err(StoreError::UnsupportedFormat);
    }
    let mut rows = 0u64;
    let mut logical_bytes = 0u64;
    let mut rows_hash = Sha256::new();
    let mut previous = None::<(Family, Vec<u8>)>;
    let mut namespaces = Vec::new();
    let mut source_store_identity = None;
    loop {
        let tag = reader.read(1)?[0];
        if tag == 0 {
            break;
        }
        if tag != 1 {
            return Err(StoreError::Corrupt);
        }
        let rest = reader.read(7)?;
        let family = FAMILIES
            .iter()
            .copied()
            .find(|family| *family as u8 == rest[0])
            .ok_or(StoreError::UnsupportedFormat)?;
        let key_bytes = usize::from(u16::from_le_bytes(
            rest[1..3].try_into().map_err(|_| StoreError::Corrupt)?,
        ));
        let value_bytes = usize::try_from(u32::from_le_bytes(
            rest[3..7].try_into().map_err(|_| StoreError::Corrupt)?,
        ))
        .map_err(|_| StoreError::Capacity)?;
        if key_bytes == 0 || key_bytes > 4096 || value_bytes > 4 * 1024 * 1024 {
            return Err(StoreError::Capacity);
        }
        rows = rows.checked_add(1).ok_or(StoreError::Capacity)?;
        logical_bytes = logical_bytes
            .checked_add(
                u64::try_from(key_bytes + value_bytes + 1).map_err(|_| StoreError::Capacity)?,
            )
            .ok_or(StoreError::Capacity)?;
        if rows > SNAPSHOT_ROWS || logical_bytes > SNAPSHOT_LOGICAL_BYTES {
            return Err(StoreError::Capacity);
        }
        let key = RowKey {
            family,
            key: reader.read(key_bytes)?,
        };
        if previous
            .as_ref()
            .is_some_and(|prior| (prior.0, prior.1.as_slice()) >= (family, key.key.as_slice()))
        {
            return Err(StoreError::Corrupt);
        }
        let value = reader.read(value_bytes)?;
        validate_row(&key, &value)?;
        if let Some((_, expected_bytes, observed, _)) = histories
            .iter_mut()
            .find(|(expected_key, _, _, _)| *expected_key == key)
        {
            NamespaceHistory::validate_row(&key, &value).map_err(|_| StoreError::Corrupt)?;
            if value != *expected_bytes {
                return Err(StoreError::Corrupt);
            }
            *observed = true;
        }
        if key == crate::store_identity::StoreIdentity::row_key() {
            crate::store_identity::StoreIdentity::validate_row(&key, &value)?;
            source_store_identity = Some(value.clone());
        }
        if family == Family::Namespace && key.key.starts_with(b"ns-v1\0") {
            if namespaces.len() == SNAPSHOT_NAMESPACES {
                return Err(StoreError::Capacity);
            }
            NamespaceCatalog::validate_row(&key, &value).map_err(|_| StoreError::Corrupt)?;
            namespaces.push(value.clone());
        }
        rows_hash.update([1]);
        rows_hash.update(&rest);
        rows_hash.update(&key.key);
        rows_hash.update(&value);
        previous = Some((family, key.key));
    }
    if histories
        .iter()
        .any(|(_, _, observed, legacy)| !observed && !legacy)
    {
        return Err(StoreError::Corrupt);
    }
    reader.finish(
        rows,
        logical_bytes,
        rows_hash.finalize().into(),
        &namespaces,
        source_store_identity.as_deref(),
    )
}

fn require_schema_artifacts(
    metadata: &SnapshotMetadata,
    namespaces: &[NamespaceSnapshot],
) -> Result<(), StoreError> {
    for namespace in namespaces {
        let (record, _) = namespace.decode()?;
        let artifact = metadata
            .required_artifacts
            .iter()
            .find(|artifact| artifact.identity == record.state_schema)
            .ok_or(StoreError::Corrupt)?;
        let mut identity = String::from("sha256:");
        for byte in artifact.digest {
            write!(&mut identity, "{byte:02x}").expect("writing bounded String");
        }
        if identity != record.state_schema {
            return Err(StoreError::Corrupt);
        }
    }
    Ok(())
}

pub(super) fn capture_namespaces(view: &ReadView) -> Result<Vec<NamespaceSnapshot>, StoreError> {
    capture_namespace_rows(view, true)
}

fn capture_namespace_rows(
    view: &ReadView,
    require_quiesced: bool,
) -> Result<Vec<NamespaceSnapshot>, StoreError> {
    let page = view.scan_after(
        Family::Namespace,
        b"ns-v1\0",
        None,
        SNAPSHOT_NAMESPACES,
        1024 * 1024,
    )?;
    if page.resume.is_some() || page.rows.is_empty() {
        return Err(StoreError::Capacity);
    }
    let mut snapshots = Vec::with_capacity(page.rows.len());
    for (key, bytes) in page.rows {
        NamespaceCatalog::validate_row(&key, &bytes).map_err(|_| StoreError::Corrupt)?;
        let record = NamespaceRecord::decode(&bytes).map_err(|_| StoreError::Corrupt)?;
        if require_quiesced && record.status == NamespaceStatus::Active {
            return Err(StoreError::Conflict);
        }
        let (history, _) = NamespaceHistory::capture(view, &record)?;
        snapshots.push(NamespaceSnapshot {
            record: bytes,
            history: history.encode().map_err(|_| StoreError::Corrupt)?,
        });
    }
    Ok(snapshots)
}

pub(super) fn row_header(key: &RowKey, value: &[u8]) -> Result<[u8; 8], StoreError> {
    if key.key.is_empty() || key.key.len() > 4096 || value.len() > 4 * 1024 * 1024 {
        return Err(StoreError::Capacity);
    }
    let mut header = [0u8; 8];
    header[0] = 1;
    header[1] = key.family as u8;
    header[2..4].copy_from_slice(
        &u16::try_from(key.key.len())
            .map_err(|_| StoreError::Capacity)?
            .to_le_bytes(),
    );
    header[4..8].copy_from_slice(
        &u32::try_from(value.len())
            .map_err(|_| StoreError::Capacity)?
            .to_le_bytes(),
    );
    Ok(header)
}

pub(super) fn checkpoint(deadline: Instant) -> Result<(), StoreError> {
    if Instant::now() >= deadline {
        return Err(StoreError::SnapshotExpired);
    }
    Ok(())
}

pub(super) fn validate_deadline(deadline: Instant) -> Result<(), StoreError> {
    checkpoint(deadline)?;
    if deadline.saturating_duration_since(Instant::now()) > SNAPSHOT_DURATION {
        return Err(StoreError::Capacity);
    }
    Ok(())
}

struct SnapshotWriter<'a, W> {
    output: &'a mut W,
    hash: Sha256,
    bytes: u64,
    deadline: Instant,
}

struct SnapshotReader<'a, R> {
    input: &'a mut R,
    hash: Sha256,
    bytes: u64,
    deadline: Instant,
}
impl<R: Read> SnapshotReader<'_, R> {
    fn finish(
        mut self,
        rows: u64,
        logical_bytes: u64,
        rows_digest: [u8; 32],
        namespaces: &[Vec<u8>],
        source_store_identity: Option<&[u8]>,
    ) -> Result<SnapshotReceipt, StoreError> {
        let manifest_bytes = usize::try_from(u32::from_le_bytes(
            self.read(4)?.try_into().map_err(|_| StoreError::Corrupt)?,
        ))
        .map_err(|_| StoreError::Capacity)?;
        if manifest_bytes == 0 || manifest_bytes > MANIFEST_BYTES {
            return Err(StoreError::Capacity);
        }
        let encoded = self.read(manifest_bytes)?;
        let manifest = SnapshotManifest::decode(&encoded)?;
        let manifest_digest: [u8; 32] = Sha256::digest(&encoded).into();
        if self.read(32)? != manifest_digest
            || manifest.rows != rows
            || manifest.logical_bytes != logical_bytes
            || manifest.rows_digest != rows_digest
            || source_store_identity != Some(manifest.source_store_identity.as_slice())
            || namespaces.iter().ne(manifest
                .namespaces
                .iter()
                .map(|namespace| &namespace.record))
        {
            return Err(StoreError::Corrupt);
        }
        checkpoint(self.deadline)?;
        let mut tail = [0u8; 1];
        if self
            .input
            .read(&mut tail)
            .map_err(|_| StoreError::Unavailable)?
            != 0
        {
            return Err(StoreError::Corrupt);
        }
        Ok(SnapshotReceipt {
            snapshot_digest: self.hash.finalize().into(),
            manifest_digest,
            file_bytes: self.bytes,
            manifest,
        })
    }

    fn read(&mut self, length: usize) -> Result<Vec<u8>, StoreError> {
        checkpoint(self.deadline)?;
        if length > 4 * 1024 * 1024 {
            return Err(StoreError::Capacity);
        }
        let next = self
            .bytes
            .checked_add(u64::try_from(length).map_err(|_| StoreError::Capacity)?)
            .ok_or(StoreError::Capacity)?;
        if next > SNAPSHOT_FILE_BYTES {
            return Err(StoreError::Capacity);
        }
        let mut bytes = vec![0u8; length];
        self.input
            .read_exact(&mut bytes)
            .map_err(|_| StoreError::Corrupt)?;
        self.hash.update(&bytes);
        self.bytes = next;
        Ok(bytes)
    }
}
impl<W: Write> SnapshotWriter<'_, W> {
    fn write(&mut self, bytes: &[u8]) -> Result<(), SnapshotError> {
        checkpoint(self.deadline).map_err(SnapshotError::source)?;
        let next = self
            .bytes
            .checked_add(u64::try_from(bytes.len()).map_err(|_| SnapshotError::Capacity)?)
            .ok_or(SnapshotError::Capacity)?;
        if next > SNAPSHOT_FILE_BYTES {
            return Err(SnapshotError::Capacity);
        }
        self.output
            .write_all(bytes)
            .map_err(|_| SnapshotError::Output)?;
        self.hash.update(bytes);
        self.bytes = next;
        Ok(())
    }
}

#[cfg(test)]
pub(super) mod tests;

mod limits;
