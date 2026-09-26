use super::{
    busy, capacity, corrupt, fs, io_error, lock_error, recovery, shared_content, sync_dir,
    ArtifactBlobDigest, DirectoryArtifactRepository, PlatformError, PublicationId, EVIDENCE,
    PUBLICATIONS, TEMP_DIR,
};

impl DirectoryArtifactRepository {
    /// Bounded control maintenance. Current and terminal lifecycle rows retain
    /// original packages and their selected evidence. Only uncommitted packages
    /// and superseded/interrupted evidence revisions can be removed here.
    /// Shared zero-reference blob removal remains `reclaim_uncommitted_content`.
    pub fn reclaim_uncommitted_web_content(&self, maximum: usize) -> Result<usize, PlatformError> {
        if maximum == 0 || maximum > 1024 {
            return Err(capacity());
        }
        let _work = self.admission_work.try_lock().map_err(|_| busy())?;
        let _epoch = self.web.epoch.write()?;
        let mut state = self.web.state.try_write().map_err(|_| busy())?;
        if !state.enabled {
            return Ok(0);
        }
        let mut writer = self.publish_lock.try_lock().map_err(|_| busy())?;
        if writer.pending.is_some() {
            return Err(busy());
        }
        let mut content = self.content.lock().map_err(lock_error)?;
        let result = (|| {
            let publications =
                self.reclaim_web_publications(&state, &mut writer, &mut content, maximum)?;
            let revisions = self.reclaim_web_revisions(&mut state, maximum - publications)?;
            content.replace_web_control(recovery::control_exposure(&state, state.head_bytes)?)?;
            Ok(publications + revisions)
        })();
        if let Err(failure) = result {
            // Retain the conservative storage charge and close web authority.
            // Shared-content write failures additionally poison that owner.
            self.web.epoch.retire();
            return Err(failure);
        }
        result
    }
    fn reclaim_web_publications(
        &self,
        state: &super::State,
        writer: &mut super::PublicationState,
        content: &mut shared_content::SharedContent,
        maximum: usize,
    ) -> Result<usize, PlatformError> {
        let mut removed = 0usize;
        for (scanned, entry) in fs::read_dir(self.web_path().join(PUBLICATIONS))
            .map_err(io_error)?
            .enumerate()
        {
            if removed == maximum {
                break;
            }
            if scanned >= self.config.max_recovery_directories {
                return Err(capacity());
            }
            let entry = entry.map_err(io_error)?;
            let name = entry
                .file_name()
                .into_string()
                .map_err(|_| corrupt("web-directory-name"))?;
            let id: PublicationId = format!("publication:sha256:{name}")
                .parse()
                .map_err(|_| corrupt("web-directory-name"))?;
            if state.entries.contains_key(&id) {
                continue;
            }
            writer.pending = Some(id.clone());
            content.forget_uncommitted(&id, &entry.path())?;
            writer.release_directories = writer
                .release_directories
                .checked_sub(1)
                .ok_or_else(capacity)?;
            writer.pending = None;
            removed += 1;
        }
        Ok(removed)
    }
    fn reclaim_web_revisions(
        &self,
        state: &mut super::State,
        maximum: usize,
    ) -> Result<usize, PlatformError> {
        let mut removed = 0usize;
        let selected: std::collections::BTreeSet<_> = state
            .entries
            .values()
            .filter_map(|entry| entry.record.evidence_revision.clone())
            .collect();
        for (scanned, entry) in fs::read_dir(self.web_path().join(EVIDENCE))
            .map_err(io_error)?
            .enumerate()
        {
            if removed == maximum {
                break;
            }
            if scanned >= self.config.max_recovery_directories {
                return Err(capacity());
            }
            let entry = entry.map_err(io_error)?;
            let name = entry
                .file_name()
                .into_string()
                .map_err(|_| corrupt("web-evidence-directory"))?;
            let digest: ArtifactBlobDigest = format!("sha256:{name}")
                .parse()
                .map_err(|_| corrupt("web-evidence-directory"))?;
            if selected.contains(&digest) {
                continue;
            }
            let files = shared_content::bounded_files(&entry.path(), self.config)?;
            let bytes = files
                .iter()
                .try_fold(0u64, |n, (_, size)| n.checked_add(*size))
                .ok_or_else(capacity)?;
            // Hide the entire unselected revision before unlinking files,
            // so crash cleanup never exposes a half-deleted revision.
            let temporary = self
                .root
                .join(TEMP_DIR)
                .join(format!("web-evidence-gc-{name}"));
            if temporary.try_exists().map_err(io_error)? {
                return Err(corrupt("web-evidence-gc-conflict"));
            }
            fs::rename(entry.path(), &temporary).map_err(io_error)?;
            sync_dir(&self.web_path().join(EVIDENCE))?;
            for (file, _) in files {
                fs::remove_file(temporary.join(file)).map_err(io_error)?;
            }
            fs::remove_dir(&temporary).map_err(io_error)?;
            sync_dir(&self.root.join(TEMP_DIR))?;
            state.evidence_bytes = state
                .evidence_bytes
                .checked_sub(bytes)
                .ok_or_else(capacity)?;
            state.evidence_directories = state
                .evidence_directories
                .checked_sub(1)
                .ok_or_else(capacity)?;
            removed += 1;
        }
        Ok(removed)
    }
}
