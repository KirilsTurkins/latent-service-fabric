use super::{
    config, Arc, AtomicBool, BoxFuture, Entry, Generation, Inner, Ordering, SecretError, SecretSpec,
};
use crate::SecretSource;
use std::time::Instant;

struct Loading(Arc<Inner>);
impl Drop for Loading {
    fn drop(&mut self) {
        self.0.loading.store(false, Ordering::Release);
    }
}
struct Waiter(Arc<AtomicBool>);
impl Drop for Waiter {
    fn drop(&mut self) {
        self.0.store(true, Ordering::Release);
    }
}

pub(super) fn start(
    inner: &Arc<Inner>,
    expected: u64,
    specs: Vec<SecretSpec>,
) -> Result<BoxFuture<'static, Result<u64, SecretError>>, SecretError> {
    start_inner(inner, expected, specs, None)
}

pub(super) fn start_before(
    inner: &Arc<Inner>,
    expected: u64,
    specs: Vec<SecretSpec>,
    deadline: Instant,
) -> Result<BoxFuture<'static, Result<u64, SecretError>>, SecretError> {
    start_inner(inner, expected, specs, Some(deadline))
}

fn start_inner(
    inner: &Arc<Inner>,
    expected: u64,
    specs: Vec<SecretSpec>,
    deadline: Option<Instant>,
) -> Result<BoxFuture<'static, Result<u64, SecretError>>, SecretError> {
    inner.check()?;
    if specs.capacity() > inner.limits.maximum_references {
        return Err(SecretError::Unavailable);
    }
    config::validate_specs(&specs, inner.limits, &inner.allowlist)?;
    let next = expected.checked_add(1).ok_or(SecretError::Unavailable)?;
    if inner
        .state
        .try_lock()
        .map_err(|_| SecretError::Unavailable)?
        .number
        != expected
    {
        return Err(SecretError::Unavailable);
    }
    inner
        .loading
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| SecretError::Unavailable)?;
    let loading = Loading(inner.clone());
    let charge = inner.reserve_generation()?;
    // One candidate may overflow the retained-generation cap before rejection;
    // its entire bounded source buffer remains separately prepaid.
    let scratch = inner
        .pools
        .reserve_protocol_metadata(inner.limits.maximum_value_bytes + 4096)?;
    let environment = specs
        .iter()
        .any(|s| matches!(s.source, SecretSource::Environment { .. }));
    let environment_memory = if environment {
        Some(
            inner
                .pools
                .reserve_protocol_metadata(inner.limits.maximum_environment_bytes)?,
        )
    } else {
        None
    };
    let cancelled = Arc::new(AtomicBool::new(false));
    let waiter = Waiter(cancelled.clone());
    let owner = inner.clone();
    let work = move || {
        let _loading = loading;
        let _scratch = scratch;
        let _environment_memory = environment_memory;
        let check = || {
            owner.check()?;
            if cancelled.load(Ordering::Acquire) {
                return Err(SecretError::Unavailable);
            }
            Ok(())
        };
        check()?;
        let environment = if environment {
            Some(crate::environment::capture(
                owner.limits.maximum_environment_bytes,
                &check,
            )?)
        } else {
            None
        };
        let entries = load_entries(
            &owner,
            specs,
            environment.as_ref().map(|e| e.as_slice()),
            &check,
        )?;
        let generation = Arc::new(Generation {
            number: next,
            entries,
            _charge: charge,
        });
        let mut state = owner
            .state
            .try_lock()
            .map_err(|_| SecretError::Unavailable)?;
        check()?;
        if state.number != expected {
            return Err(SecretError::Unavailable);
        }
        // This finite swap is the sole installation boundary. A cancellation
        // arriving after it cannot roll back the new generation; status reports
        // the installed number even when the original waiter has gone away.
        let old = state.generation.replace(generation);
        state.number = next;
        drop(state);
        drop(old);
        Ok(next)
    };
    if let Some(deadline) = deadline {
        let pools = inner.pools.clone();
        return Ok(Box::pin(async move {
            let _waiter = waiter;
            pools
                .control_blocking_before(deadline, work)
                .await?
                .wait()
                .await?
        }));
    }
    let job = inner.pools.control_blocking(work)?;
    Ok(Box::pin(async move {
        let _waiter = waiter;
        job.wait().await?
    }))
}

fn load_entries(
    owner: &Inner,
    specs: Vec<SecretSpec>,
    environment: Option<&[u8]>,
    check: &impl Fn() -> Result<(), SecretError>,
) -> Result<Vec<Entry>, SecretError> {
    let mut entries = Vec::with_capacity(specs.len());
    let mut bytes = 0_usize;
    for spec in specs {
        check()?;
        let value = match &spec.source {
            SecretSource::File { name } => {
                owner.root.read(name, owner.limits.maximum_value_bytes)?
            }
            SecretSource::Environment { key } => crate::environment::get(
                environment.expect("environment reservation"),
                key,
                owner.limits.maximum_value_bytes,
            )?,
        };
        check()?;
        bytes = bytes
            .checked_add(value.capacity())
            .ok_or(SecretError::Unavailable)?;
        if bytes > owner.limits.maximum_generation_bytes {
            return Err(SecretError::Unavailable);
        }
        let expiry = super::expiry(&spec, owner.clock.sample())?;
        entries.push(Entry {
            spec,
            bytes: value,
            expiry,
            expired: AtomicBool::new(false),
        });
    }
    Ok(entries)
}
