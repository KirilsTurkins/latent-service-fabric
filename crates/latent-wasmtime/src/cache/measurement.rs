//! Identical, explicitly invoked lookup probe for the two exact-source builds.
//! This measures generic cache bookkeeping, not Wasmtime compilation or RPC.

mod input;
mod output;

use std::hint::black_box;
use std::sync::Arc;
use std::time::{Duration, Instant};

use rustix::time::{clock_getres, clock_gettime, ClockId};
use serde_json::json;

use super::{CacheLimits, PrepareAccess, PreparedCache};
use crate::preparation_observer::{sample_thread_cpu, PreparationThreadCpuInterval};

/// This exact non-inlined frame is the allocation attribution boundary. It is
/// called once, only for measured hits. Preallocated tag stores and checksum
/// accumulation are included; all per-tag verification follows the timers.
#[inline(never)]
fn measured_cache_hits(
    cache: &PreparedCache<u16>,
    keys: &[String],
    trace: &[u16],
    observed: &mut [u16],
) -> u64 {
    let mut checksum = 0_u64;
    for (position, (&index, observed)) in trace.iter().zip(observed).enumerate() {
        let runtime = black_box(cache).get(black_box(&keys[usize::from(index)]));
        let tag = runtime.as_deref().copied().unwrap_or(u16::MAX);
        *observed = black_box(tag);
        checksum = checksum.wrapping_add((u64::from(tag) + 1) * (position as u64 + 1));
        drop(black_box(runtime));
    }
    black_box(checksum)
}

fn warmup_cache_hits(cache: &PreparedCache<u16>, keys: &[String], trace: &[u16]) {
    for &index in trace {
        let runtime = cache.get(&keys[usize::from(index)]).expect("warmup hit");
        assert_eq!(*black_box(&runtime), index);
        drop(black_box(runtime));
    }
}

#[test]
#[ignore = "explicit finite paired Linux cache lookup measurement only"]
fn cache_lookup_collector() {
    collect().expect("cache lookup collector");
}

fn collect() -> Result<(), Box<dyn std::error::Error>> {
    let input = input::Input::load()?;
    let plan = &input.plan;
    let keys: Vec<_> = (0..plan.capacity)
        .map(|index| format!("cache-key-{index:04x}"))
        .collect();
    let cache = Arc::new(PreparedCache::new(CacheLimits {
        maximum_entries: plan.capacity,
        maximum_source_bytes: plan.capacity * 2,
        maximum_metadata_bytes: plan.capacity * 3,
        maximum_compiled_image_bytes: plan.capacity * 4,
        maximum_concurrent_preparations: 1,
    })?);
    for (index, key) in keys.iter().enumerate() {
        let PrepareAccess::Compile(reservation) = cache.begin(key.clone(), 2, 3)? else {
            return Err("unexpected prepopulation hit".into());
        };
        reservation.publish(Arc::new(u16::try_from(index)?), 4)?;
    }
    let warmup = plan.trace(plan.warmup_hits);
    warmup_cache_hits(&cache, &keys, &warmup);
    let trace = plan.trace(plan.measured_hits);
    let mut trace_bytes = Vec::with_capacity(trace.len() * 2);
    for index in &trace {
        trace_bytes.extend_from_slice(&index.to_le_bytes());
    }
    input::write_new(&input.output.join("trace.bin"), &trace_bytes)?;
    let trace_sha256 = input::sha256(&trace_bytes);
    let expected_checksum = trace
        .iter()
        .enumerate()
        .fold(0_u64, |sum, (position, tag)| {
            sum.wrapping_add((u64::from(*tag) + 1) * (position as u64 + 1))
        });
    let mut observed = vec![u16::MAX; trace.len()];
    let before = cache.snapshot();
    input::verify_occupancy(&before, plan.capacity)?;
    let ready_task = sample_thread_cpu().ok_or("ready task identity unavailable")?;
    let identity = ready_task.identity;
    let ready = json!({
        "schema": "latent.optimization.cache-lookup-ready.v1", "event": "ready",
        "process_id": std::process::id(), "plan_sha256": input.plan_sha256,
        "identity_sha256": input.identity_sha256, "trace_sha256": trace_sha256,
        "thread_identity": identity, "observation_hold_millis": 100,
    });
    output::emit(&ready)?;
    std::thread::sleep(Duration::from_millis(100));

    let resolution = output::nanos(clock_getres(ClockId::ThreadCPUTime))?;
    let before_task = sample_thread_cpu().ok_or("before task CPU unavailable")?;
    let cpu_before = output::nanos(clock_gettime(ClockId::ThreadCPUTime))?;
    let started = Instant::now();
    let checksum = measured_cache_hits(&cache, &keys, &trace, &mut observed);
    let elapsed_nanos = started.elapsed().as_nanos();
    let cpu_after = output::nanos(clock_gettime(ClockId::ThreadCPUTime))?;
    let after_task = sample_thread_cpu().ok_or("after task CPU unavailable")?;

    let after = cache.snapshot();
    input::verify_occupancy(&after, plan.capacity)?;
    let mut expected_after = before.clone();
    expected_after.hits += u64::try_from(plan.measured_hits)?;
    if before_task.identity != identity
        || after_task.identity != identity
        || after_task.user_ticks < before_task.user_ticks
        || after_task.system_ticks < before_task.system_ticks
        || cpu_after < cpu_before
        || resolution == 0
        || elapsed_nanos == 0
        || after != expected_after
        || observed != trace
        || checksum != expected_checksum
    {
        return Err("cache lookup semantic or clock verification failed".into());
    }
    let result = json!({
        "schema": "latent.optimization.cache-lookup-result.v1",
        "event": "measurement-complete", "process_id": std::process::id(),
        "plan_sha256": input.plan_sha256, "identity_sha256": input.identity_sha256,
        "trace_sha256": trace_sha256, "thread_identity": identity,
        "observation_hold_millis": 100, "outcome": "passed",
        "warmup_hits": plan.warmup_hits, "measured_hits": plan.measured_hits,
        "elapsed_nanos": elapsed_nanos.to_string(),
        "cpu": {"clock": "CLOCK_THREAD_CPUTIME_ID", "resolution_nanos": resolution.to_string(),
                "before_nanos": cpu_before.to_string(), "after_nanos": cpu_after.to_string()},
        "coarse_thread_cpu": PreparationThreadCpuInterval { before: before_task, after: after_task },
        "before": before, "after": after, "checksum": checksum.to_string(),
        "expected_checksum": expected_checksum.to_string(), "all_tags_verified": true,
        "trace_bytes": trace_bytes.len().to_string(),
    });
    output::emit(&result)?;
    std::thread::sleep(Duration::from_millis(100));
    Ok(())
}
