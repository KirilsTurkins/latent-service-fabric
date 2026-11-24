use super::{change, elapsed_nanos, storage, summarize, Observation, SAMPLES, VALUE_BYTES, WARMUP};
use latent_state::embedded::{AtomicBatch, EmbeddedStore, RowKey, StoreError};
use serde::Serialize;
use std::{
    io,
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

const WRITERS: usize = 2;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct PairedWriters {
    workers: usize,
    measured_rounds: usize,
    elapsed_nanos: u64,
    attempted: usize,
    committed: Observation,
    conflicts: Option<Observation>,
}

pub(super) fn measure(
    store: &EmbeddedStore,
    keys: &[RowKey; WRITERS],
) -> io::Result<PairedWriters> {
    let same_key = keys[0] == keys[1];
    let expected_commits = if same_key { 1 } else { WRITERS };
    let mut commits = Vec::with_capacity(SAMPLES * expected_commits);
    let mut conflicts = Vec::with_capacity(SAMPLES * (WRITERS - expected_commits));
    let mut elapsed = 0_u64;
    thread::scope(|scope| {
        let (complete, outcomes) = mpsc::sync_channel(WRITERS);
        let senders: [_; WRITERS] = std::array::from_fn(|_| {
            let (send, receive) = mpsc::sync_channel::<(AtomicBatch, Instant)>(1);
            let complete = complete.clone();
            scope.spawn(move || {
                while let Ok((batch, submitted)) = receive.recv() {
                    let result = store.apply(batch);
                    let elapsed = elapsed_nanos(submitted);
                    if complete.send((result, elapsed)).is_err() {
                        break;
                    }
                }
            });
            send
        });
        drop(complete);
        for round in 0..WARMUP + SAMPLES {
            let began = Instant::now();
            let view = store.snapshot().map_err(storage)?;
            let mut batches = Vec::with_capacity(WRITERS);
            for key in keys {
                let previous = view
                    .get(key)
                    .map_err(storage)?
                    .ok_or_else(|| storage(StoreError::Corrupt))?;
                let mut next = previous.clone();
                let count = counter(&previous)?
                    .checked_add(1)
                    .ok_or_else(|| storage(StoreError::Capacity))?;
                next[..8].copy_from_slice(&count.to_le_bytes());
                batches.push(change(key, &previous, &next));
            }
            drop(view);
            let submitted = Instant::now();
            for (sender, batch) in senders.iter().zip(batches) {
                sender.send((batch, submitted)).map_err(io::Error::other)?;
            }
            let measured = round >= WARMUP;
            let mut committed = 0;
            for _ in 0..WRITERS {
                let (result, latency) = outcomes
                    .recv_timeout(Duration::from_secs(5))
                    .map_err(io::Error::other)?;
                let latency = latency?;
                match result {
                    Ok(()) => {
                        committed += 1;
                        if measured {
                            commits.push(latency);
                        }
                    }
                    Err(StoreError::Conflict) => {
                        if measured {
                            conflicts.push(latency);
                        }
                    }
                    Err(error) => return Err(storage(error)),
                }
            }
            if committed != expected_commits {
                return Err(io::Error::other(
                    "paired writes returned an unexpected outcome",
                ));
            }
            if measured {
                elapsed = elapsed
                    .checked_add(elapsed_nanos(began)?)
                    .ok_or_else(|| io::Error::other("paired write duration exceeds u64"))?;
            }
        }
        Ok::<_, io::Error>(())
    })?;

    let view = store.snapshot().map_err(storage)?;
    for key in keys {
        let bytes = view
            .get(key)
            .map_err(storage)?
            .ok_or_else(|| storage(StoreError::Corrupt))?;
        if counter(&bytes)? != (WARMUP + SAMPLES) as u64 {
            return Err(io::Error::other(
                "paired writes produced an unexpected value",
            ));
        }
    }
    Ok(PairedWriters {
        workers: WRITERS,
        measured_rounds: SAMPLES,
        elapsed_nanos: elapsed,
        attempted: SAMPLES * WRITERS,
        committed: summarize(&mut commits, elapsed),
        conflicts: (!conflicts.is_empty()).then(|| summarize(&mut conflicts, elapsed)),
    })
}

fn counter(bytes: &[u8]) -> io::Result<u64> {
    if bytes.len() != VALUE_BYTES {
        return Err(storage(StoreError::Corrupt));
    }
    let encoded = bytes[..8].try_into().map_err(io::Error::other)?;
    Ok(u64::from_le_bytes(encoded))
}
