//! Fixed source-owned observation thread; never profiles the 100k workload.
use std::fs::{File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::Path;
use std::sync::mpsc::{self, Sender};
use std::thread::JoinHandle;
use std::time::Duration;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use super::{Clock, Plan, Result};
use crate::standalone::measurements::read;

pub(super) struct Sampler {
    stop: Sender<()>,
    owner: Option<JoinHandle<Result<Value>>>,
}

impl Sampler {
    pub fn start(directory: &Path, plan: &Plan, clock: Clock) -> Result<Self> {
        let path = directory.join("sampler.jsonl");
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)?;
        let maximum = if plan.mode == "reopen" {
            20_000
        } else {
            40_000
        };
        let (stop, receiver) = mpsc::channel();
        let (ready, started) = mpsc::sync_channel(1);
        let owner = std::thread::Builder::new()
            .name("catalog-sampler".into())
            .spawn(move || {
                let result = run(file, &path, maximum, clock, &receiver, &ready);
                // Also wake the constructor after a failure before the first sample.
                let _ = ready.try_send(result.is_ok());
                result
            })?;
        let mut sampler = Self {
            stop,
            owner: Some(owner),
        };
        if !started.recv_timeout(Duration::from_secs(5))? {
            sampler.finish()?;
            return Err("catalog sampler startup failed".into());
        }
        Ok(sampler)
    }

    pub fn finish(&mut self) -> Result<Value> {
        let _ = self.stop.send(());
        self.owner
            .take()
            .ok_or("catalog sampler already joined")?
            .join()
            .map_err(|_| "catalog sampler panicked")?
    }
}

impl Drop for Sampler {
    fn drop(&mut self) {
        let _ = self.stop.send(());
        if let Some(owner) = self.owner.take() {
            let _ = owner.join();
        }
    }
}

fn run(
    file: File,
    path: &Path,
    maximum: u32,
    clock: Clock,
    stop: &mpsc::Receiver<()>,
    ready: &mpsc::SyncSender<bool>,
) -> Result<Value> {
    let mut file = BufWriter::with_capacity(64 * 1024, file);
    let mut count = 0_u32;
    let mut bytes = 0_u64;
    let mut digest = Sha256::new();
    let mut identity = None;
    let mut previous = None;
    let mut gap_min = u128::MAX;
    let mut gap_max = 0_u128;
    loop {
        if count >= maximum {
            return Err("catalog sampler count bound".into());
        }
        let sample = sample(clock)?;
        let current = (sample[2], sample[3]);
        if identity.is_some_and(|prior| prior != current) {
            return Err("catalog sampler identity changed".into());
        }
        identity = Some(current);
        if let Some(prior) = previous {
            let gap = sample[0] - prior;
            gap_min = gap_min.min(gap);
            gap_max = gap_max.max(gap);
        }
        previous = Some(sample[0]);
        let mut row = serde_json::to_vec(&sample.map(|value| value.to_string()))?;
        row.push(b'\n');
        bytes = bytes
            .checked_add(row.len() as u64)
            .ok_or("catalog sampler byte overflow")?;
        if row.len() > 256 || bytes > 16 * 1024 * 1024 {
            return Err("catalog sampler byte bound".into());
        }
        file.write_all(&row)?;
        file.flush()?;
        digest.update(&row);
        count += 1;
        if count == 1 {
            let _ = ready.try_send(true);
        }
        match stop.recv_timeout(Duration::from_millis(100)) {
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Ok(()) | Err(mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }
    file.flush()?;
    file.get_ref().sync_all()?;
    let identity = identity.ok_or("catalog sampler missing identity")?;
    Ok(
        json!({"enabled":true,"joined":true,"source":"proc-self-status-and-stat",
        "requested_period_nanos":"100000000","samples":count.to_string(),
        "process_id":identity.0.to_string(),"start_time_ticks":identity.1.to_string(),
        "minimum_start_gap_nanos":(count>1).then(||gap_min.to_string()),
        "maximum_start_gap_nanos":(count>1).then(||gap_max.to_string()),
        "file":{"path":path.file_name().and_then(|name|name.to_str()).ok_or("catalog sampler path")?,
            "bytes":bytes.to_string(),"sha256":format!("sha256:{:x}",digest.finalize())}}),
    )
}

fn stat() -> Result<[u128; 4]> {
    let bytes = read(Path::new("/proc/self/stat"), 4096)?;
    let text = std::str::from_utf8(&bytes)?;
    let (pid, _) = text
        .split_once(' ')
        .ok_or("catalog sampler stat identity")?;
    let fields = text[text.rfind(')').ok_or("catalog sampler stat command")? + 1..]
        .split_whitespace()
        .collect::<Vec<_>>();
    let number = |index: usize| -> Result<u128> {
        Ok(fields
            .get(index)
            .ok_or("catalog sampler stat fields")?
            .parse()?)
    };
    let pid = pid.parse::<u128>()?;
    if pid != u128::from(std::process::id()) {
        return Err("catalog sampler foreign PID".into());
    }
    Ok([pid, number(19)?, number(11)?, number(12)?])
}

fn sample(clock: Clock) -> Result<[u128; 8]> {
    let began = clock.elapsed();
    let before = stat()?;
    let bytes = read(Path::new("/proc/self/status"), 128 * 1024)?;
    let text = std::str::from_utf8(&bytes)?;
    let memory = |key: &str| -> Result<u128> {
        let mut rows = text
            .lines()
            .filter_map(|line| line.split_once(':'))
            .filter(|(name, _)| *name == key);
        let (_, value) = rows.next().ok_or("catalog sampler memory missing")?;
        if rows.next().is_some() {
            return Err("catalog sampler memory duplicate".into());
        }
        let fields = value.split_whitespace().collect::<Vec<_>>();
        if fields.len() != 2 || fields[1] != "kB" {
            return Err("catalog sampler memory unit".into());
        }
        fields[0]
            .parse::<u128>()?
            .checked_mul(1024)
            .ok_or_else(|| "catalog sampler memory overflow".into())
    };
    let rss = memory("VmRSS")?;
    let hwm = memory("VmHWM")?;
    let after = stat()?;
    if before[..2] != after[..2] || hwm < rss {
        return Err("catalog sampler process changed".into());
    }
    Ok([
        began,
        clock.elapsed(),
        before[0],
        before[1],
        rss,
        hwm,
        after[2],
        after[3],
    ])
}
