//! Explicit bounded offline migration. The legacy reader's `LIFECYCLE_MODE` check
//! is the initial durable fence; the intent itself contains the recovery identity.

use super::*;
use crate::{
    lifecycle::{LegacyLifecycleSnapshot, LifecycleIdentity},
    AdmissionAuthority, AdmissionStorageLimits, LifecycleLimits,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const NAMESPACE: &str = ".publication-migration";
const MARKER: &str = "LIFECYCLE_MODE";
const LEGACY_MARKER: &[u8] = b"lsf-release-lifecycle-v1\n";
const MAX_CONTROL_BYTES: usize = 16 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CatalogMigrationLimits {
    pub batch_size: usize,
    pub max_metadata_bytes: usize,
    pub max_disk_bytes: u64,
    pub max_files: usize,
    pub max_work_bytes: u64,
}
impl Default for CatalogMigrationLimits {
    fn default() -> Self {
        Self {
            batch_size: 32,
            max_metadata_bytes: 256 * 1024 * 1024,
            max_disk_bytes: 8 * 1024 * 1024 * 1024,
            max_files: 1_000_000,
            max_work_bytes: 64 * 1024 * 1024 * 1024,
        }
    }
}
impl CatalogMigrationLimits {
    fn validate(self) -> Result<(), PlatformError> {
        if self.batch_size == 0
            || self.batch_size > 1024
            || self.max_metadata_bytes == 0
            || self.max_metadata_bytes > 1024 * 1024 * 1024
            || self.max_disk_bytes == 0
            || self.max_files == 0
            || self.max_files > 1_000_000
            || self.max_work_bytes == 0
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-catalog-migration-limits",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CatalogMigrationReceipt {
    pub format_version: u32,
    pub source_digest: String,
    pub publications: usize,
    pub retained_operations: usize,
    pub previous_format: u32,
    pub current_format: u32,
}

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Fence {
    format_version: u32,
    kind: String,
    source: [u8; 32],
    configuration: [u8; 32],
    rows: usize,
    receipts: usize,
    limits: CatalogMigrationLimits,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Progress {
    format_version: u32,
    source: [u8; 32],
    rows: usize,
    receipts: usize,
}
#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Association {
    format_version: u32,
    publication: crate::PublicationRef,
    legacy: LifecycleIdentity,
}

/// Call before temporary cleanup or index rebuild. An old root is never
/// implicitly bootstrapped into a new set of positive lifecycle grants.
pub(super) fn check_current_format(root: &Path) -> Result<(), PlatformError> {
    if let Some(marker) = optional(&root.join(MARKER), MAX_CONTROL_BYTES)? {
        if marker != LEGACY_MARKER {
            return Err(required("catalog-migration-in-progress"));
        }
        let mode = optional(&root.join("lifecycle/MODE"), 4096)?
            .ok_or_else(|| corrupt("catalog-lifecycle-history-missing"))?;
        if format_version(&mode)? != 2 {
            return Err(required("catalog-migration-required"));
        }
        return Ok(());
    }
    if let Some(mode) = optional(&root.join("lifecycle/MODE"), 4096)? {
        if format_version(&mode)? != 2 {
            return Err(required("catalog-migration-required"));
        }
    } else if root.join("lifecycle/INITIALIZED").exists() || root.join("lifecycle/HEAD").exists() {
        return Err(corrupt("catalog-lifecycle-history-missing"));
    }
    if root.join("releases").exists()
        && fs::read_dir(root.join("releases"))
            .map_err(io_error)?
            .next()
            .is_some()
    {
        return Err(required("catalog-migration-required"));
    }
    Ok(())
}

impl DirectoryArtifactRepository {
    /// Only deployment/rollout recovery may consult the immutable v1 association.
    /// Ordinary legacy requests still require a unique current scoped mapping.
    pub(crate) fn recover_execution_publication(
        &self,
        tenant: &latent_core::TenantId,
        component: &ReleaseDigest,
    ) -> Result<crate::PublicationRef, PlatformError> {
        crate::publication::validate_component(component)?;
        let path = self
            .root
            .join(NAMESPACE)
            .join("associations")
            .join(format!("{}.json", &component.0[7..]));
        if let Some(bytes) = optional(&path, 4096)? {
            let mapping: Association = decode(&bytes)?;
            if mapping.format_version != 1
                || mapping.legacy.release != *component
                || mapping.legacy.publication()? != mapping.publication
            {
                return Err(corrupt("catalog-migration-legacy-association"));
            }
            let selected = self.select_execution_publication(
                tenant,
                component,
                Some(&mapping.publication.id),
            )?;
            if selected != mapping.publication {
                return Err(corrupt("catalog-migration-legacy-association"));
            }
            return Ok(selected);
        }
        self.select_execution_publication(tenant, component, None)
    }

    pub fn migrate_catalog(
        root: impl Into<PathBuf>,
        config: DirectoryArtifactRepositoryConfig,
        lifecycle: LifecycleLimits,
        limits: CatalogMigrationLimits,
    ) -> Result<CatalogMigrationReceipt, PlatformError> {
        let repository = Self::acquire_configured(root.into(), config, None, lifecycle)?;
        repository.migrate_owned(limits)
    }

    pub fn migrate_enforced_catalog(
        root: impl Into<PathBuf>,
        config: DirectoryArtifactRepositoryConfig,
        admission_limits: AdmissionStorageLimits,
        authority: Arc<dyn AdmissionAuthority>,
        lifecycle: LifecycleLimits,
        limits: CatalogMigrationLimits,
    ) -> Result<CatalogMigrationReceipt, PlatformError> {
        admission_limits.validate()?;
        let repository = Self::acquire_configured(
            root.into(),
            config,
            Some(admission::RepositoryAdmission::new(
                authority,
                admission_limits,
            )),
            lifecycle,
        )?;
        repository.migrate_owned(limits)
    }

    fn migrate_owned(
        &self,
        limits: CatalogMigrationLimits,
    ) -> Result<CatalogMigrationReceipt, PlatformError> {
        limits.validate()?;
        let work = self.root.join(NAMESPACE);
        if fs::symlink_metadata(&work).is_ok() {
            shared_content::directory(&work)?;
        }
        let receipt_path = work.join("receipt.json");
        let marker = optional(&self.root.join(MARKER), MAX_CONTROL_BYTES)?
            .ok_or_else(|| required("catalog-legacy-history-required"))?;
        if marker == LEGACY_MARKER
            && self.root.join("lifecycle/MODE").is_file()
            && format_version(&read_bounded_file(
                &self.root.join("lifecycle/MODE"),
                4096,
                "lifecycle mode",
            )?)? == 2
        {
            let receipt: CatalogMigrationReceipt = decode(
                &optional(&receipt_path, MAX_CONTROL_BYTES)?
                    .ok_or_else(|| required("catalog-is-already-format-two"))?,
            )?;
            if receipt.format_version != 1
                || receipt.previous_format != 1
                || receipt.current_format != 2
            {
                return Err(corrupt("catalog-migration-receipt"));
            }
            check_current_format(&self.root)?;
            self.content.lock().map_err(lock_error)?.open()?;
            let baseline = self.rebuild_index()?;
            self.initialize_lifecycle(&baseline)?;
            return Ok(receipt);
        }
        let old_fence = if marker == LEGACY_MARKER {
            None
        } else {
            Some(decode::<Fence>(&marker)?)
        };
        if old_fence.as_ref().is_some_and(|f| {
            f.format_version != 1 || f.kind != "publication-migration" || f.limits != limits
        }) {
            return Err(required("catalog-migration-use-original-limits"));
        }
        let source_root = if work.join("legacy-lifecycle").exists() {
            work.join("legacy-lifecycle")
        } else {
            self.root.join("lifecycle")
        };
        let (baseline, source_bytes, file_count) = self.legacy_baseline(limits)?;
        shared_content::directory(&source_root)?;
        let source_limits = LifecycleLimits {
            max_records: self
                .lifecycle_limits
                .max_records
                .min(limits.max_metadata_bytes / 8192),
            max_total_metadata_bytes: self
                .lifecycle_limits
                .max_total_metadata_bytes
                .min(limits.max_metadata_bytes / 2),
            ..self.lifecycle_limits
        };
        source_limits.validate()?;
        let source = LegacyLifecycleSnapshot::open(
            &source_root,
            source_limits,
            self.admission.is_some(),
            &baseline,
        )?;
        let plan: Vec<_> = source.identities().cloned().collect();
        let mappings = plan.len().checked_mul(4096).ok_or_else(limit)?;
        let memory = source
            .retained_bytes()?
            .checked_add(mappings)
            .and_then(|n| n.checked_add(baseline.len().checked_mul(2048)?))
            .ok_or_else(limit)?;
        if memory > limits.max_metadata_bytes {
            return Err(limit());
        }
        let (historical_bytes, historical_files) = tree_bytes(
            &source_root,
            limits.max_files.saturating_sub(file_count),
            limits.max_disk_bytes,
            limits.max_metadata_bytes,
        )?;
        let destination_files = file_count
            .checked_mul(3)
            .and_then(|n| n.checked_add(historical_files.checked_mul(2)?))
            .and_then(|n| n.checked_add(plan.len().checked_mul(2)?))
            .and_then(|n| n.checked_add(32))
            .ok_or_else(limit)?;
        if destination_files > limits.max_files {
            return Err(limit());
        }
        // Includes original immutable/history retention, new metadata/evidence,
        // logical publication links and the worst case of unique shared blobs.
        let disk = source_bytes
            .checked_mul(3)
            .and_then(|n| n.checked_add(historical_bytes.checked_mul(2)?))
            .and_then(|n| n.checked_add(mappings as u64))
            .and_then(|n| n.checked_add(64 * 1024))
            .ok_or_else(limit)?;
        if disk > limits.max_disk_bytes
            || disk
                .checked_mul(6)
                .is_none_or(|n| n > limits.max_work_bytes)
        {
            return Err(limit());
        }
        self.preflight_migration_destination(&plan, memory, limits)?;
        let fence = Fence {
            format_version: 1,
            kind: "publication-migration".into(),
            source: source.fingerprint(),
            configuration: self.migration_configuration(),
            rows: source.len(),
            receipts: source.receipts(),
            limits,
        };
        if old_fence.as_ref().is_some_and(|old| old != &fence) {
            return Err(required(
                "catalog-migration-source-or-configuration-changed",
            ));
        }
        if old_fence.is_none() {
            if work.exists()
                || self.root.join(RELEASES_DIR).exists()
                || self.root.join("blobs").exists()
            {
                return Err(corrupt("unfenced-publication-migration-state"));
            }
            // Old startup reads at most 64 bytes and expects LEGACY_MARKER.
            // This atomic intent is itself the checked downgrade fence.
            atomic_write(&self.root.join(MARKER), &encode(&fence)?)?;
            fault(1)?;
        }
        fs::create_dir_all(&work).map_err(io_error)?;
        shared_content::directory(&work)?;
        for path in [
            self.root.join(RELEASES_DIR),
            self.root.join(TEMP_DIR),
            work.join("associations"),
        ] {
            fs::create_dir_all(&path).map_err(io_error)?;
            shared_content::directory(&path)?;
        }
        sync_dir(&work)?;
        sync_dir(&self.root)?;
        self.content.lock().map_err(lock_error)?.open()?;
        let mut progress = optional(&work.join("PROGRESS"), MAX_CONTROL_BYTES)?
            .map(|bytes| decode::<Progress>(&bytes))
            .transpose()?
            .unwrap_or(Progress {
                format_version: 1,
                source: source.fingerprint(),
                rows: 0,
                receipts: 0,
            });
        if progress.format_version != 1
            || progress.source != source.fingerprint()
            || progress.rows > plan.len()
            || progress.receipts > source.receipts()
        {
            return Err(corrupt("catalog-migration-progress"));
        }
        let target = if source_root == work.join("legacy-lifecycle")
            && self.root.join("lifecycle").exists()
        {
            self.root.join("lifecycle")
        } else {
            work.join("new-lifecycle")
        };
        source.begin(&target)?;
        // Recover references for already completed batches before reserving more.
        for identity in plan.iter().take(progress.rows) {
            let reference = identity.publication()?;
            self.content
                .lock()
                .map_err(lock_error)?
                .register_directory(&reference.id, &self.publication_path(&reference.id))?;
        }
        while progress.rows < plan.len() {
            let end = (progress.rows + limits.batch_size).min(plan.len());
            for identity in &plan[progress.rows..end] {
                self.migrate_publication(identity, &work)?;
            }
            source.stage_rows(&target, progress.rows, end - progress.rows)?;
            fault(2)?;
            progress.rows = end;
            atomic_write(&work.join("PROGRESS"), &encode(&progress)?)?;
            fault(3)?;
        }
        while progress.receipts < source.receipts() {
            let end = (progress.receipts + limits.batch_size).min(source.receipts());
            source.stage_receipts(&target, progress.receipts, end - progress.receipts)?;
            fault(4)?;
            progress.receipts = end;
            atomic_write(&work.join("PROGRESS"), &encode(&progress)?)?;
        }
        source.finish(&target)?;
        for identity in &plan {
            let reference = identity.publication()?;
            let path = self.publication_path(&reference.id);
            let verified = self.load_complete_entry(&path, Retention::Metadata)?;
            if verified.publication != reference
                || verified.completion.identity()? != identity.completion
            {
                return Err(corrupt("catalog-migration-final-association"));
            }
            let mapping: Association = decode(&read_bounded_file(
                &work
                    .join("associations")
                    .join(format!("{}.json", &identity.release.0[7..])),
                4096,
                "legacy association",
            )?)?;
            if mapping.format_version != 1
                || mapping.publication != reference
                || mapping.legacy != *identity
            {
                return Err(corrupt("catalog-migration-legacy-association"));
            }
        }
        fault(5)?;
        if !work.join("legacy-lifecycle").exists() {
            fs::rename(self.root.join("lifecycle"), work.join("legacy-lifecycle"))
                .map_err(io_error)?;
            sync_dir(&self.root)?;
            sync_dir(&work)?;
        }
        fault(6)?;
        if target != self.root.join("lifecycle") {
            fs::rename(&target, self.root.join("lifecycle")).map_err(io_error)?;
            sync_dir(&self.root)?;
            sync_dir(&work)?;
        }
        fault(7)?;
        let receipt = CatalogMigrationReceipt {
            format_version: 1,
            source_digest: format!("sha256:{}", hex(&source.fingerprint())),
            publications: source.len(),
            retained_operations: source.receipts(),
            previous_format: 1,
            current_format: 2,
        };
        exact_write(&receipt_path, &encode(&receipt)?)?;
        atomic_write(&self.root.join(MARKER), LEGACY_MARKER)?;
        fault(8)?;
        Ok(receipt)
    }

    fn legacy_baseline(
        &self,
        limits: CatalogMigrationLimits,
    ) -> Result<(Vec<LifecycleIdentity>, u64, usize), PlatformError> {
        let root = self.root.join("releases");
        shared_content::directory(&root)?;
        let mut paths = Vec::new();
        let mut bytes = 0u64;
        let mut files = 0usize;
        for entry in fs::read_dir(&root).map_err(io_error)? {
            let entry = entry.map_err(io_error)?;
            if paths.len() >= self.config.max_recovery_directories.min(limits.max_files) {
                return Err(limit());
            }
            let path = entry.path();
            shared_content::directory(&path)?;
            if (paths.len() + 1)
                .checked_mul(8192)
                .is_none_or(|n| n > limits.max_metadata_bytes)
            {
                return Err(limit());
            }
            let entries = shared_content::bounded_files(&path, self.config)?;
            files = files
                .checked_add(entries.len())
                .filter(|n| *n <= limits.max_files)
                .ok_or_else(limit)?;
            for (_, size) in entries {
                bytes = bytes
                    .checked_add(size)
                    .filter(|n| *n <= limits.max_disk_bytes)
                    .ok_or_else(limit)?;
            }
            paths.push(path);
        }
        if bytes
            .checked_mul(6)
            .is_none_or(|n| n > limits.max_work_bytes)
        {
            return Err(limit());
        }
        paths.sort();
        let mut baseline = Vec::new();
        for path in paths {
            if !is_recovery_candidate(&path)? {
                continue;
            }
            if baseline.len()
                >= self
                    .config
                    .max_index_entries
                    .min(self.lifecycle_limits.max_records)
                || (baseline.len() + 1)
                    .checked_mul(2048)
                    .is_none_or(|n| n > limits.max_metadata_bytes)
            {
                return Err(limit());
            }
            let verified = self.load_complete_entry_at_format(
                &path,
                Retention::Metadata,
                self.repository_read_limits(),
                true,
            )?;
            let package = if let Some(stored) = &verified.admission {
                let config = self.admission.as_ref().expect("enforced legacy data");
                let binding = stored.binding(&path, config.limits)?;
                stored.verify_original_association(&verified.metadata)?;
                Some(binding.package)
            } else {
                None
            };
            baseline.push(LifecycleIdentity {
                scope: verified.publication.scope,
                release: verified.metadata.verified_digest().clone(),
                package,
                completion: verified.completion.identity()?,
            });
        }
        Ok((baseline, bytes, files))
    }

    fn migrate_publication(
        &self,
        identity: &LifecycleIdentity,
        work: &Path,
    ) -> Result<(), PlatformError> {
        let reference = identity.publication()?;
        let source = self
            .root
            .join("releases")
            .join(digest_hex(&identity.release)?);
        let target = self.publication_path(&reference.id);
        if !target.exists() {
            let stage = work.join(format!("publication-{}", reference.id.hex()));
            fs::create_dir_all(&stage).map_err(io_error)?;
            shared_content::directory(&stage)?;
            let files = shared_content::bounded_files(&source, self.config)?;
            let mut content = self.content.lock().map_err(lock_error)?;
            content.preflight_existing(&reference.id, &source, &files)?;
            for (name, _) in files {
                content.link_existing(&source.join(&name), &stage.join(name))?;
            }
            sync_dir(&stage)?;
            fs::rename(&stage, &target).map_err(io_error)?;
            sync_dir(&self.root.join(RELEASES_DIR))?;
        }
        let verified = self.load_complete_entry(&target, Retention::Metadata)?;
        if verified.publication != reference
            || verified.completion.identity()? != identity.completion
        {
            return Err(corrupt("catalog-migration-publication"));
        }
        self.content
            .lock()
            .map_err(lock_error)?
            .register_directory(&reference.id, &target)?;
        let mapping = Association {
            format_version: 1,
            publication: reference,
            legacy: identity.clone(),
        };
        exact_write(
            &work
                .join("associations")
                .join(format!("{}.json", digest_hex(&identity.release)?)),
            &encode(&mapping)?,
        )
    }

    fn preflight_migration_destination(
        &self,
        plan: &[LifecycleIdentity],
        retained: usize,
        limits: CatalogMigrationLimits,
    ) -> Result<(), PlatformError> {
        let mut index = CatalogIndex::default();
        let mut content = shared_content::SharedContent::new(&self.root, self.config);
        for identity in plan {
            let path = self
                .root
                .join("releases")
                .join(digest_hex(&identity.release)?);
            let verified = self.load_complete_entry_at_format(
                &path,
                Retention::Metadata,
                self.repository_read_limits(),
                true,
            )?;
            let reference = identity.publication()?;
            if verified.publication != reference
                || verified.completion.identity()? != identity.completion
            {
                return Err(corrupt("catalog-migration-source-association"));
            }
            if let Some(stored) = &verified.admission {
                let admission = self
                    .admission
                    .as_ref()
                    .ok_or_else(|| corrupt("catalog-migration-admission-mode"))?;
                let binding = stored.binding(&path, admission.limits)?;
                index.insert_admitted(
                    reference.clone(),
                    verified.metadata,
                    None,
                    binding,
                    None,
                    identity.completion,
                    self.config,
                )?;
                // Migration does not require a current grant for historical
                // content. Reserve the configured maximum future grant size.
                index.accounted_bytes = index
                    .accounted_bytes
                    .checked_add(admission.limits.max_grant_bytes)
                    .and_then(|n| {
                        n.checked_add(std::mem::size_of::<crate::ReleaseEligibility>() + 64)
                    })
                    .filter(|n| *n <= self.config.max_index_bytes)
                    .ok_or_else(limit)?;
            } else {
                index.insert_verified(reference.clone(), verified.metadata, None, self.config)?;
            }
            content.plan_directory(&reference.id, &path)?;
            if retained
                .checked_add(index.accounted_bytes)
                .and_then(|n| n.checked_add(content.snapshot().accounted_metadata_bytes))
                .is_none_or(|n| n > limits.max_metadata_bytes)
            {
                return Err(limit());
            }
        }
        Ok(())
    }

    fn migration_configuration(&self) -> [u8; 32] {
        let c = self.config;
        let l = self.lifecycle_limits;
        let mut hash = Sha256::new();
        hash.update(b"lsf-publication-migration-configuration-v1\0");
        hash.update([u8::from(self.admission.is_some())]);
        for value in [
            c.max_storage_bytes,
            c.max_content_index_bytes as u64,
            c.max_content_blobs as u64,
            c.max_publication_files as u64,
            c.max_index_entries as u64,
            c.max_index_bytes as u64,
            c.max_page_size as u64,
            c.max_page_bytes as u64,
            c.max_descriptor_bytes as u64,
            c.max_metadata_bytes as u64,
            c.max_component_bytes as u64,
            c.max_recovery_directories as u64,
            l.max_records as u64,
            l.max_record_bytes as u64,
            l.max_receipt_bytes as u64,
            l.max_recent_operations as u64,
            l.max_total_metadata_bytes as u64,
            l.max_intent_bytes as u64,
            l.max_evidence_revision_bytes as u64,
            l.max_total_evidence_bytes as u64,
        ] {
            hash.update(value.to_le_bytes());
        }
        if let Some(admission) = &self.admission {
            for value in [
                admission.limits.max_document_bytes,
                admission.limits.max_auxiliary_bytes,
                admission.limits.max_evidence_per_kind,
                admission.limits.max_grant_bytes,
            ] {
                hash.update((value as u64).to_le_bytes());
            }
        }
        hash.finalize().into()
    }
}

fn tree_bytes(
    path: &Path,
    maximum_files: usize,
    maximum_bytes: u64,
    maximum_metadata: usize,
) -> Result<(u64, usize), PlatformError> {
    let mut pending = vec![(path.to_owned(), 0usize)];
    let mut files = 0usize;
    let mut total = 0u64;
    while let Some((path, depth)) = pending.pop() {
        if depth > 3 {
            return Err(corrupt("legacy-lifecycle-directory-depth"));
        }
        shared_content::directory(&path)?;
        for entry in fs::read_dir(path).map_err(io_error)? {
            let entry = entry.map_err(io_error)?;
            files = files
                .checked_add(1)
                .filter(|n| *n <= maximum_files)
                .ok_or_else(limit)?;
            let metadata = entry.file_type().map_err(io_error)?;
            if metadata.is_dir() {
                if (pending.len() + 1)
                    .checked_mul(4096)
                    .is_none_or(|n| n > maximum_metadata)
                {
                    return Err(limit());
                }
                pending.push((entry.path(), depth + 1));
            } else if metadata.is_file() {
                total = total
                    .checked_add(shared_content::regular(&entry.path())?.len())
                    .filter(|n| *n <= maximum_bytes)
                    .ok_or_else(limit)?;
            } else {
                return Err(corrupt("legacy-lifecycle-file-type"));
            }
        }
    }
    Ok((total, files))
}
fn format_version(bytes: &[u8]) -> Result<u64, PlatformError> {
    let value: serde_json::Value =
        serde_json::from_slice(bytes).map_err(|_| corrupt("catalog-format-marker"))?;
    value
        .get("formatVersion")
        .and_then(serde_json::Value::as_u64)
        .ok_or_else(|| corrupt("catalog-format-marker"))
}
fn optional(path: &Path, maximum: usize) -> Result<Option<Vec<u8>>, PlatformError> {
    match fs::symlink_metadata(path) {
        Ok(_) => read_bounded_file(path, maximum, "catalog migration record").map(Some),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(io_error(e)),
    }
}
fn encode<T: Serialize>(value: &T) -> Result<Vec<u8>, PlatformError> {
    let bytes = serde_json::to_vec(value).map_err(|_| corrupt("catalog-migration-encoding"))?;
    if bytes.len() > MAX_CONTROL_BYTES {
        return Err(limit());
    }
    Ok(bytes)
}
fn decode<T: serde::de::DeserializeOwned + Serialize>(bytes: &[u8]) -> Result<T, PlatformError> {
    let value = serde_json::from_slice(bytes).map_err(|_| corrupt("catalog-migration-record"))?;
    if encode(&value)? != bytes {
        return Err(corrupt("catalog-migration-noncanonical-record"));
    }
    Ok(value)
}
fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), PlatformError> {
    let temporary = path.with_extension("migration-next");
    if let Some(old) = optional(&temporary, MAX_CONTROL_BYTES)? {
        drop(old);
        fs::remove_file(&temporary).map_err(io_error)?;
    }
    write_synced(&temporary, bytes)?;
    fs::rename(&temporary, path).map_err(io_error)?;
    sync_dir(path.parent().expect("catalog migration parent"))
}
fn exact_write(path: &Path, bytes: &[u8]) -> Result<(), PlatformError> {
    if let Some(old) = optional(path, MAX_CONTROL_BYTES)? {
        if old != bytes {
            return Err(corrupt("catalog-migration-file-conflict"));
        }
        return Ok(());
    }
    atomic_write(path, bytes)
}
fn required(reason: &'static str) -> PlatformError {
    error(PlatformErrorCode::Unavailable, format!("{reason}; stop the node and run the offline catalog migration with its original configuration"))
}
fn limit() -> PlatformError {
    resource_exhausted("catalog-migration-resource-limit")
}
fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8] = b"0123456789abcdef";
    let mut result = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        result.push(char::from(DIGITS[usize::from(byte >> 4)]));
        result.push(char::from(DIGITS[usize::from(byte & 15)]));
    }
    result
}
#[cfg(test)]
thread_local! { static FAIL: std::cell::Cell<u8> = const { std::cell::Cell::new(0) }; }
#[cfg(all(test, unix))]
pub(super) fn interrupt_at(point: u8) {
    FAIL.with(|fail| fail.set(point));
}
fn fault(point: u8) -> Result<(), PlatformError> {
    #[cfg(test)]
    if FAIL.with(|fail| {
        if fail.get() == point {
            fail.set(0);
            true
        } else {
            false
        }
    }) {
        return Err(required("injected-migration-interruption"));
    }
    let _ = point;
    Ok(())
}
