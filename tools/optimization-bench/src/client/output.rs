use std::fs::{File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

use serde::Serialize;

use super::{plan::MAXIMUM_ROW_BYTES, record::Attempt, Result};

pub(super) struct Output {
    root: PathBuf,
    attempts: BufWriter<File>,
    remaining: u64,
}

impl Output {
    pub fn new(root: PathBuf, maximum: u64) -> Result<Self> {
        std::fs::create_dir_all(&root).map_err(|_| "output-directory-failed")?;
        // All collector-owned files are exclusive; parent-owned plan/log files may exist.
        if ["readiness.json", "summary.json", "attempts.jsonl"]
            .iter()
            .any(|name| root.join(name).exists())
        {
            return Err("output-already-exists");
        }
        let attempts = BufWriter::with_capacity(64 * 1024, create(&root.join("attempts.jsonl"))?);
        Ok(Self {
            root,
            attempts,
            remaining: maximum,
        })
    }

    pub fn document<T: Serialize>(&mut self, name: &str, value: &T) -> Result<()> {
        let bytes = encode(value, self.remaining.min(8 * 1024 * 1024))?;
        self.charge(bytes.len())?;
        let mut file = create(&self.root.join(name))?;
        file.write_all(&bytes).map_err(|_| "output-write-failed")?;
        file.sync_all().map_err(|_| "output-sync-failed")
    }

    pub fn attempt(&mut self, row: &Attempt) -> Result<()> {
        let mut bytes = encode(row, MAXIMUM_ROW_BYTES - 1)?;
        bytes.push(b'\n');
        self.charge(bytes.len())?;
        self.attempts
            .write_all(&bytes)
            .map_err(|_| "attempt-write-failed")
    }

    pub fn finish(&mut self) -> Result<()> {
        self.attempts.flush().map_err(|_| "attempt-flush-failed")?;
        self.attempts
            .get_ref()
            .sync_all()
            .map_err(|_| "attempt-sync-failed")
    }

    fn charge(&mut self, bytes: usize) -> Result<()> {
        self.remaining = self
            .remaining
            .checked_sub(bytes as u64)
            .ok_or("output-byte-limit")?;
        Ok(())
    }
}

fn create(path: &Path) -> Result<File> {
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|_| "exclusive-output-create-failed")
}

fn encode<T: Serialize>(value: &T, maximum: u64) -> Result<Vec<u8>> {
    let mut writer = Limited {
        bytes: Vec::new(),
        maximum,
    };
    serde_json::to_writer(&mut writer, value).map_err(|_| "encoded-output-byte-limit")?;
    Ok(writer.bytes)
}

struct Limited {
    bytes: Vec<u8>,
    maximum: u64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bounded_writer_stops_before_retaining_an_oversized_serialization() {
        let mut writer = Limited {
            bytes: Vec::new(),
            maximum: 4,
        };
        assert!(serde_json::to_writer(&mut writer, &"abcdef").is_err());
        assert!(writer.bytes.len() <= 4);
        assert!(writer.bytes.capacity() <= 4);
    }

    #[test]
    fn exclusive_output_creation_does_not_overwrite_existing_bytes() {
        let path = std::env::temp_dir().join(format!(
            "optimization-client-exclusive-{}-{}.json",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let mut file = create(&path).unwrap();
        file.write_all(b"original").unwrap();
        drop(file);
        assert!(create(&path).is_err());
        assert_eq!(std::fs::read(&path).unwrap(), b"original");
        std::fs::remove_file(path).unwrap();
    }
}
impl Write for Limited {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        let needed = self
            .bytes
            .len()
            .checked_add(bytes.len())
            .filter(|n| *n as u64 <= self.maximum)
            .ok_or_else(|| std::io::Error::other("output-byte-limit"))?;
        if needed > self.bytes.capacity() {
            let capacity = needed
                .max(self.bytes.capacity().saturating_mul(2))
                .min(self.maximum as usize);
            self.bytes
                .try_reserve_exact(capacity - self.bytes.len())
                .map_err(std::io::Error::other)?;
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
