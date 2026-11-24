//! Finite backing-store control for the state throughput campaign.
use latent_state::embedded::{
    AtomicBatch, CompactionLimits, EmbeddedStore, ExpectedRow, Family, FencedStoreError, RowKey,
    RowMutation, StoreError, StoreLimits,
};
use serde::Serialize;
use std::{
    fs::OpenOptions,
    io,
    time::{Duration, Instant},
};

#[path = "state_throughput/contention.rs"]
mod contention;

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
struct Reclamation {
    commits_with_pinned_view: Observation,
    file_bytes_before_view: u64,
    file_bytes_with_view: u64,
    refused_compaction_nanos: u64,
    compaction: serde_json::Value,
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
    same_key_writers: contention::PairedWriters,
    independent_key_writers: contention::PairedWriters,
    reclamation: Reclamation,
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
    let mut write_next = |previous: &mut Vec<u8>| {
        generation += 1;
        let mut next = vec![0; VALUE_BYTES];
        next[..8].copy_from_slice(&generation.to_le_bytes());
        store.apply(change(&primary, previous, &next))?;
        *previous = next;
        Ok(())
    };
    let commit = measure(|| write_next(&mut current))?;
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
    let same_key_writers = contention::measure(&store, &[key(1), key(1)])?;
    let independent_key_writers = contention::measure(&store, &[key(2), key(3)])?;
    let reclamation = measure_reclamation(&store, &path, &primary, &mut current, write_next)?;
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
        profile: "latent.state-throughput.embedded-file.v3",
        os: std::env::consts::OS,
        architecture: std::env::consts::ARCH,
        warmup_per_case: WARMUP,
        rows: ROWS,
        value_bytes: VALUE_BYTES,
        file_limit_bytes: FILE_LIMIT_BYTES,
        file_bytes_before,
        file_bytes_after,
        logical_read_value_bytes: SAMPLES * (ROWS + 6) * VALUE_BYTES,
        logical_written_value_bytes: 5 * SAMPLES * VALUE_BYTES,
        commit,
        stale_conflict,
        fresh_point_read,
        bounded_prefix_scan,
        same_key_writers,
        independent_key_writers,
        reclamation,
        reopen_and_verify,
    };
    println!("{}", serde_json::to_string(&report)?);
    Ok(())
}

fn measure_reclamation(
    store: &EmbeddedStore,
    path: &std::path::Path,
    primary: &RowKey,
    current: &mut Vec<u8>,
    mut write_next: impl FnMut(&mut Vec<u8>) -> Result<(), StoreError>,
) -> io::Result<Reclamation> {
    let file_bytes_before_view = std::fs::metadata(path)?.len();
    let original = current.clone();
    let pinned = store.snapshot().map_err(storage)?;
    let commits_with_pinned_view = measure(|| write_next(current))?;
    let file_bytes_with_view = std::fs::metadata(path)?.len();
    if pinned.get(primary).map_err(storage)?.as_deref() != Some(original.as_slice()) {
        return Err(storage(StoreError::Corrupt));
    }
    let began = Instant::now();
    let refused = store.compact_fenced(compaction_limits(), &[], || Ok::<_, StoreError>(()));
    let refused_compaction_nanos = elapsed_nanos(began)?;
    if !matches!(refused, Err(FencedStoreError::Store(StoreError::Capacity))) {
        return Err(io::Error::other("pinned view did not prevent compaction"));
    }
    drop(pinned);
    if store.live_views() != 0 {
        return Err(io::Error::other("the original read view did not retire"));
    }
    let expectation = ExpectedRow {
        key: primary.clone(),
        value: Some(current.clone()),
    };
    let compacted = store
        .compact_fenced(compaction_limits(), &[expectation], || {
            Ok::<_, StoreError>(())
        })
        .map_err(|error| io::Error::other(format!("bounded compaction failed: {error:?}")))?;
    Ok(Reclamation {
        commits_with_pinned_view,
        file_bytes_before_view,
        file_bytes_with_view,
        refused_compaction_nanos,
        compaction: serde_json::json!({
            "changed": compacted.changed,
            "elapsedMicros": compacted.elapsed_micros,
            "readBytes": compacted.read_bytes,
            "writeBytes": compacted.write_bytes,
            "ioOperations": compacted.io_operations,
            "peakFileBytes": compacted.peak_file_bytes,
            "observedFileBytes": compacted.observed_file_bytes,
            "scratchRequirementBytes": compacted.scratch_requirement_bytes,
            "scratchLimitBytes": compacted.scratch_limit_bytes,
        }),
    })
}

fn compaction_limits() -> CompactionLimits {
    CompactionLimits {
        deadline: Instant::now() + Duration::from_secs(5),
        maximum_read_bytes: 64 * 1024 * 1024,
        maximum_write_bytes: 64 * 1024 * 1024,
        maximum_io_operations: 8192,
        maximum_scratch_bytes: 8 * 1024 * 1024,
        maximum_growth_bytes: 2 * 1024 * 1024,
    }
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
        *sample = elapsed_nanos(began)?;
    }
    let nanos = samples
        .iter()
        .try_fold(0_u64, |total, sample| total.checked_add(*sample))
        .ok_or_else(|| io::Error::other("total duration exceeds u64"))?;
    Ok(summarize(&mut samples, nanos))
}

fn summarize(samples: &mut [u64], elapsed_nanos: u64) -> Observation {
    samples.sort_unstable();
    let count = samples.len();
    let percentile = |rank: usize| samples[(rank * count).div_ceil(100) - 1];
    Observation {
        samples: count,
        p50_nanos: percentile(50),
        p95_nanos: percentile(95),
        p99_nanos: percentile(99),
        operations_per_second: (1_000_000_000 * count as u64).checked_div(elapsed_nanos),
    }
}

fn elapsed_nanos(began: Instant) -> io::Result<u64> {
    u64::try_from(began.elapsed().as_nanos())
        .map_err(|_| io::Error::other("sample duration exceeds u64"))
}

fn storage(error: StoreError) -> io::Error {
    io::Error::other(format!("state throughput fixture failed: {error:?}"))
}
