use super::super::unavailable;
use super::{codec, model::Image, PolicyStoreLimits};
use latent_core::PlatformError;
use serde::{Deserialize, Serialize};
use std::{
    fs::File,
    io::{Read, Write},
    path::Path,
};

#[cfg(target_os = "linux")]
mod linux;
const MARKER: &[u8] = b"lsf-capability-policy-store-v1\n";

pub(super) struct Ledger {
    root: File,
    _lock: File,
    pub cursor_key: [u8; 32],
    #[cfg(test)]
    pub fault: std::sync::atomic::AtomicU8,
}
#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Floor {
    format_version: u32,
    generation: u64,
    digest: String,
}

impl Ledger {
    #[cfg(target_os = "linux")]
    pub fn open(path: &Path, limits: PolicyStoreLimits) -> Result<(Self, Image), PlatformError> {
        let root = linux::root(path)?;
        let lock = linux::open(&root, ".owner.lock", true)?.ok_or_else(unavailable)?;
        lock.try_lock().map_err(|_| unavailable())?;
        lock.sync_all()
            .and_then(|()| root.sync_all())
            .map_err(|_| unavailable())?;
        let mut cursor_key = [0; 32];
        File::open("/dev/urandom")
            .and_then(|mut f| f.read_exact(&mut cursor_key))
            .map_err(|_| unavailable())?;
        let ledger = Self {
            root,
            _lock: lock,
            cursor_key,
            #[cfg(test)]
            fault: std::sync::atomic::AtomicU8::new(0),
        };
        let image = ledger.recover(limits)?;
        Ok((ledger, image))
    }
    #[cfg(not(target_os = "linux"))]
    pub fn open(_: &Path, _: PolicyStoreLimits) -> Result<(Self, Image), PlatformError> {
        Err(super::super::error(
            latent_core::PlatformErrorCode::IncompatibleContract,
            "capability-policy-durability-requires-linux",
        ))
    }
    fn recover(&self, limits: PolicyStoreLimits) -> Result<Image, PlatformError> {
        let initialized = self.read("INITIALIZED", MARKER.len())?;
        let initializing = self.read("INITIALIZING", MARKER.len())?;
        if initialized.is_none() && initializing.is_none() {
            if self.read("floor.json", 512)?.is_some()
                || self
                    .read("catalog.json", limits.maximum_catalog_bytes)?
                    .is_some()
                || self
                    .read("catalog.pending.json", limits.maximum_catalog_bytes)?
                    .is_some()
                || self.read("floor.pending.json", 512)?.is_some()
            {
                return Err(codec::corrupt());
            }
            self.write_new("INITIALIZING", MARKER)?;
            let image = Image::empty();
            let bytes = codec::encode(&image, limits.maximum_catalog_bytes)?;
            self.persist(&bytes, image.generation)?;
            self.rename("INITIALIZING", "INITIALIZED")?;
            return Ok(image);
        }
        if initialized.as_deref().is_some_and(|v| v != MARKER)
            || initializing.as_deref().is_some_and(|v| v != MARKER)
            || (initialized.is_some() && initializing.is_some())
        {
            return Err(codec::corrupt());
        }
        let floor_bytes = self.read("floor.json", 512)?.ok_or_else(codec::corrupt)?;
        let floor: Floor = serde_json::from_slice(&floor_bytes).map_err(|_| codec::corrupt())?;
        if floor.format_version != 1
            || floor.generation == 0
            || !codec::is_digest(&floor.digest)
            || codec::encode(&floor, 512)? != floor_bytes
        {
            return Err(codec::corrupt());
        }
        let mut bytes = self.read("catalog.json", limits.maximum_catalog_bytes)?;
        if bytes
            .as_deref()
            .is_none_or(|value| codec::digest(value) != floor.digest)
        {
            bytes = self.read("catalog.pending.json", limits.maximum_catalog_bytes)?;
            if bytes
                .as_deref()
                .is_none_or(|value| codec::digest(value) != floor.digest)
            {
                return Err(codec::corrupt());
            }
            let image = codec::decode(bytes.as_deref().ok_or_else(codec::corrupt)?, limits)?;
            if image.generation != floor.generation {
                return Err(codec::corrupt());
            }
            self.rename("catalog.pending.json", "catalog.json")?;
        }
        let image = codec::decode(bytes.as_deref().ok_or_else(codec::corrupt)?, limits)?;
        if image.generation != floor.generation {
            return Err(codec::corrupt());
        }
        if initializing.is_some() {
            self.rename("INITIALIZING", "INITIALIZED")?;
        }
        // Interrupted, uncommitted staging never gains authority by its presence.
        self.remove("catalog.pending.json")?;
        self.remove("floor.pending.json")?;
        Ok(image)
    }
    pub fn persist(&self, bytes: &[u8], generation: u64) -> Result<(), PlatformError> {
        self.remove("catalog.pending.json")?;
        self.write_new("catalog.pending.json", bytes)?;
        #[cfg(test)]
        self.checkpoint(1)?;
        let floor = codec::encode(
            &Floor {
                format_version: 1,
                generation,
                digest: codec::digest(bytes),
            },
            512,
        )?;
        self.remove("floor.pending.json")?;
        self.write_new("floor.pending.json", &floor)?;
        #[cfg(test)]
        self.checkpoint(2)?;
        // Publish the floor first. Recovery may finish only the exact staged
        // image it authenticates, and can never fall back to older permissions.
        self.rename("floor.pending.json", "floor.json")?;
        #[cfg(test)]
        self.checkpoint(3)?;
        self.rename("catalog.pending.json", "catalog.json")?;
        #[cfg(test)]
        self.checkpoint(4)?;
        Ok(())
    }
    #[cfg(test)]
    fn checkpoint(&self, point: u8) -> Result<(), PlatformError> {
        if self.fault.load(std::sync::atomic::Ordering::Acquire) == point {
            return Err(unavailable());
        }
        Ok(())
    }
    fn read(&self, name: &str, maximum: usize) -> Result<Option<Vec<u8>>, PlatformError> {
        let Some(mut file) = self.open_file(name, false)? else {
            return Ok(None);
        };
        let before = file.metadata().map_err(|_| unavailable())?;
        if before.len() > maximum as u64 {
            return Err(codec::corrupt());
        }
        let mut bytes = Vec::new();
        std::io::Read::by_ref(&mut file)
            .take(maximum as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| unavailable())?;
        if bytes.len() > maximum || bytes.len() as u64 != before.len() {
            return Err(codec::corrupt());
        }
        #[cfg(target_os = "linux")]
        linux::unchanged(&before, &file.metadata().map_err(|_| unavailable())?)?;
        Ok(Some(bytes))
    }
    fn write_new(&self, name: &str, bytes: &[u8]) -> Result<(), PlatformError> {
        let mut file = self.open_file(name, true)?.ok_or_else(unavailable)?;
        // Only the lock permits reopening. Data and marker writes are exclusive.
        if file.metadata().map_err(|_| unavailable())?.len() != 0 {
            return Err(codec::corrupt());
        }
        file.write_all(bytes)
            .and_then(|()| file.sync_all())
            .and_then(|()| self.root.sync_all())
            .map_err(|_| unavailable())
    }
    #[cfg(target_os = "linux")]
    fn open_file(&self, name: &str, create: bool) -> Result<Option<File>, PlatformError> {
        linux::open(&self.root, name, create)
    }
    #[cfg(not(target_os = "linux"))]
    fn open_file(&self, _: &str, _: bool) -> Result<Option<File>, PlatformError> {
        Err(unavailable())
    }
    #[cfg(target_os = "linux")]
    fn rename(&self, from: &str, to: &str) -> Result<(), PlatformError> {
        linux::rename(&self.root, from, to)?;
        #[cfg(test)]
        match to {
            "floor.json" => self.checkpoint(5)?,
            "catalog.json" => self.checkpoint(6)?,
            _ => (),
        }
        self.root.sync_all().map_err(|_| unavailable())
    }
    #[cfg(not(target_os = "linux"))]
    fn rename(&self, _: &str, _: &str) -> Result<(), PlatformError> {
        Err(unavailable())
    }
    #[cfg(target_os = "linux")]
    fn remove(&self, name: &str) -> Result<(), PlatformError> {
        linux::remove(&self.root, name)
    }
    #[cfg(not(target_os = "linux"))]
    fn remove(&self, _: &str) -> Result<(), PlatformError> {
        Err(unavailable())
    }
}
