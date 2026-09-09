use std::fs::{File, OpenOptions};
use std::io::{self, BufWriter, Write};
use std::path::Path;

use serde_json::Value;

use super::Result;

const MAXIMUM_DOCUMENT_BYTES: usize = 16 * 1024 * 1024;
const MAXIMUM_RECORD_BYTES: usize = 256 * 1024;

/// One JSON document, streamed without retaining the growing sample population.
pub(super) struct Writer {
    file: BufWriter<File>,
    written: usize,
    count: u32,
    maximum_samples: u32,
    maximum_bytes: usize,
    finished: bool,
}

impl Writer {
    pub fn new(directory: &Path, header: &Value) -> Result<Self> {
        Self::named(directory, "candidate.json", 440, header)
    }

    pub fn named(
        directory: &Path,
        name: &str,
        maximum_samples: u32,
        header: &Value,
    ) -> Result<Self> {
        if !matches!(
            name,
            "candidate.json"
                | "cold.json"
                | "cache.json"
                | "budget.json"
                | "recovery.json"
                | "ownership.json"
                | "engine.json"
        ) || !(1..=2048).contains(&maximum_samples)
        {
            return Err("comparison writer limits".into());
        }
        let mut bytes = record(header)?;
        if bytes.pop() != Some(b'}') || bytes.first() != Some(&b'{') {
            return Err("comparison header is not an object".into());
        }
        bytes.extend_from_slice(b",\"samples\":[");
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(directory.join(name))?;
        let mut writer = Self {
            file: BufWriter::with_capacity(64 * 1024, file),
            written: 0,
            count: 0,
            maximum_samples,
            maximum_bytes: if name == "engine.json" {
                32 * 1024 * 1024
            } else if name == "ownership.json" {
                8 * 1024 * 1024
            } else {
                MAXIMUM_DOCUMENT_BYTES
            },
            finished: false,
        };
        writer.append(&bytes)?;
        Ok(writer)
    }

    pub fn sample(&mut self, sample: &Value) -> Result<()> {
        if self.finished || self.count >= self.maximum_samples {
            return Err("comparison sample count bound".into());
        }
        let bytes = record(sample)?;
        let mut row = Vec::with_capacity(bytes.len() + 1);
        if self.count != 0 {
            row.push(b',');
        }
        row.extend_from_slice(&bytes);
        self.append(&row)?;
        self.count += 1;
        Ok(())
    }

    pub fn finish(&mut self, footer: &Value) -> Result<()> {
        if self.finished {
            return Err("comparison document already finished".into());
        }
        let bytes = record(footer)?;
        if bytes.first() != Some(&b'{') {
            return Err("comparison footer is not an object".into());
        }
        let mut row = Vec::with_capacity(bytes.len() + 2);
        row.extend_from_slice(b"],");
        row.extend_from_slice(&bytes[1..]);
        row.push(b'\n');
        self.append(&row)?;
        self.file.get_ref().sync_all()?;
        self.finished = true;
        Ok(())
    }

    fn append(&mut self, bytes: &[u8]) -> Result<()> {
        let next = self
            .written
            .checked_add(bytes.len())
            .filter(|next| *next <= self.maximum_bytes)
            .ok_or("comparison document byte limit")?;
        self.file.write_all(bytes)?;
        self.file.flush()?;
        self.written = next;
        Ok(())
    }
}

fn record(value: &Value) -> Result<Vec<u8>> {
    struct Row(Vec<u8>);
    impl Write for Row {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            if self.0.len().saturating_add(bytes.len()) > MAXIMUM_RECORD_BYTES {
                return Err(io::Error::other("comparison record byte limit"));
            }
            self.0.extend_from_slice(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
    let mut row = Row(Vec::with_capacity(1024));
    serde_json::to_writer(&mut row, value)?;
    Ok(row.0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn streamed_document_retains_every_sample_and_rejects_partial_oversized_records() {
        let directory = tempfile::tempdir().unwrap();
        let mut writer = Writer::new(directory.path(), &json!({"schema":"synthetic"})).unwrap();
        writer.sample(&json!({"iteration":"0"})).unwrap();
        let before = std::fs::read(directory.path().join("candidate.json")).unwrap();
        assert!(writer
            .sample(&json!({"data":"x".repeat(MAXIMUM_RECORD_BYTES)}))
            .is_err());
        assert_eq!(
            before,
            std::fs::read(directory.path().join("candidate.json")).unwrap()
        );
        writer.sample(&json!({"iteration":"1"})).unwrap();
        writer.finish(&json!({"status":"passed"})).unwrap();
        assert!(writer.sample(&json!({})).is_err());
        assert!(Writer::new(directory.path(), &json!({})).is_err());
        let document: Value = serde_json::from_slice(
            &std::fs::read(directory.path().join("candidate.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(
            document["samples"],
            json!([{"iteration":"0"},{"iteration":"1"}])
        );
        assert_eq!(document["status"], "passed");
    }
}
