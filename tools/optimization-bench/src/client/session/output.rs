use std::{
    fs::{File, OpenOptions},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
    time::Instant,
};

use serde::Serialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use super::{
    nanos,
    plan::{MAXIMUM_BYTES, PREFIX},
    Result,
};

pub struct Output {
    root: PathBuf,
    attempts: BufWriter<File>,
    events: BufWriter<File>,
    attempts_hash: Sha256,
    attempts_bytes: u64,
    event_bytes: u64,
    event_count: u32,
    remaining: u64,
    digest: String,
    started: Instant,
}

impl Output {
    pub fn new(root: PathBuf, digest: String, started: Instant) -> Result<Self> {
        std::fs::create_dir_all(&root).map_err(|_| "session-output-directory")?;
        if ["attempts.jsonl", "events.jsonl", "summary.json"]
            .iter()
            .any(|name| root.join(name).exists())
        {
            return Err("session-output-exists");
        }
        Ok(Self {
            attempts: BufWriter::new(create(&root.join("attempts.jsonl"))?),
            events: BufWriter::new(create(&root.join("events.jsonl"))?),
            root,
            attempts_hash: Sha256::new(),
            attempts_bytes: 0,
            event_bytes: 0,
            event_count: 0,
            remaining: MAXIMUM_BYTES,
            digest,
            started,
        })
    }

    pub fn attempt<T: Serialize>(&mut self, row: &T) -> Result<()> {
        let bytes = encode(row, 20 * 1024)?;
        self.charge(bytes.len(), false)?;
        self.attempts
            .write_all(&bytes)
            .map_err(|_| "session-attempt-write")?;
        self.attempts_hash.update(&bytes);
        self.attempts_bytes += bytes.len() as u64;
        Ok(())
    }

    pub fn event(&mut self, event: &str, command: Option<u32>, payload: &Value) -> Result<()> {
        let value = json!({"schema":format!("{PREFIX}event.v1"),"event":event,
            "event_ordinal":self.event_count,"command_ordinal":command,
            "process_id":std::process::id(),"plan_sha256":self.digest,
            "session_elapsed_nanos":nanos(self.started.elapsed()).to_string(),"payload":payload});
        let bytes = encode(&value, 2 * 1024 * 1024)?;
        self.charge(bytes.len(), event == "failed")?;
        let offset = self.event_bytes;
        self.events
            .write_all(&bytes)
            .map_err(|_| "session-event-write")?;
        self.event_bytes += bytes.len() as u64;
        self.event_count += 1;
        self.flush()?;
        let ack = json!({"schema":format!("{PREFIX}ack.v1"),"event":event,"command_ordinal":command,
            "process_id":std::process::id(),"plan_sha256":self.digest,
            "event_record":{"path":"events.jsonl","offset":offset.to_string(),"bytes":bytes.len().to_string(),
                "sha256":super::super::record::digest(&bytes)},
            "attempts":self.attempt_ref()});
        let bytes = encode(&ack, 4096)?;
        let mut stdout = std::io::stdout().lock();
        stdout
            .write_all(&bytes)
            .and_then(|()| stdout.flush())
            .map_err(|_| "session-ack-write")
    }

    pub fn summary(&mut self, value: &Value) -> Result<Value> {
        self.flush()?;
        self.attempts
            .get_ref()
            .sync_all()
            .map_err(|_| "session-attempt-sync")?;
        self.events
            .get_ref()
            .sync_all()
            .map_err(|_| "session-event-sync")?;
        let bytes = encode(value, 16 * 1024)?;
        self.charge(bytes.len(), true)?;
        let mut file = create(&self.root.join("summary.json"))?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| "session-summary-write")?;
        Ok(
            json!({"path":"summary.json","bytes":bytes.len().to_string(),
            "sha256":super::super::record::digest(&bytes)}),
        )
    }

    pub fn attempt_ref(&self) -> Value {
        json!({"path":"attempts.jsonl","bytes":self.attempts_bytes.to_string(),
            "sha256":format!("sha256:{:x}",self.attempts_hash.clone().finalize())})
    }

    fn charge(&mut self, bytes: usize, final_record: bool) -> Result<()> {
        let remaining = self
            .remaining
            .checked_sub(bytes as u64)
            .ok_or("session-output-byte-bound")?;
        if !final_record && remaining < 32 * 1024 {
            return Err("session-output-byte-bound");
        }
        self.remaining = remaining;
        Ok(())
    }

    fn flush(&mut self) -> Result<()> {
        self.attempts
            .flush()
            .and_then(|()| self.events.flush())
            .map_err(|_| "session-output-flush")
    }
}

fn create(path: &Path) -> Result<File> {
    OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|_| "session-exclusive-output")
}

pub fn encode<T: Serialize>(value: &T, limit: usize) -> Result<Vec<u8>> {
    struct Limited {
        data: Vec<u8>,
        maximum: usize,
    }
    impl Write for Limited {
        fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
            let next = self
                .data
                .len()
                .checked_add(bytes.len())
                .filter(|size| *size < self.maximum)
                .ok_or_else(|| std::io::Error::other("session-row-byte-bound"))?;
            if next > self.data.capacity() {
                self.data
                    .try_reserve_exact(next - self.data.len())
                    .map_err(std::io::Error::other)?;
            }
            self.data.extend_from_slice(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let mut writer = Limited {
        data: Vec::new(),
        maximum: limit,
    };
    serde_json::to_writer(&mut writer, value).map_err(|_| "session-row-byte-bound")?;
    writer.data.push(b'\n');
    Ok(writer.data)
}
