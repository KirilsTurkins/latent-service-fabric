use std::io::{self, Write};

use serde::Serialize;

use super::EvidenceError;

#[derive(Debug, Clone, Copy)]
pub struct ReportLimits {
    pub maximum_bytes: usize,
}

impl Default for ReportLimits {
    fn default() -> Self {
        Self {
            maximum_bytes: 4 * 1024 * 1024,
        }
    }
}

struct BoundedWriter {
    bytes: Vec<u8>,
    maximum: usize,
}

impl Write for BoundedWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > self.maximum.saturating_sub(self.bytes.len()) {
            return Err(io::Error::other("conformance-report-byte-limit"));
        }
        // Never let geometric Vec growth reserve beyond the report byte limit.
        let needed = self.bytes.len() + bytes.len();
        if needed > self.bytes.capacity() {
            let target = self
                .bytes
                .capacity()
                .saturating_mul(2)
                .max(needed)
                .min(self.maximum);
            self.bytes
                .try_reserve_exact(target - self.bytes.len())
                .map_err(io::Error::other)?;
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

/// Serializes directly into a capped writer, without constructing a second JSON
/// value tree or first allocating an uncapped encoded report.
pub fn encode_bounded<T: Serialize>(
    value: &T,
    limits: ReportLimits,
) -> Result<Vec<u8>, EvidenceError> {
    if limits.maximum_bytes == 0 || limits.maximum_bytes > ReportLimits::default().maximum_bytes {
        return Err(EvidenceError("invalid-conformance-report-limit"));
    }
    let mut writer = BoundedWriter {
        bytes: Vec::new(),
        maximum: limits.maximum_bytes,
    };
    serde_json::to_writer(&mut writer, value)
        .map_err(|_| EvidenceError("conformance-report-encoding-limit"))?;
    Ok(writer.bytes)
}
