use std::io::{self, Read};
use std::path::Path;

use super::ProbeLimits;

pub(super) struct Reads {
    pub(super) limits: ProbeLimits,
    remaining: usize,
}

impl Reads {
    pub(super) fn new(limits: ProbeLimits) -> Self {
        Self {
            limits,
            remaining: limits.maximum_total_bytes,
        }
    }

    pub(super) fn charge(&mut self, bytes: usize) -> io::Result<()> {
        self.remaining = self.remaining.checked_sub(bytes).ok_or_else(limit)?;
        Ok(())
    }

    pub(super) fn file(&mut self, path: &Path, maximum: usize) -> io::Result<Vec<u8>> {
        let limit_bytes = maximum.min(self.remaining);
        let mut bytes = Vec::new();
        std::fs::File::open(path)?
            .take(
                u64::try_from(limit_bytes)
                    .unwrap_or(u64::MAX)
                    .saturating_add(1),
            )
            .read_to_end(&mut bytes)?;
        if bytes.len() > limit_bytes {
            return Err(limit());
        }
        self.charge(bytes.len())?;
        Ok(bytes)
    }
}

pub(super) fn numeric_entries(path: &Path, maximum: usize) -> io::Result<Vec<u32>> {
    let mut result = Vec::new();
    for entry in std::fs::read_dir(path)? {
        if result.len() >= maximum {
            return Err(limit());
        }
        let entry = entry?;
        let id = entry
            .file_name()
            .to_str()
            .and_then(|name| name.parse::<u32>().ok())
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "invalid proc entry"))?;
        result.push(id);
    }
    result.sort_unstable();
    Ok(result)
}

pub(super) fn limit() -> io::Error {
    io::Error::new(
        io::ErrorKind::InvalidData,
        "child resource probe limit exceeded",
    )
}
