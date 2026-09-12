//! One fixed-size, atomically replaced durable floor and one staging file.
use super::config::PolicyIdentity;
use latent_artifacts::package::{validate_package_json, PackageLimits};
use latent_core::{PlatformError, PlatformErrorCode};
use serde::{Deserialize, Serialize};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

const MAX_BYTES: usize = 4096;
const INITIALIZED: &[u8] = b"lsf-admission-authority-v1\n";
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct DurableFloor {
    format_version: u32,
    pub epoch: u64,
    pub restart_not_before: u64,
    policy: PolicyIdentity,
}
impl DurableFloor {
    pub fn new(policy: &PolicyIdentity, epoch: u64, ceiling: u64) -> Self {
        Self {
            format_version: 1,
            epoch,
            restart_not_before: ceiling,
            policy: policy.clone(),
        }
    }
    pub fn check_policy(&self, next: &PolicyIdentity) -> Result<(), PlatformError> {
        next.replaces(&self.policy)
    }
}

pub(super) struct Ledger {
    root: PathBuf,
    owner_lock: Option<File>,
    #[cfg(test)]
    pub fault: std::sync::atomic::AtomicU8,
}
impl Ledger {
    pub fn open(root: &Path) -> Result<Self, PlatformError> {
        // The production durable node has the same native-Linux requirement as
        // its artifact/deployment catalogs; no pretend directory-sync fallback.
        if !cfg!(target_os = "linux") {
            return Err(super::error(
                PlatformErrorCode::IncompatibleContract,
                "admission-durability-requires-linux",
            ));
        }
        fs::create_dir_all(root).map_err(io)?;
        let root = fs::canonicalize(root).map_err(io)?;
        for ancestor in root.ancestors() {
            sync(ancestor)?;
        }
        let path = root.join(".authority.lock");
        if path.exists() {
            regular(&path)?;
        }
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(path)
            .map_err(io)?;
        lock.try_lock()
            .map_err(|_| super::unavailable("admission-authority-owned"))?;
        lock.sync_all().map_err(io)?;
        sync(&root)?;
        Ok(Self {
            root,
            owner_lock: Some(lock),
            #[cfg(test)]
            fault: std::sync::atomic::AtomicU8::new(0),
        })
    }
    pub fn read(&self) -> Result<Option<DurableFloor>, PlatformError> {
        let initialized = self.initialized()?;
        let path = self.root.join("floor.json");
        match fs::symlink_metadata(&path) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return if initialized {
                    Err(corrupt())
                } else {
                    Ok(None)
                };
            }
            Err(_) => return Err(corrupt()),
            Ok(metadata) if !metadata.is_file() || metadata.len() > MAX_BYTES as u64 => {
                return Err(corrupt())
            }
            Ok(_) => {}
        }
        let mut bytes = Vec::new();
        File::open(&path)
            .map_err(io)?
            .take(MAX_BYTES as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(io)?;
        if bytes.len() > MAX_BYTES {
            return Err(corrupt());
        }
        validate_package_json(
            &bytes,
            PackageLimits {
                max_document_bytes: MAX_BYTES,
                ..PackageLimits::default()
            },
        )
        .map_err(|_| corrupt())?;
        let floor: DurableFloor = serde_json::from_slice(&bytes).map_err(|_| corrupt())?;
        floor.policy.validate().map_err(|_| corrupt())?;
        if floor.format_version != 1
            || floor.epoch == 0
            || floor.restart_not_before == 0
            || encode(&floor)? != bytes
        {
            return Err(corrupt());
        }
        Ok(Some(floor))
    }
    pub fn retire(&mut self) {
        self.owner_lock.take();
    }
    pub fn persist(&self, floor: &DurableFloor) -> Result<(), PlatformError> {
        let bytes = encode(floor)?;
        let temporary = self.root.join("floor.pending.json");
        // An old interrupted staging file acquired no authority. Only the
        // synchronized rename below changes the authoritative restart floor.
        if fs::symlink_metadata(&temporary).is_ok() {
            regular(&temporary)?;
            fs::remove_file(&temporary).map_err(io)?;
        }
        let mut output = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)
            .map_err(io)?;
        output.write_all(&bytes).map_err(io)?;
        #[cfg(test)]
        self.checkpoint(1)?;
        output.sync_all().map_err(io)?;
        #[cfg(test)]
        self.checkpoint(2)?;
        drop(output);
        let destination = self.root.join("floor.json");
        if fs::symlink_metadata(&destination).is_ok() {
            regular(&destination)?;
        }
        fs::rename(temporary, destination).map_err(io)?;
        #[cfg(test)]
        self.checkpoint(3)?;
        sync(&self.root)?;
        #[cfg(test)]
        self.checkpoint(4)?;
        if !self.initialized()? {
            let mut marker = OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(self.root.join("INITIALIZED"))
                .map_err(io)?;
            marker.write_all(INITIALIZED).map_err(io)?;
            marker.sync_all().map_err(io)?;
            sync(&self.root)?;
        }
        Ok(())
    }
    fn initialized(&self) -> Result<bool, PlatformError> {
        let path = self.root.join("INITIALIZED");
        match fs::symlink_metadata(&path) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
            Err(_) => return Err(corrupt()),
            Ok(metadata)
                if !metadata.file_type().is_file()
                    || metadata.len() != INITIALIZED.len() as u64 =>
            {
                return Err(corrupt())
            }
            Ok(_) => {}
        }
        let mut bytes = Vec::new();
        File::open(path)
            .map_err(io)?
            .take(INITIALIZED.len() as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(io)?;
        if bytes != INITIALIZED {
            return Err(corrupt());
        }
        Ok(true)
    }
    #[cfg(test)]
    fn checkpoint(&self, point: u8) -> Result<(), PlatformError> {
        if self.fault.load(std::sync::atomic::Ordering::SeqCst) == point {
            return Err(super::unavailable("admission-durability-uncertain"));
        }
        Ok(())
    }
}
fn encode(floor: &DurableFloor) -> Result<Vec<u8>, PlatformError> {
    let bytes = serde_json::to_vec(floor).map_err(|_| corrupt())?;
    if bytes.len() > MAX_BYTES {
        return Err(corrupt());
    }
    Ok(bytes)
}
fn regular(path: &Path) -> Result<(), PlatformError> {
    if !fs::symlink_metadata(path)
        .map_err(io)?
        .file_type()
        .is_file()
    {
        return Err(corrupt());
    }
    Ok(())
}
fn sync(path: &Path) -> Result<(), PlatformError> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(io)
}
fn io(_: std::io::Error) -> PlatformError {
    super::unavailable("admission-durability-uncertain")
}
fn corrupt() -> PlatformError {
    super::error(
        PlatformErrorCode::CorruptArtifact,
        "admission-floor-corrupt",
    )
}
