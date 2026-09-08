use std::fs::{File, OpenOptions};
use std::io::{self, BufWriter, Write};
use std::path::Path;
use std::time::Instant;

use serde_json::{json, Value};

use super::Result;

const MAXIMUM_ROW_BYTES: usize = 256 * 1024;

pub struct MeasurementWriter {
    file: BufWriter<File>,
    sequence: u64,
    written: u64,
    maximum: u64,
    finished: bool,
    origin: Instant,
}

impl MeasurementWriter {
    pub fn new(directory: &Path, maximum: u64, header: &Value, origin: Instant) -> Result<Self> {
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(directory.join("measurements.jsonl"))?;
        let mut writer = Self {
            file: BufWriter::with_capacity(64 * 1024, file),
            sequence: 0,
            written: 0,
            maximum,
            finished: false,
            origin,
        };
        writer.write("header", header)?;
        Ok(writer)
    }

    pub fn write(&mut self, kind: &str, payload: &Value) -> io::Result<()> {
        if self.finished
            || kind.is_empty()
            || kind.len() > 64
            || !kind
                .bytes()
                .all(|byte| byte.is_ascii_lowercase() || byte == b'-')
        {
            return Err(io::Error::other("invalid measurement event"));
        }
        let mut row = Row {
            bytes: Vec::with_capacity(1024),
        };
        serde_json::to_writer(
            &mut row,
            &json!({"schema":"latent.phase1.measurement.raw.v1",
            "sequence":self.sequence.to_string(),"kind":kind,"payload":payload}),
        )?;
        row.write_all(b"\n")?;
        let next = self
            .written
            .checked_add(u64::try_from(row.bytes.len()).unwrap())
            .filter(|next| *next <= self.maximum)
            .ok_or_else(|| io::Error::other("measurement output byte limit"))?;
        self.file.write_all(&row.bytes)?;
        self.file.flush()?;
        self.sequence += 1;
        self.written = next;
        Ok(())
    }

    pub fn finish(
        &mut self,
        directory: &Path,
        status: &str,
        reason: Option<&str>,
        shutdown: &Value,
        work: &Value,
        workload_result: &Value,
    ) -> Result<()> {
        let summary = json!({"status":status,"reason":reason,"event_count":self.sequence.saturating_sub(1).to_string(),
            "elapsed_nanos":self.origin.elapsed().as_nanos().to_string(),"shutdown":shutdown,"work":work,"workload_result":workload_result});
        self.write("summary", &summary)?;
        self.finished = true;
        self.file.get_ref().sync_all()?;
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(directory.join("summary.json"))?;
        serde_json::to_writer(&mut file, &summary)?;
        file.sync_all()?;
        Ok(())
    }
}

struct Row {
    bytes: Vec<u8>,
}
impl Write for Row {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self
            .bytes
            .len()
            .checked_add(bytes.len())
            .is_none_or(|length| length > MAXIMUM_ROW_BYTES)
        {
            return Err(io::Error::other("measurement row byte limit"));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn oversized_event_cannot_append_partial_json() {
        let directory = tempfile::tempdir().unwrap();
        let mut writer = MeasurementWriter::new(
            directory.path(),
            1024 * 1024,
            &json!({"synthetic":true}),
            Instant::now(),
        )
        .unwrap();
        let before = std::fs::read(directory.path().join("measurements.jsonl")).unwrap();
        assert!(writer
            .write("sample", &json!("x".repeat(MAXIMUM_ROW_BYTES)))
            .is_err());
        assert_eq!(
            std::fs::read(directory.path().join("measurements.jsonl")).unwrap(),
            before
        );
    }
}
