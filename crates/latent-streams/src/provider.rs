#[cfg(any(test, feature = "development-outbound"))]
use crate::StreamResolution;
use crate::{
    connection::{self, Connection, Socket},
    error, StreamError, StreamErrorCode, StreamProviderConfig,
};
use latent_capabilities::broker::{
    network::{OutboundStreamInvoker, StreamConnectRequest, StreamInvocation},
    pools::{InstalledProvider, ProviderClient, ProviderMetadata, ProviderPools},
    CapabilitySession, ProviderReference,
};
#[cfg(any(test, feature = "development-outbound"))]
use latent_capabilities::broker::{
    network::{STREAM_CAPABILITY, STREAM_PROFILE},
    pools::ProviderSetup,
    ProviderBudgetRequirement, ProviderConfiguration,
};
#[cfg(any(test, feature = "development-outbound"))]
use latent_core::BudgetDimension;
use latent_network::dns::Resolver;
#[cfg(any(test, feature = "development-outbound"))]
use sha2::{Digest, Sha256};
use std::{
    sync::{Arc, Mutex, Weak},
    time::{Duration, Instant},
};

#[derive(Clone)]
pub struct StreamProvider {
    pub(crate) inner: Arc<Inner>,
}
pub(crate) struct Inner {
    pub config: StreamProviderConfig,
    pub installed: InstalledProvider,
    pub pools: Arc<ProviderPools>,
    pub resolvers: Vec<Option<Resolver>>,
    pub connections: Mutex<[Weak<Connection>; 32]>,
    _configuration: ProviderMetadata,
}
impl StreamProvider {
    /// Explicit nonproduction qualification entry. Removing this feature gate
    /// requires the architecture/security and real-component profile gates.
    #[cfg(any(test, feature = "development-outbound"))]
    pub fn install_for_qualification(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: StreamProviderConfig,
    ) -> Result<Self, StreamError> {
        config.validate()?;
        let limits = pools.limits()?;
        if limits.maximum_running_requests > 64
            || limits.maximum_running_per_tenant > 16
            || limits.maximum_running_per_provider > 32
            || limits.maximum_pending_requests > 128
            || limits.maximum_requests_per_tenant > 32
            || limits.maximum_requests_per_provider > 64
        {
            return Err(error(StreamErrorCode::InvalidInput));
        }
        // Fixed owner table, all eight resolver caches and serialization are
        // prepaid before creating those retained allocations.
        let configuration = pools.reserve_protocol_metadata(128 * 1024)?;
        let encoded =
            serde_json::to_vec(&config).map_err(|_| error(StreamErrorCode::InvalidInput))?;
        if encoded.len() > 16 * 1024 {
            return Err(error(StreamErrorCode::InvalidInput));
        }
        let mut hash = Sha256::new();
        hash.update(b"lsf-outbound-streams-v1\0");
        hash.update(&encoded);
        let digest = format!(
            "sha256:{:x}",
            latent_core::digest::HexDigest(hash.finalize())
        );
        let restriction = serde_json::to_vec(&serde_json::json!({
            "operations":["connect","read","write","ready","inspect","shutdown","close","chunk-bytes"],
            "resources":{"kind":"stream","endpoints":config.destinations.iter().map(|d| &d.endpoint).collect::<Vec<_>>()}
        })).map_err(|_| error(StreamErrorCode::InvalidInput))?;
        let mut resolvers = Vec::with_capacity(config.destinations.len());
        for destination in &config.destinations {
            resolvers.push(match &destination.resolution {
                StreamResolution::Static { .. } => None,
                StreamResolution::Dns {
                    server,
                    maximum_ttl_seconds,
                } => Some(
                    Resolver::new(
                        destination.endpoint.host.clone(),
                        *server,
                        *maximum_ttl_seconds,
                        destination.addresses.clone(),
                        32,
                    )
                    .map_err(connection::network_error)?,
                ),
            });
        }
        let installed = pools.install(
            ProviderSetup {
                logical_id,
                credentials: &[],
                authority: ProviderConfiguration {
                    capability: STREAM_CAPABILITY,
                    profile: STREAM_PROFILE,
                    configuration_digest: &digest,
                    configuration_epoch: epoch,
                    restriction_json: &restriction,
                    minimum_call_charges: &[ProviderBudgetRequirement {
                        operation: "connect",
                        dimension: BudgetDimension::OutboundRequests,
                        minimum: 1,
                    }],
                },
            },
            expected_epoch,
        )?;
        Ok(Self {
            inner: Arc::new(Inner {
                config,
                installed,
                pools,
                resolvers,
                connections: Mutex::new(std::array::from_fn(|_| Weak::new())),
                _configuration: configuration,
            }),
        })
    }
    #[must_use]
    pub fn reference(&self) -> ProviderReference {
        self.inner.installed.reference()
    }
    /// Admission retirement and physical abort are separate. The latter does
    /// not release charges held by a pending operation or retained chunk.
    pub fn retire(&self) {
        self.inner.installed.retire();
        for index in 0..32 {
            let connection = self
                .inner
                .connections
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)[index]
                .upgrade();
            if let Some(connection) = connection {
                connection.abort(StreamErrorCode::Revoked);
            }
        }
        for resolver in self.inner.resolvers.iter().flatten() {
            let _ = resolver.close();
        }
    }
    pub fn usage(&self) -> Result<crate::StreamUsage, StreamError> {
        let mut result = crate::StreamUsage {
            retired: self.inner.installed.is_retired(),
            ..Default::default()
        };
        for index in 0..32 {
            let connection = self
                .inner
                .connections
                .try_lock()
                .map_err(|_| error(StreamErrorCode::Exhausted))?[index]
                .upgrade();
            if let Some(connection) = connection {
                let usage = connection.usage()?;
                result.owners += usage.owners;
                result.connections += usage.connections;
                result.pending_operations += usage.pending_operations;
                result.retained_chunks += usage.retained_chunks;
                result.accepted_write_bytes += usage.accepted_write_bytes;
                result.delivered_read_bytes += usage.delivered_read_bytes;
            }
        }
        Ok(result)
    }

    pub(crate) fn maintenance_step(&self, now: Instant) {
        for index in 0..32 {
            let connection = match self.inner.connections.try_lock() {
                Ok(slots) => slots[index].upgrade(),
                Err(std::sync::TryLockError::WouldBlock) => continue,
                Err(std::sync::TryLockError::Poisoned(slots)) => {
                    let connection = slots.into_inner()[index].upgrade();
                    if let Some(connection) = connection {
                        connection.abort(StreamErrorCode::Exhausted);
                    }
                    continue;
                }
            };
            if let Some(connection) = connection {
                connection.maintenance_step(now);
            }
        }
    }
}
impl OutboundStreamInvoker for StreamProvider {
    fn inspect_node_usage(
        &self,
    ) -> Result<
        Option<latent_capabilities::broker::network::StreamNodeUsage>,
        latent_core::PlatformError,
    > {
        let usage = self.usage().map_err(crate::inspection_unavailable)?;
        Ok(Some(
            latent_capabilities::broker::network::StreamNodeUsage {
                configuration_epoch: self.reference().configuration_epoch(),
                stopped: usage.retired,
                owners: usage.owners,
                connections: usage.connections,
                pending_operations: usage.pending_operations,
                retained_chunks: usage.retained_chunks,
                live_accepted_write_bytes: usage.accepted_write_bytes,
                live_delivered_read_bytes: usage.delivered_read_bytes,
                ..Default::default()
            },
        ))
    }

    fn start(
        &self,
        session: &CapabilitySession,
        request: StreamConnectRequest,
    ) -> Result<StreamInvocation, StreamError> {
        request.endpoint.validate()?;
        if self.inner.installed.is_retired() || !session.uses_provider(&self.reference())? {
            return Err(error(StreamErrorCode::Denied));
        }
        let index = self
            .inner
            .config
            .destinations
            .iter()
            .position(|d| d.endpoint == request.endpoint)
            .ok_or_else(|| error(StreamErrorCode::Denied))?;
        let original = session.deadline()?;
        let now = Instant::now();
        let mut deadline = original.min(
            now + Duration::from_millis(u64::from(
                self.inner.config.limits.absolute_timeout_millis,
            )),
        );
        if let Some(timeout) = request.timeout_millis {
            if timeout == 0 || timeout > 10_000 {
                return Err(error(StreamErrorCode::InvalidInput));
            }
            deadline = deadline.min(now + Duration::from_millis(u64::from(timeout)));
        }
        let scope = session.reserve_stream()?;
        let client: Arc<ProviderClient<Socket>> = self.inner.pools.client(
            &self.inner.installed,
            u16::try_from(index).map_err(|_| error(StreamErrorCode::InvalidInput))?,
        )?;
        let admission = self.inner.pools.admit_until(&client, session, deadline)?;
        let inner = Arc::clone(&self.inner);
        Ok(Box::pin(connection::connect(
            inner, scope, index, client, admission, deadline,
        )))
    }
}
impl Drop for Inner {
    fn drop(&mut self) {
        self.installed.retire();
        let slots = self
            .connections
            .get_mut()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        for connection in slots.iter().filter_map(Weak::upgrade) {
            connection.abort(StreamErrorCode::Revoked);
        }
        for resolver in self.resolvers.iter().flatten() {
            let _ = resolver.close();
        }
    }
}
