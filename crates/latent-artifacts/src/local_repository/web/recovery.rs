use super::{
    capacity, corrupt, fs, io_error, lock_error, persistence, shared_content, storage, Arc,
    ArtifactBlobDigest, CheckedWebLayout, DirectoryArtifactRepository, Entry, PlatformError,
    PlatformErrorCode, PublicationId, State, VerifiedWebAdmission, WebAdmissionBinding,
    WebAdmissionGrant, WebGeneration, EVIDENCE, HEAD, PUBLICATIONS,
};
use crate::package::artifact_blob_digest;

impl DirectoryArtifactRepository {
    pub(in crate::local_repository) fn initialize_web(&self) -> Result<(), PlatformError> {
        let enabled = self.web_enabled()?;
        let root = self.web_path();
        if !root.try_exists().map_err(io_error)? {
            return if enabled {
                Err(corrupt("web-lifecycle-history-missing"))
            } else {
                Ok(())
            };
        }
        shared_content::directory(&root)?;
        let temporary_head_bytes = self.inspect_web_control_files()?;
        if !enabled {
            return self.recover_empty_web_initialization(temporary_head_bytes);
        }
        // An interrupted first initialization before the mode marker may leave
        // only empty control material. Never infer positive grants from payloads.
        let recovered = persistence::read(&root, self.lifecycle_limits, self.web_head_limit())?;
        self.check_web_initialized()?;
        let mut state = State {
            enabled,
            head_bytes: recovered.bytes.max(temporary_head_bytes),
            receipts: recovered.receipts,
            ..State::default()
        };
        let mut writer = self.publish_lock.lock().map_err(lock_error)?;
        for entry in fs::read_dir(root.join(PUBLICATIONS)).map_err(io_error)? {
            let entry = entry.map_err(io_error)?;
            if !enabled {
                return Err(corrupt("web-data-without-format-marker"));
            }
            shared_content::directory(&entry.path())?;
            writer.release_directories = writer
                .release_directories
                .checked_add(1)
                .filter(|n| *n <= self.config.max_recovery_directories)
                .ok_or_else(capacity)?;
            let hex = entry
                .file_name()
                .into_string()
                .map_err(|_| corrupt("web-directory-name"))?;
            let id: PublicationId = format!("publication:sha256:{hex}")
                .parse()
                .map_err(|_| corrupt("web-directory-name"))?;
            let stored = storage::Stored::read(
                &entry.path(),
                self.web_authority()?.limits,
                self.config.max_component_bytes,
            )?;
            if stored.publication.id != id {
                return Err(corrupt("web-directory-association"));
            }
            self.content
                .lock()
                .map_err(lock_error)?
                .register_directory(&id, &entry.path())?;
        }
        if !enabled && (!recovered.rows.is_empty() || !state.receipts.is_empty()) {
            return Err(corrupt("web-history-without-format-marker"));
        }
        let mut retained = state.retained_bytes()?;
        for disk in recovered.rows {
            let entry = self.recover_web_entry(disk)?;
            retained = retained
                .checked_add(entry.retained_bytes()?)
                .ok_or_else(capacity)?;
            state
                .entries
                .insert(entry.record.publication.id.clone(), entry);
            self.index.read().map_err(lock_error)?.check_web(
                state.entries.len(),
                retained,
                self.config,
            )?;
        }
        self.recover_web_evidence(&mut state)?;
        self.index.write().map_err(lock_error)?.replace_web(
            state.entries.len(),
            state.retained_bytes()?,
            self.config,
        )?;
        self.content
            .lock()
            .map_err(lock_error)?
            .replace_web_control(control_exposure(&state, state.head_bytes)?)?;
        // The sole writer owns this incarnation before open returns. Temporary
        // head bytes are never authoritative; their reserved exposure is charged.
        *self.web.state.write().map_err(lock_error)? = state;
        Ok(())
    }
    fn inspect_web_control_files(&self) -> Result<usize, PlatformError> {
        let mut temporary_head_bytes = 0usize;
        let mut count = 0;
        for entry in fs::read_dir(self.web_path()).map_err(io_error)? {
            count += 1;
            if count > 6 {
                return Err(corrupt("web-control-file-set"));
            }
            let entry = entry.map_err(io_error)?;
            match entry.file_name().to_str() {
                Some(PUBLICATIONS | EVIDENCE) => {
                    shared_content::directory(&entry.path())?;
                }
                Some(HEAD | persistence::INITIALIZED) => {
                    shared_content::regular(&entry.path())?;
                }
                Some("HEAD.next") => {
                    temporary_head_bytes =
                        usize::try_from(shared_content::regular(&entry.path())?.len())
                            .map_err(|_| capacity())?;
                    if temporary_head_bytes > self.web_head_limit() {
                        return Err(capacity());
                    }
                }
                Some("INITIALIZED.next") => {
                    if shared_content::regular(&entry.path())?.len() > 64 {
                        return Err(capacity());
                    }
                }
                _ => return Err(corrupt("web-control-file-set")),
            }
        }
        Ok(temporary_head_bytes)
    }
    fn recover_empty_web_initialization(
        &self,
        temporary_head_bytes: usize,
    ) -> Result<(), PlatformError> {
        let root = self.web_path();
        for name in [PUBLICATIONS, EVIDENCE] {
            let path = root.join(name);
            if path.try_exists().map_err(io_error)?
                && fs::read_dir(path).map_err(io_error)?.next().is_some()
            {
                return Err(corrupt("web-data-without-format-marker"));
            }
        }
        let mut head_bytes = temporary_head_bytes;
        let exists = root.join(HEAD).try_exists().map_err(io_error)?;
        if root
            .join(persistence::INITIALIZED)
            .try_exists()
            .map_err(io_error)?
        {
            self.check_web_initialized()?;
            if !exists {
                return Err(corrupt("web-lifecycle-history-missing"));
            }
        }
        if exists {
            let recovered = persistence::read(&root, self.lifecycle_limits, self.web_head_limit())?;
            if !recovered.rows.is_empty() || !recovered.receipts.is_empty() {
                return Err(corrupt("web-history-without-format-marker"));
            }
            head_bytes = head_bytes.max(recovered.bytes);
        }
        // The first mode promotion precedes every payload write. Bounded empty
        // initialization remnants therefore cannot represent a past permission.
        let state = State {
            head_bytes,
            ..State::default()
        };
        self.index.write().map_err(lock_error)?.replace_web(
            0,
            state.retained_bytes()?,
            self.config,
        )?;
        self.content
            .lock()
            .map_err(lock_error)?
            .replace_web_control(control_exposure(&state, head_bytes)?)?;
        *self.web.state.write().map_err(lock_error)? = state;
        Ok(())
    }
    fn recover_web_entry(&self, disk: persistence::Row) -> Result<Entry, PlatformError> {
        let config = self.web_authority()?;
        let stored = self.web_storage(&disk.record.publication)?;
        if stored.digest()? != disk.completion {
            return Err(corrupt("web-retained-publication-missing-or-changed"));
        }
        let directory = self.web_publication_path(&disk.record.publication.id);
        let binding = stored.binding(&directory, config.limits)?;
        let mut upload =
            stored.upload(&directory, config.limits, self.config.max_component_bytes)?;
        let layout = storage::check_upload(
            &binding,
            &mut upload,
            config.limits,
            self.config.max_component_bytes,
        )?;
        if layout.package() != &disk.record.package
            || layout.manifest_digest() != &disk.record.manifest
            || layout.assets_digest() != &disk.record.assets
        {
            return Err(corrupt("web-lifecycle-package-association"));
        }
        // Validate original admission history even after evidence replacement.
        let original = config.authority.recover_web(&binding, upload);
        let original = self.recovered_web_grant(&binding, &layout, original)?;
        let grant = if let Some(revision) = &disk.record.evidence_revision {
            let (binding, upload) =
                self.read_web_revision(&disk.record.publication, revision, &disk.completion)?;
            let value = config.authority.recover_web(&binding, upload);
            self.recovered_web_grant(&binding, &layout, value)?
        } else {
            original
        };
        Ok(Entry {
            projection: super::projection::Projection::new(&disk.record.publication, &layout)?,
            generation: Arc::new(WebGeneration::new(disk.record.generation)),
            record: disk.record,
            completion: disk.completion,
            layout: Arc::new(layout),
            grant,
        })
    }
    fn recovered_web_grant(
        &self,
        binding: &WebAdmissionBinding,
        layout: &CheckedWebLayout,
        result: Result<VerifiedWebAdmission, PlatformError>,
    ) -> Result<Option<Arc<dyn WebAdmissionGrant>>, PlatformError> {
        match result {
            Ok(value) => {
                if value.grant.binding() != binding || &value.layout != layout {
                    return Err(corrupt("web-recovery-grant-association"));
                }
                self.check_web_grant(&binding.tenant, &value)?;
                Ok(Some(value.grant))
            }
            Err(failure)
                if matches!(
                    failure.code,
                    PlatformErrorCode::PermissionDenied
                        | PlatformErrorCode::IncompatibleContract
                        | PlatformErrorCode::StateConflict
                        | PlatformErrorCode::Unavailable
                ) =>
            {
                Ok(None)
            }
            Err(failure) => Err(failure),
        }
    }
}
pub(super) fn control_exposure(state: &State, next_head: usize) -> Result<u64, PlatformError> {
    // Reserve one old head and one maximum next head, including a stopped
    // atomic write. A replacement cannot briefly exceed the storage ceiling.
    state
        .evidence_bytes
        .checked_add(state.head_bytes.max(next_head) as u64)
        .and_then(|n| n.checked_add(state.head_bytes.max(next_head) as u64))
        .and_then(|n| n.checked_add(512))
        .ok_or_else(capacity)
}
impl storage::Stored {
    pub(super) fn digest(&self) -> Result<ArtifactBlobDigest, PlatformError> {
        Ok(artifact_blob_digest(
            &serde_json::to_vec(self).map_err(|_| corrupt("web-record-encoding"))?,
        ))
    }
}
