//! Finite backing-store control for the state throughput campaign.
use latent_state::embedded::{
    AtomicBatch, EmbeddedStore, ExpectedRow, Family, RowKey, RowMutation, StoreError, StoreLimits,
};
use serde::Serialize;
use std::{fs::OpenOptions, io, time::Instant};

const WARMUP: usize = 5;
const SAMPLES: usize = 30;
const ROWS: usize = 16;
const VALUE_BYTES: usize = 128;
const FILE_LIMIT_BYTES: u64 = 32 * 1024 * 1024;
const PREFIX: &[u8] = b"benchmark/";

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Observation {
    samples: usize,
    p50_nanos: u64,
    p95_nanos: u64,
    p99_nanos: u64,
    operations_per_second: Option<u64>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Report {
    profile: &'static str,
    os: &'static str,
    architecture: &'static str,
    warmup_per_case: usize,
    rows: usize,
    value_bytes: usize,
    file_limit_bytes: u64,
    file_bytes_before: u64,
    file_bytes_after: u64,
    logical_read_value_bytes: usize,
    logical_written_value_bytes: usize,
    commit: Observation,
    stale_conflict: Observation,
    fresh_point_read: Observation,
    bounded_prefix_scan: Observation,
    reopen_and_verify: Observation,
}

fn main() -> io::Result<()> {
    let root = tempfile::tempdir()?;
    let path = root.path().join("state-throughput.redb");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)?;
    let (store, _) =
        EmbeddedStore::open_bounded_file(file, StoreLimits::default(), FILE_LIMIT_BYTES)
            .map_err(storage)?;
    store
        .apply(AtomicBatch {
            expectations: Vec::new(),
            mutations: (0..ROWS)
                .map(|index| RowMutation {
                    key: key(index),
                    value: Some(vec![0; VALUE_BYTES]),
                })
                .collect(),
        })
        .map_err(storage)?;
    let file_bytes_before = std::fs::metadata(&path)?.len();
    let primary = key(0);
    let mut generation = 0_u64;
    let mut current = vec![0; VALUE_BYTES];
    let commit = measure(|| {
        generation += 1;
        let mut next = vec![0; VALUE_BYTES];
        next[..8].copy_from_slice(&generation.to_le_bytes());
        store.apply(change(&primary, &current, &next))?;
        current = next;
        Ok(())
    })?;
    let stale = vec![0xff; VALUE_BYTES];
    let stale_conflict = measure(|| match store.apply(change(&primary, &stale, &stale)) {
        Err(StoreError::Conflict) => Ok(()),
        Err(error) => Err(error),
        Ok(()) => Err(StoreError::Corrupt),
    })?;
    let fresh_point_read = measure(|| {
        let view = store.snapshot()?;
        if view.get(&primary)?.as_deref() != Some(current.as_slice()) {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    })?;
    let bounded_prefix_scan = measure(|| {
        let view = store.snapshot()?;
        let page = view.scan_after(Family::State, PREFIX, None, ROWS, 4096)?;
        if page.rows.len() != ROWS || page.resume.is_some() {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    })?;
    let file_bytes_after = std::fs::metadata(&path)?.len();
    drop(store);
    let reopen_and_verify = measure(|| {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .map_err(|_| StoreError::Unavailable)?;
        let (reopened, _) =
            EmbeddedStore::open_bounded_file(file, StoreLimits::default(), FILE_LIMIT_BYTES)?;
        let view = reopened.snapshot()?;
        if view.get(&primary)?.as_deref() != Some(current.as_slice()) {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    })?;
    let report = Report {
        profile: "latent.state-throughput.embedded-file.v1",
        os: std::env::consts::OS,
        architecture: std::env::consts::ARCH,
        warmup_per_case: WARMUP,
        rows: ROWS,
        value_bytes: VALUE_BYTES,
        file_limit_bytes: FILE_LIMIT_BYTES,
        file_bytes_before,
        file_bytes_after,
        logical_read_value_bytes: SAMPLES * (ROWS + 2) * VALUE_BYTES,
        logical_written_value_bytes: SAMPLES * VALUE_BYTES,
        commit,
        stale_conflict,
        fresh_point_read,
        bounded_prefix_scan,
        reopen_and_verify,
    };
    println!("{}", serde_json::to_string(&report)?);
    Ok(())
}

fn key(index: usize) -> RowKey {
    RowKey {
        family: Family::State,
        key: format!("benchmark/{index:02}").into_bytes(),
    }
}

fn change(key: &RowKey, expected: &[u8], next: &[u8]) -> AtomicBatch {
    AtomicBatch {
        expectations: vec![ExpectedRow {
            key: key.clone(),
            value: Some(expected.to_vec()),
        }],
        mutations: vec![RowMutation {
            key: key.clone(),
            value: Some(next.to_vec()),
        }],
    }
}

fn measure(mut step: impl FnMut() -> Result<(), StoreError>) -> io::Result<Observation> {
    for _ in 0..WARMUP {
        step().map_err(storage)?;
    }
    let mut samples = [0; SAMPLES];
    for sample in &mut samples {
        let began = Instant::now();
        step().map_err(storage)?;
        *sample = u64::try_from(began.elapsed().as_nanos())
            .map_err(|_| io::Error::other("sample duration exceeds u64"))?;
    }
    let nanos = samples
        .iter()
        .try_fold(0_u64, |total, sample| total.checked_add(*sample))
        .ok_or_else(|| io::Error::other("total duration exceeds u64"))?;
    samples.sort_unstable();
    let percentile = |rank: usize| samples[(rank * SAMPLES).div_ceil(100) - 1];
    Ok(Observation {
        samples: SAMPLES,
        p50_nanos: percentile(50),
        p95_nanos: percentile(95),
        p99_nanos: percentile(99),
        operations_per_second: (1_000_000_000 * SAMPLES as u64).checked_div(nanos),
    })
}

fn storage(error: StoreError) -> io::Error {
    io::Error::other(format!("state throughput fixture failed: {error:?}"))
}
