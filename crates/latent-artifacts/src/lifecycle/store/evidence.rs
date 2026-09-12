use super::*;
use crate::{AdmissionBinding, AdmissionEvidence, AdmissionStorageLimits};

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Blob {
    digest: [u8; 32],
    size: usize,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Revision {
    format_version: u32,
    identity: LifecycleIdentity,
    files: Vec<Blob>,
    signatures: usize,
    provenance: usize,
    sboms: usize,
}
/// Fully bounded exact raw material; preparation performs no filesystem writes.
pub(crate) struct LifecycleEvidence {
    revision: Revision,
    record: Vec<u8>,
    files: Vec<Vec<u8>>,
    digest: ArtifactBlobDigest,
    total: usize,
}
impl LifecycleEvidence {
    pub(crate) fn prepare(
        identity: &LifecycleIdentity,
        binding: &AdmissionBinding,
        evidence: ReleaseEvidenceUpload,
        limits: LifecycleLimits,
    ) -> Result<Self, PlatformError> {
        limits.validate()?;
        validation::identity(identity, true)?;
        AdmissionStorageLimits::default().check_binding(binding)?;
        if identity.scope.tenant() != Some(&binding.tenant)
            || identity.release != binding.release
            || identity.package.as_ref() != Some(&binding.package)
        {
            return Err(invalid());
        }
        let counts = [
            evidence.signatures.len(),
            evidence.provenance.len(),
            evidence.sboms.len(),
        ];
        let mut total = binding.receipt.capacity();
        let mut files = vec![binding.receipt.clone()];
        for entries in [evidence.signatures, evidence.provenance, evidence.sboms] {
            if entries.len() > 8 || entries.capacity() > 8 {
                return Err(exhausted());
            }
            for entry in entries {
                if entry.manifest.capacity() > 256 * 1024
                    || entry.configuration.capacity() > 256 * 1024
                {
                    return Err(exhausted());
                }
                for bytes in [entry.manifest, entry.configuration, entry.payload] {
                    total = total.checked_add(bytes.capacity()).ok_or_else(exhausted)?;
                    if total > limits.max_evidence_revision_bytes {
                        return Err(exhausted());
                    }
                    files.push(bytes);
                }
            }
        }
        let revision = Revision {
            format_version: 1,
            identity: identity.clone(),
            files: files
                .iter()
                .map(|bytes| Blob {
                    digest: digest(bytes),
                    size: bytes.len(),
                })
                .collect(),
            signatures: counts[0],
            provenance: counts[1],
            sboms: counts[2],
        };
        let record = encode(&revision, 16 * 1024)?;
        total = total.checked_add(record.len()).ok_or_else(exhausted)?;
        if total > limits.max_evidence_revision_bytes {
            return Err(exhausted());
        }
        let digest = blob(&record);
        Ok(Self {
            revision,
            record,
            files,
            digest,
            total,
        })
    }
    pub(crate) fn digest(&self) -> &ArtifactBlobDigest {
        &self.digest
    }
}
#[derive(Default)]
pub(super) struct EvidenceState {
    total: usize,
    revisions: BTreeMap<ArtifactBlobDigest, (ReleaseDigest, usize)>,
    unreferenced: Option<ArtifactBlobDigest>,
}

impl LifecycleStore {
    pub(crate) fn stage_evidence(&self, prepared: &LifecycleEvidence) -> Result<(), PlatformError> {
        let _fence = self.owner.acquire()?;
        let state = self.state.try_lock().map_err(lock_error)?;
        let entry = state
            .entries
            .get(&prepared.revision.identity.release)
            .ok_or_else(invalid)?;
        if entry.stored.identity != prepared.revision.identity {
            return Err(invalid());
        }
        let mut evidence = self.evidence.try_lock().map_err(lock_error)?;
        if evidence.revisions.contains_key(&prepared.digest) {
            return Ok(());
        }
        if evidence.unreferenced.is_some() {
            return Err(exhausted());
        }
        let total = evidence
            .total
            .checked_add(prepared.total)
            .ok_or_else(exhausted)?;
        if total > self.limits.max_total_evidence_bytes {
            return Err(exhausted());
        }
        let base = self.root.join("evidence");
        let pending = base.join("PENDING");
        if pending.exists() {
            return Err(unavailable());
        }
        io::create_directory(&pending)?;
        // Record is first, so recovery can validate every existing partial file
        // before removing it. No arbitrary files or symlinks are swept.
        let result = (|| {
            io::write(&pending.join("revision.json"), &prepared.record)?;
            for (index, bytes) in prepared.files.iter().enumerate() {
                io::write(&pending.join(file_name(index)), bytes)?;
            }
            io::sync(&pending)?;
            let destination = revision_path(&self.root, &prepared.digest);
            if destination.exists() {
                return Err(corrupt());
            }
            std::fs::rename(&pending, &destination).map_err(|_| unavailable())?;
            io::sync(&base)?;
            Ok(())
        })();
        if result.is_err() {
            self.owner.poison();
            return result;
        }
        evidence.total = total;
        evidence.revisions.insert(
            prepared.digest.clone(),
            (prepared.revision.identity.release.clone(), prepared.total),
        );
        evidence.unreferenced = Some(prepared.digest.clone());
        Ok(())
    }
    pub(crate) fn read_evidence(
        &self,
        release: &ReleaseDigest,
    ) -> Result<Option<(AdmissionBinding, ReleaseEvidenceUpload)>, PlatformError> {
        self.owner.check()?;
        let state = self.state.try_lock().map_err(lock_error)?;
        let Some(entry) = state.entries.get(release) else {
            return Ok(None);
        };
        let Some(digest) = &entry.stored.record.evidence_revision_digest else {
            return Ok(None);
        };
        let _evidence = self.evidence.try_lock().map_err(lock_error)?;
        let (revision, files, _) =
            read_revision(&revision_path(&self.root, digest), self.limits, false)?;
        if revision.identity != entry.stored.identity {
            return Err(corrupt());
        }
        let mut files = files.into_iter();
        let binding = AdmissionBinding {
            tenant: revision
                .identity
                .scope
                .tenant()
                .ok_or_else(corrupt)?
                .clone(),
            package: revision.identity.package.ok_or_else(corrupt)?,
            release: revision.identity.release,
            receipt: files.next().ok_or_else(corrupt)?,
        };
        let mut group = |count| -> Result<Vec<AdmissionEvidence>, PlatformError> {
            let mut entries = Vec::new();
            entries.try_reserve_exact(count).map_err(|_| exhausted())?;
            for _ in 0..count {
                entries.push(AdmissionEvidence {
                    manifest: files.next().ok_or_else(corrupt)?,
                    configuration: files.next().ok_or_else(corrupt)?,
                    payload: files.next().ok_or_else(corrupt)?,
                });
            }
            Ok(entries)
        };
        let upload = ReleaseEvidenceUpload {
            signatures: group(revision.signatures)?,
            provenance: group(revision.provenance)?,
            sboms: group(revision.sboms)?,
        };
        Ok(Some((binding, upload)))
    }
    /// Only the one verified unreferenced candidate may be reclaimed. An old
    /// receipt is diagnostic history and does not pin obsolete raw evidence.
    pub(crate) fn reclaim_evidence(&self) -> Result<(), PlatformError> {
        let _fence = self.owner.acquire()?;
        let state = self.state.try_lock().map_err(lock_error)?;
        let mut evidence = self.evidence.try_lock().map_err(lock_error)?;
        let Some(digest) = evidence.unreferenced.clone() else {
            return Ok(());
        };
        let (release, size) = evidence
            .revisions
            .get(&digest)
            .cloned()
            .ok_or_else(corrupt)?;
        if state
            .entries
            .get(&release)
            .and_then(|entry| entry.stored.record.evidence_revision_digest.as_ref())
            == Some(&digest)
        {
            evidence.unreferenced = None;
            return Ok(());
        }
        remove_revision(&revision_path(&self.root, &digest), self.limits, true)?;
        evidence.total = evidence.total.checked_sub(size).ok_or_else(corrupt)?;
        evidence.revisions.remove(&digest);
        evidence.unreferenced = None;
        Ok(())
    }
    pub(super) fn recover_evidence(&self) -> Result<(), PlatformError> {
        let state = self.state.try_lock().map_err(lock_error)?;
        let mut evidence = EvidenceState::default();
        let mut references = BTreeMap::new();
        for entry in state.entries.values() {
            if let Some(digest) = &entry.stored.record.evidence_revision_digest {
                if references
                    .insert(digest.clone(), &entry.stored.identity)
                    .is_some()
                {
                    return Err(corrupt());
                }
            }
        }
        let base = self.root.join("evidence");
        for name in io::files(&base, self.limits.max_records + 2)? {
            if name == "PENDING" {
                remove_revision(&base.join(name), self.limits, true)?;
                continue;
            }
            let digest: ArtifactBlobDigest =
                format!("sha256:{name}").parse().map_err(|_| corrupt())?;
            let referenced = references.contains_key(&digest);
            if !referenced && io::files(&base.join(&name), 76)?.is_empty() {
                remove_revision(&base.join(&name), self.limits, true)?;
                continue;
            }
            let (revision, _, size) = read_revision(&base.join(&name), self.limits, !referenced)?;
            let row = state
                .entries
                .get(&revision.identity.release)
                .ok_or_else(corrupt)?;
            if row.stored.identity != revision.identity {
                return Err(corrupt());
            }
            if row.stored.record.evidence_revision_digest.as_ref() != Some(&digest) {
                if evidence.unreferenced.replace(digest.clone()).is_some() {
                    return Err(corrupt());
                }
            }
            evidence.total = evidence.total.checked_add(size).ok_or_else(exhausted)?;
            if evidence.total > self.limits.max_total_evidence_bytes {
                return Err(exhausted());
            }
            evidence
                .revisions
                .insert(digest, (revision.identity.release, size));
        }
        for entry in state.entries.values() {
            if let Some(digest) = &entry.stored.record.evidence_revision_digest {
                if evidence.revisions.get(digest).map(|(release, _)| release)
                    != Some(&entry.stored.identity.release)
                {
                    return Err(corrupt());
                }
            }
        }
        drop(state);
        *self.evidence.try_lock().map_err(lock_error)? = evidence;
        self.reclaim_evidence()
    }
    pub(super) fn evidence_cutover(
        &self,
        old: Option<&ArtifactBlobDigest>,
        new: Option<&ArtifactBlobDigest>,
    ) -> Result<(), PlatformError> {
        if old == new {
            return Ok(());
        }
        let mut evidence = self.evidence.try_lock().map_err(lock_error)?;
        if let Some(new) = new {
            if !evidence.revisions.contains_key(new) {
                return Err(corrupt());
            }
            if evidence.unreferenced.as_ref() != Some(new) {
                return Err(conflict());
            }
        }
        evidence.unreferenced = old.cloned();
        Ok(())
    }
    pub(super) fn check_evidence_cutover(
        &self,
        release: Option<&ReleaseDigest>,
        old: Option<&ArtifactBlobDigest>,
        new: Option<&ArtifactBlobDigest>,
    ) -> Result<(), PlatformError> {
        if old == new {
            return Ok(());
        }
        let evidence = self.evidence.try_lock().map_err(lock_error)?;
        let new = new.ok_or_else(invalid)?;
        if evidence.unreferenced.as_ref() != Some(new)
            || evidence.revisions.get(new).map(|(release, _)| release) != release
        {
            return Err(conflict());
        }
        Ok(())
    }
}
fn file_name(index: usize) -> String {
    format!("{index:03}.bin")
}
fn revision_path(root: &Path, digest: &ArtifactBlobDigest) -> PathBuf {
    root.join("evidence").join(&digest.as_str()[7..])
}
fn read_revision(
    path: &Path,
    limits: LifecycleLimits,
    partial: bool,
) -> Result<(Revision, Vec<Vec<u8>>, usize), PlatformError> {
    io::directory(path)?;
    let record = io::required(&path.join("revision.json"), 16 * 1024)?;
    if path.file_name().and_then(|name| name.to_str()) != Some("PENDING")
        && path.file_name().and_then(|name| name.to_str()) != Some(&blob(&record).as_str()[7..])
    {
        return Err(corrupt());
    }
    let revision: Revision = decode(&record, 16 * 1024)?;
    validation::identity(&revision.identity, true)?;
    if revision.format_version != 1
        || revision.signatures > 8
        || revision.provenance > 8
        || revision.sboms > 8
        || revision.files.len()
            != 1 + 3 * (revision.signatures + revision.provenance + revision.sboms)
    {
        return Err(corrupt());
    }
    let mut total = record.len();
    let mut files = Vec::new();
    for (index, descriptor) in revision.files.iter().enumerate() {
        total = total.checked_add(descriptor.size).ok_or_else(exhausted)?;
        if total > limits.max_evidence_revision_bytes {
            return Err(exhausted());
        }
        if index == 0 && descriptor.size > 16 * 1024 {
            return Err(exhausted());
        }
        let bytes = io::read(&path.join(file_name(index)), descriptor.size)?;
        match bytes {
            Some(bytes) => {
                if bytes.len() != descriptor.size || digest(&bytes) != descriptor.digest {
                    return Err(corrupt());
                }
                files.push(bytes);
            }
            None if partial => {}
            None => return Err(corrupt()),
        }
    }
    for name in io::files(path, revision.files.len() + 2)? {
        if name == "revision.json" {
            continue;
        }
        if partial && name.ends_with(".next") {
            let index = name
                .strip_suffix(".next")
                .and_then(|name| name.parse::<usize>().ok())
                .ok_or_else(corrupt)?;
            let descriptor = revision.files.get(index).ok_or_else(corrupt)?;
            if name != format!("{index:03}.next") {
                return Err(corrupt());
            }
            io::required(&path.join(&name), descriptor.size)?;
            continue;
        }
        if !revision
            .files
            .iter()
            .enumerate()
            .any(|(index, _)| name == file_name(index))
        {
            return Err(corrupt());
        }
    }
    Ok((revision, files, total))
}
fn remove_revision(
    path: &Path,
    limits: LifecycleLimits,
    partial: bool,
) -> Result<(), PlatformError> {
    io::directory(path)?;
    if partial && io::files(path, 76)?.is_empty() {
        std::fs::remove_dir(path).map_err(|_| unavailable())?;
        return io::sync(path.parent().ok_or_else(corrupt)?);
    }
    if partial
        && path.file_name().and_then(|name| name.to_str()) == Some("PENDING")
        && io::read(&path.join("revision.json"), 16 * 1024)?.is_none()
    {
        let names = io::files(path, 2)?;
        if names != ["revision.next"] {
            return Err(corrupt());
        }
        io::required(&path.join("revision.next"), 16 * 1024)?;
        io::remove(&path.join("revision.next"))?;
        std::fs::remove_dir(path).map_err(|_| unavailable())?;
        return io::sync(path.parent().ok_or_else(corrupt)?);
    }
    let (revision, _, _) = read_revision(path, limits, partial)?;
    for index in 0..revision.files.len() {
        let temporary = path.join(format!("{index:03}.next"));
        if temporary.exists() {
            io::remove(&temporary)?;
        }
        let file = path.join(file_name(index));
        if file.exists() {
            io::remove(&file)?;
        }
    }
    io::remove(&path.join("revision.json"))?;
    std::fs::remove_dir(path).map_err(|_| unavailable())?;
    io::sync(path.parent().ok_or_else(corrupt)?)
}
