use crate::{config, SecretError, SecretLimits, SecretPurpose, SecretSpec};
use latent_capabilities::broker::pools::{ProviderMetadata, ProviderPools};
use latent_core::{BoxFuture, ClockSample};
use latent_protected_files::ProtectedRoot;
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use zeroize::Zeroizing;

mod credential;
mod reload;

pub trait SecretClock: Send + Sync {
    fn sample(&self) -> ClockSample;
}
pub struct SystemSecretClock;
impl SecretClock for SystemSecretClock {
    fn sample(&self) -> ClockSample {
        ClockSample::system_now()
    }
}

pub(crate) struct Entry {
    pub spec: SecretSpec,
    pub bytes: Zeroizing<Vec<u8>>,
    pub expiry: Option<Instant>,
    pub expired: AtomicBool,
}
impl Entry {
    pub fn check_expiry(&self, now: ClockSample) -> Result<(), SecretError> {
        if self.expired.load(Ordering::Acquire)
            || self.expiry.is_some_and(|t| now.monotonic() >= t)
            || self
                .spec
                .expires_at_unix_millis
                .is_some_and(|t| now.unix_millis() >= t)
        {
            self.expired.store(true, Ordering::Release);
            return Err(SecretError::Expired);
        }
        Ok(())
    }
}
pub(crate) struct Generation {
    pub number: u64,
    pub entries: Vec<Entry>,
    _charge: GenerationCharge,
}
struct Retention {
    generations: AtomicUsize,
    maximum: usize,
}
struct GenerationCharge {
    retained: Arc<Retention>,
    _bytes: ProviderMetadata,
    _metadata: ProviderMetadata,
}
impl Drop for GenerationCharge {
    fn drop(&mut self) {
        self.retained.generations.fetch_sub(1, Ordering::AcqRel);
    }
}
pub(crate) struct State {
    pub generation: Option<Arc<Generation>>,
    pub number: u64,
}
pub(crate) struct Inner {
    pub root: ProtectedRoot,
    pub pools: Arc<ProviderPools>,
    pub limits: SecretLimits,
    pub clock: Arc<dyn SecretClock>,
    pub state: Mutex<State>,
    allowlist: Vec<String>,
    retained: Arc<Retention>,
    loading: AtomicBool,
    closed: AtomicBool,
    _metadata: ProviderMetadata,
}

#[derive(Clone)]
pub struct LocalSecretStore {
    pub(crate) inner: Arc<Inner>,
}
#[derive(Clone, Copy, Debug)]
pub struct SecretSnapshot {
    pub generation: u64,
    pub references: usize,
    pub retained_generations: usize,
    pub reserved_generation_bytes: usize,
    pub loading: bool,
    pub closed: bool,
}
impl LocalSecretStore {
    /// Installation and reload are explicit trusted control operations. No
    /// environment enumeration or filesystem operation occurs on guest reads.
    pub fn open(
        pools: Arc<ProviderPools>,
        root: PathBuf,
        limits: SecretLimits,
        environment_allowlist: Vec<String>,
        clock: Arc<dyn SecretClock>,
    ) -> Result<BoxFuture<'static, Result<Self, SecretError>>, SecretError> {
        limits.validate()?;
        if root.as_os_str().len() > 4096
            || root.capacity() > 4096
            || environment_allowlist.len() > 64
            || environment_allowlist.capacity() > 64
            || environment_allowlist.iter().enumerate().any(|(i, k)| {
                !config::environment_key(k)
                    || k.capacity() > 128
                    || environment_allowlist[..i].contains(k)
            })
        {
            return Err(SecretError::Unavailable);
        }
        let metadata = pools.reserve_protocol_metadata(65536)?;
        let worker_pool = pools.clone();
        let job = worker_pool.control_blocking(move || {
            let root = ProtectedRoot::open(&root)?;
            Ok::<_, latent_core::PlatformError>(Self {
                inner: Arc::new(Inner {
                    root,
                    pools,
                    limits,
                    clock,
                    state: Mutex::new(State {
                        generation: None,
                        number: 0,
                    }),
                    allowlist: environment_allowlist,
                    retained: Arc::new(Retention {
                        generations: AtomicUsize::new(0),
                        maximum: limits.maximum_generations,
                    }),
                    loading: AtomicBool::new(false),
                    closed: AtomicBool::new(false),
                    _metadata: metadata,
                }),
            })
        })?;
        Ok(Box::pin(async move { Ok(job.wait().await??) }))
    }
    pub fn reload(
        &self,
        expected_generation: u64,
        specs: Vec<SecretSpec>,
    ) -> Result<BoxFuture<'static, Result<u64, SecretError>>, SecretError> {
        reload::start(&self.inner, expected_generation, specs)
    }
    pub fn snapshot(&self) -> Result<SecretSnapshot, SecretError> {
        let state = self
            .inner
            .state
            .try_lock()
            .map_err(|_| SecretError::Unavailable)?;
        let count = self.inner.retained.generations.load(Ordering::Acquire);
        Ok(SecretSnapshot {
            generation: state.number,
            references: state.generation.as_ref().map_or(0, |g| g.entries.len()),
            retained_generations: count,
            reserved_generation_bytes: count * self.inner.limits.maximum_generation_bytes,
            loading: self.inner.loading.load(Ordering::Acquire),
            closed: self.inner.closed.load(Ordering::Acquire),
        })
    }
    /// Reject future reads/reloads immediately. Already retained generations are
    /// zeroized only when their actual outstanding owners are destroyed.
    pub fn close(&self) {
        self.inner.closed.store(true, Ordering::Release);
        if let Ok(mut state) = self.inner.state.try_lock() {
            state.generation.take();
        }
    }
}
impl Inner {
    pub fn check(&self) -> Result<(), SecretError> {
        if self.closed.load(Ordering::Acquire) {
            return Err(SecretError::Unavailable);
        }
        Ok(())
    }
    pub fn generation(&self) -> Result<Arc<Generation>, SecretError> {
        self.check()?;
        self.state
            .try_lock()
            .map_err(|_| SecretError::Unavailable)?
            .generation
            .clone()
            .ok_or(SecretError::NotFound)
    }
    fn reserve_generation(&self) -> Result<GenerationCharge, SecretError> {
        let bytes = self
            .pools
            .reserve_protocol_metadata(self.limits.maximum_generation_bytes)?;
        let metadata = self
            .pools
            .reserve_protocol_metadata(8192 + self.limits.maximum_references * 2048)?;
        self.retained
            .generations
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| {
                (n < self.retained.maximum).then_some(n + 1)
            })
            .map_err(|_| SecretError::Unavailable)?;
        Ok(GenerationCharge {
            retained: self.retained.clone(),
            _bytes: bytes,
            _metadata: metadata,
        })
    }
    pub fn with_current<T>(
        &self,
        generation: &Arc<Generation>,
        index: usize,
        use_value: impl FnOnce(&Entry) -> Result<T, SecretError>,
    ) -> Result<T, SecretError> {
        self.check()?;
        let state = self
            .state
            .try_lock()
            .map_err(|_| SecretError::Unavailable)?;
        self.check()?;
        if state.number != generation.number
            || state
                .generation
                .as_ref()
                .is_none_or(|g| !Arc::ptr_eq(g, generation))
        {
            return Err(SecretError::Unavailable);
        }
        let entry = generation.entries.get(index).ok_or(SecretError::NotFound)?;
        entry.check_expiry(self.clock.sample())?;
        use_value(entry)
    }
}

fn expiry(spec: &SecretSpec, sample: ClockSample) -> Result<Option<Instant>, SecretError> {
    spec.expires_at_unix_millis
        .map(|t| {
            sample
                .monotonic()
                .checked_add(Duration::from_millis(
                    t.saturating_sub(sample.unix_millis()),
                ))
                .ok_or(SecretError::Unavailable)
        })
        .transpose()
}
