mod auth;
mod cache;
mod read;
mod remote;
use super::{memory, Result, SecretError, VaultConfig};
use latent_capabilities::broker::{
    pools::{InstalledProvider, ProviderMetadata, ProviderPools, ProviderSetup},
    secrets::{ProviderCredential, SECRETS_CAPABILITY},
    ProviderConfiguration, ProviderReference,
};
use latent_http::protocol::ProtocolTransport;
use latent_secrets::SecretClock;
use sha2::{Digest, Sha256};
use std::sync::{
    atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering},
    Arc, Mutex,
};

pub const VAULT_SECRETS_PROFILE: &str = "vault-kv-v2-secrets-v1";
#[derive(Clone)]
pub struct VaultSecretProvider {
    inner: Arc<Inner>,
}
struct Inner {
    config: VaultConfig,
    pools: Arc<ProviderPools>,
    installed: InstalledProvider,
    transport: ProtocolTransport,
    credentials: Vec<Arc<dyn ProviderCredential>>,
    clock: Arc<dyn SecretClock>,
    expiry: Vec<cache::Expiry>,
    plaintext: Arc<memory::Plaintext>,
    cache: Mutex<cache::Cache>,
    closed: AtomicBool,
    active: AtomicUsize,
    hits: AtomicU64,
    requests: AtomicU64,
    rejected: AtomicU64,
    epoch: u64,
    _metadata: ProviderMetadata,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct VaultSnapshot {
    pub configuration_epoch: u64,
    pub references: usize,
    pub cached_values: usize,
    pub cached_bytes: usize,
    pub retained_plaintext_bytes: usize,
    pub active_reads: usize,
    pub cache_hits: u64,
    pub remote_read_attempts: u64,
    pub rejected_reads: u64,
    pub closed: bool,
}
impl VaultSecretProvider {
    pub fn install(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: VaultConfig,
        credentials: Vec<Arc<dyn ProviderCredential>>,
        clock: Arc<dyn SecretClock>,
    ) -> Result<Self> {
        config.validate()?;
        if credentials.is_empty() || credentials.capacity() > 16 {
            return Err(SecretError::PermissionDenied);
        }
        let metadata = pools.reserve_protocol_metadata(
            65536
                + 3 * config
                    .transport
                    .extra_roots
                    .iter()
                    .map(Vec::capacity)
                    .sum::<usize>(),
        )?;
        let mut hash = Sha256::new();
        hash.update(b"vault-kv-v2-secrets-v1\0");
        hash.update(config.identity()?.as_bytes());
        for (i, credential) in credentials.iter().enumerate() {
            let scope = credential.scope();
            if scope.provider_id != logical_id
                || scope.origin != config.transport.destinations[0].origin
                || !crate::config::text(&scope.tenant.0, 128)
                || !crate::config::text(credential.reference(), 256)
                || credentials[..i]
                    .iter()
                    .any(|c| c.scope().tenant == scope.tenant)
            {
                return Err(SecretError::PermissionDenied);
            }
            for value in [&scope.tenant.0, credential.reference()] {
                hash.update((value.len() as u64).to_le_bytes());
                hash.update(value.as_bytes());
            }
        }
        if config
            .references
            .iter()
            .any(|r| !credentials.iter().any(|c| c.scope().tenant.0 == r.tenant))
        {
            return Err(SecretError::PermissionDenied);
        }
        let digest = format!("sha256:{:x}", hash.finalize());
        let mut references: Vec<_> = config
            .references
            .iter()
            .map(|r| r.reference.as_str())
            .collect();
        references.sort_unstable();
        references.dedup();
        let restriction = serde_json::to_vec(&serde_json::json!({
            "operations":["read"], "resources":{"kind":"secrets","references":references}
        }))
        .map_err(|_| SecretError::Unavailable)?;
        let expiry = config
            .references
            .iter()
            .map(|r| cache::Expiry::new(r.expires_at_unix_millis, clock.sample()))
            .collect::<Result<Vec<_>>>()?;
        let cache = Mutex::new(cache::Cache::new(config.references.len()));
        let plaintext = memory::Plaintext::new(config.limits.maximum_plaintext_bytes);
        let installed = pools.install(
            ProviderSetup {
                logical_id,
                credentials: &[],
                authority: ProviderConfiguration {
                    capability: SECRETS_CAPABILITY,
                    profile: VAULT_SECRETS_PROFILE,
                    configuration_digest: &digest,
                    configuration_epoch: epoch,
                    restriction_json: &restriction,
                    minimum_call_charges: &[],
                },
            },
            expected_epoch,
        )?;
        let transport = ProtocolTransport::new(pools.clone(), &installed, config.transport.clone())
            .map_err(|_| SecretError::Unavailable)?;
        Ok(Self {
            inner: Arc::new(Inner {
                config,
                pools,
                installed,
                transport,
                credentials,
                clock,
                expiry,
                plaintext,
                cache,
                closed: AtomicBool::new(false),
                active: AtomicUsize::new(0),
                hits: AtomicU64::new(0),
                requests: AtomicU64::new(0),
                rejected: AtomicU64::new(0),
                epoch,
                _metadata: metadata,
            }),
        })
    }
    #[must_use]
    pub fn reference(&self) -> ProviderReference {
        self.inner.installed.reference()
    }
    pub fn snapshot(&self) -> Result<VaultSnapshot> {
        let cache = self
            .inner
            .cache
            .try_lock()
            .map_err(|_| SecretError::Unavailable)?;
        let (cached_values, cached_bytes) = cache.usage();
        Ok(VaultSnapshot {
            configuration_epoch: self.inner.epoch,
            references: self.inner.config.references.len(),
            cached_values,
            cached_bytes,
            retained_plaintext_bytes: self.inner.plaintext.bytes.load(Ordering::Acquire),
            active_reads: self.inner.active.load(Ordering::Acquire),
            cache_hits: self.inner.hits.load(Ordering::Acquire),
            remote_read_attempts: self.inner.requests.load(Ordering::Acquire),
            rejected_reads: self.inner.rejected.load(Ordering::Acquire),
            closed: self.inner.closed.load(Ordering::Acquire),
        })
    }
    /// Lazy expiry never authorizes stale reads. Operators may also erase idle
    /// expired cache ownership explicitly without a per-reference timer.
    pub fn prune_expired(&self) -> Result<()> {
        self.inner
            .cache
            .try_lock()
            .map_err(|_| SecretError::Unavailable)?
            .prune(self.inner.clock.sample());
        Ok(())
    }
    pub fn close(&self) {
        self.inner.closed.store(true, Ordering::Release);
        if let Ok(mut cache) = self.inner.cache.try_lock() {
            cache.clear();
        }
    }
}
impl Inner {
    fn check(&self) -> Result<()> {
        if self.closed.load(Ordering::Acquire) {
            return Err(SecretError::Unavailable);
        }
        Ok(())
    }
    fn credential(&self, index: usize) -> &dyn ProviderCredential {
        let tenant = &self.config.references[index].tenant;
        self.credentials
            .iter()
            .find(|c| &c.scope().tenant.0 == tenant)
            .expect("validated credential scope")
            .as_ref()
    }
}
fn tick(counter: &AtomicU64) {
    let _ = counter.fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| {
        Some(n.saturating_add(1))
    });
}
