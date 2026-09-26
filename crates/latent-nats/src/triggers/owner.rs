use super::{monitor::Counters, TriggerConfig, TriggerMonitor};
use crate::{
    network::{self, Connection},
    EventError, NatsCredential, Result,
};
use latent_capabilities::broker::{
    events::EVENTS_CAPABILITY,
    pools::{InstalledProvider, ProviderClient, ProviderPools, ProviderSetup},
    ProviderConfiguration,
};
use sha2::{Digest, Sha256};
use std::{
    sync::{atomic::AtomicU64, Arc, Mutex},
    time::Instant,
};

pub const NATS_TRIGGER_PROFILE: &str = "nats-jetstream-pull-v1";
pub(super) struct Tenant {
    pub credential: usize,
    pub bindings: Vec<usize>,
    pub cursor: usize,
    pub client: Option<Arc<ProviderClient<Connection>>>,
}
/// One caller-driven shared poller. Configuration retains no per-trigger task,
/// listener, connection or execution cell. Remote positions belong to consumers.
pub struct NatsTriggers {
    pub(super) config: TriggerConfig,
    pub(super) credentials: Vec<NatsCredential>,
    pub(super) tenants: Vec<Tenant>,
    pub(super) next_tenant: usize,
    pub(super) retry_after: Vec<Option<Instant>>,
    pub(super) tls: Arc<rustls::ClientConfig>,
    pub(super) namespace: String,
    pub(super) sequence: u64,
    pub(super) installed: InstalledProvider,
    pub(super) pools: Arc<ProviderPools>,
    pub(super) monitor: TriggerMonitor,
}
impl NatsTriggers {
    pub fn install(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: TriggerConfig,
        credentials: Vec<NatsCredential>,
    ) -> Result<Self> {
        config.validate()?;
        if credentials.is_empty() || credentials.capacity() > 8 {
            return Err(EventError::InvalidEvent);
        }
        let metadata = pools.reserve_protocol_metadata(
            65536
                + config.bindings.len() * 2048
                + 6 * config.extra_roots.iter().map(Vec::capacity).sum::<usize>(),
        )?;
        let destination = config.endpoint.credential_destination();
        let mut hash = Sha256::new();
        hash.update(b"lsf-nats-trigger-v1\0");
        // Hash the canonical configuration incrementally. Retaining another
        // complete JSON document would double the peak metadata allocation.
        serde_json::to_writer(HashWriter(&mut hash), &config)
            .map_err(|_| EventError::InvalidEvent)?;
        for (i, c) in credentials.iter().enumerate() {
            let scope = c.secret.scope();
            if scope.provider_id != logical_id
                || scope.destination != destination
                || !crate::config::text(&scope.tenant.0, 128)
                || !crate::config::text(c.secret.reference(), 256)
                || c.username
                    .as_ref()
                    .is_some_and(|v| !crate::config::text(v, 128) || v.capacity() > 128)
                || credentials[..i]
                    .iter()
                    .any(|old| old.secret.scope().tenant == scope.tenant)
                || !config.bindings.iter().any(|b| b.tenant == scope.tenant.0)
            {
                return Err(EventError::PermissionDenied);
            }
            for value in [
                scope.tenant.0.as_str(),
                c.secret.reference(),
                c.username.as_deref().unwrap_or(""),
            ] {
                hash.update((value.len() as u64).to_le_bytes());
                hash.update(value.as_bytes());
            }
        }
        if config.bindings.iter().any(|b| {
            !credentials
                .iter()
                .any(|c| c.secret.scope().tenant.0 == b.tenant)
        }) {
            return Err(EventError::PermissionDenied);
        }
        let tls = network::tls_for(config.public_roots, &config.extra_roots)?;
        let digest = format!("sha256:{:x}", hash.finalize());
        let tenants = tenant_rows(&config, &credentials);
        let mut entropy = [0; 16];
        getrandom::fill(&mut entropy).map_err(|_| EventError::Unavailable)?;
        let namespace = format!("_INBOX.LSF.{:032x}", u128::from_le_bytes(entropy));
        let monitor = TriggerMonitor(Arc::new(Counters {
            epoch,
            triggers: config.bindings.len(),
            active: AtomicU64::new(0),
            pulls: AtomicU64::new(0),
            executions: AtomicU64::new(0),
            acknowledged: AtomicU64::new(0),
            retries: AtomicU64::new(0),
            terminated: AtomicU64::new(0),
            exhausted: AtomicU64::new(0),
            uncertain: AtomicU64::new(0),
            rejected: AtomicU64::new(0),
            attempts: AtomicU64::new(0),
            reuses: AtomicU64::new(0),
            last: Mutex::new(None),
            _metadata: metadata,
        }));
        let installed = pools.install(
            ProviderSetup {
                logical_id,
                credentials: &[],
                authority: ProviderConfiguration {
                    capability: EVENTS_CAPABILITY,
                    profile: NATS_TRIGGER_PROFILE,
                    configuration_digest: &digest,
                    configuration_epoch: epoch,
                    restriction_json: b"{\"operations\":[]}",
                    minimum_call_charges: &[],
                },
            },
            expected_epoch,
        )?;
        Ok(Self {
            retry_after: vec![None; config.bindings.len()],
            config,
            credentials,
            tenants,
            next_tenant: 0,
            tls,
            namespace,
            sequence: 0,
            installed,
            pools,
            monitor,
        })
    }
    #[must_use]
    pub fn monitor(&self) -> TriggerMonitor {
        self.monitor.clone()
    }
    #[must_use]
    pub fn config(&self) -> &TriggerConfig {
        &self.config
    }
    pub fn close_idle(&self) -> Result<()> {
        for tenant in &self.tenants {
            if let Some(client) = &tenant.client {
                client.close_idle()?;
            }
        }
        Ok(())
    }
}
fn tenant_rows(config: &TriggerConfig, credentials: &[NatsCredential]) -> Vec<Tenant> {
    credentials
        .iter()
        .enumerate()
        .map(|(credential, c)| Tenant {
            credential,
            bindings: config
                .bindings
                .iter()
                .enumerate()
                .filter_map(|(i, b)| (b.tenant == c.secret.scope().tenant.0).then_some(i))
                .collect(),
            cursor: 0,
            client: None,
        })
        .collect()
}
struct HashWriter<'a>(&'a mut Sha256);
impl std::io::Write for HashWriter<'_> {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.0.update(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
