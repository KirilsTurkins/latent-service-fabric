#[cfg(any(test, feature = "development-outbound"))]
use crate::StreamResolution;
use crate::{
    connection::{self, Socket},
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
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

#[derive(Clone)]
pub struct StreamProvider {
    pub(crate) inner: Arc<Inner>,
}
pub(crate) struct Inner {
    pub config: StreamProviderConfig,
    pub kernel_mode: crate::kernel::Mode,
    pub installed: InstalledProvider,
    pub pools: Arc<ProviderPools>,
    pub resolvers: Vec<Option<Resolver>>,
    pub tls: Vec<Option<Arc<crate::tls::InstalledTls>>>,
    pub connections: Arc<crate::connection_registry::Registry>,
    #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
    native: Mutex<Option<crate::kernel::native::NativeOwner>>,
    #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
    pub(crate) native_bank: Option<Arc<crate::kernel::native::StreamBank>>,
    _configuration: ProviderMetadata,
}
#[cfg(any(test, feature = "development-outbound"))]
pub(crate) type ProviderInstaller = fn(
    Arc<ProviderPools>,
    &str,
    u64,
    u64,
    StreamProviderConfig,
) -> Result<StreamProvider, StreamError>;

#[cfg(any(test, feature = "development-outbound"))]
#[derive(Clone, Copy)]
enum TlsInstallMode {
    Qualified,
    #[cfg(test)]
    AccountingReference,
}
#[cfg(any(test, feature = "development-outbound"))]
impl TlsInstallMode {
    fn is_reference(self) -> bool {
        match self {
            Self::Qualified => false,
            #[cfg(test)]
            Self::AccountingReference => true,
        }
    }
}

impl StreamProvider {
    /// Actual descriptor/constructor experiment for an isolated candidate image.
    /// It retains unproved kernel retirement and cannot enable normal install.
    #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
    pub async fn install_kernel_constructor_for_qualification(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: StreamProviderConfig,
        deadline: Instant,
    ) -> Result<Self, StreamError> {
        let provider = Self::install_with_modes(
            Arc::clone(&pools),
            logical_id,
            epoch,
            expected_epoch,
            config,
            TlsInstallMode::Qualified,
            crate::kernel::Mode::RetainUnproved,
        )?;
        let owner =
            crate::kernel::native::start(pools, &provider.inner.installed, deadline).await?;
        if Instant::now() >= deadline {
            drop(owner);
            return Err(error(StreamErrorCode::Timeout));
        }
        *provider
            .inner
            .native
            .try_lock()
            .map_err(crate::snapshot_lock_error)? = Some(owner);
        Ok(provider)
    }
    /// Explicit consumer for a NEW source-matched retirement-observation image.
    /// It cannot enable normal sockets or return any native capacity. The old
    /// constructor entry above never mints an observation descriptor.
    #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
    pub async fn install_kernel_return_observation_for_qualification(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: StreamProviderConfig,
        deadline: Instant,
    ) -> Result<Self, StreamError> {
        let provider = Self::install_with_modes(
            Arc::clone(&pools),
            logical_id,
            epoch,
            expected_epoch,
            config,
            TlsInstallMode::Qualified,
            crate::kernel::Mode::RetainUnproved,
        )?;
        let owner = crate::kernel::native::start_with_retirement_observation(
            pools,
            &provider.inner.installed,
            deadline,
        )
        .await?;
        if Instant::now() >= deadline {
            drop(owner);
            return Err(error(StreamErrorCode::Timeout));
        }
        *provider
            .inner
            .native
            .try_lock()
            .map_err(crate::snapshot_lock_error)? = Some(owner);
        Ok(provider)
    }
    /// Fixed qualification-only consumption of the original 512 KiB bank.
    /// Connection, bootstrap/descriptor remainder and observer costs remain
    /// quarantined. This cannot select normal provider installation.
    #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
    pub async fn install_kernel_bank_reclamation_for_qualification(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: StreamProviderConfig,
        deadline: Instant,
    ) -> Result<Self, StreamError> {
        let provider = Self::install_with_modes(
            Arc::clone(&pools),
            logical_id,
            epoch,
            expected_epoch,
            config,
            TlsInstallMode::Qualified,
            crate::kernel::Mode::RetainUnproved,
        )?;
        let owner = crate::kernel::native::start_with_bank_reclamation(
            pools,
            &provider.inner.installed,
            deadline,
        )
        .await?;
        if Instant::now() >= deadline {
            drop(owner);
            return Err(error(StreamErrorCode::Timeout));
        }
        *provider
            .inner
            .native
            .try_lock()
            .map_err(crate::snapshot_lock_error)? = Some(owner);
        Ok(provider)
    }
    /// Observe the same native close that ordinary retirement initiates. Its
    /// fixed result is not an affine native refund proof or full cost claim.
    /// Holding it keeps the original cleanup/result charge.
    #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
    pub async fn retire_kernel_constructor_for_qualification(
        &self,
        deadline: Instant,
    ) -> Result<latent_capabilities::broker::pools::StreamKernelCloseReceipt, StreamError> {
        let owner = self
            .inner
            .native
            .try_lock()
            .map_err(crate::snapshot_lock_error)?
            .take()
            .ok_or_else(|| error(StreamErrorCode::Unsupported))?;
        // The native slot is already empty: normal retirement cannot submit a
        // duplicate close. It still retires all the original other resources.
        self.retire();
        let job = owner.close_before(deadline)?;
        tokio::select! {
            biased;
            () = tokio::time::sleep_until(deadline.into()) => Err(error(StreamErrorCode::Timeout)),
            result = job.wait() => {
                let receipt = result?;
                if Instant::now() >= deadline {
                    drop(receipt);
                    Err(error(StreamErrorCode::Timeout))
                } else {
                    Ok(receipt)
                }
            }
        }
    }
    /// Normal installation refuses before protected inputs, resolver/socket
    /// allocation or provider publication until an actual platform is qualified.
    pub fn install(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: StreamProviderConfig,
    ) -> Result<Self, StreamError> {
        let input = (pools, logical_id, epoch, expected_epoch);
        let kernel_mode = crate::kernel::Mode::RetainUnproved;
        config.validate()?;
        crate::kernel::require_supported_profile()?;
        #[cfg(any(test, feature = "development-outbound"))]
        {
            let (pools, logical_id, epoch, expected_epoch) = input;
            Self::install_with_modes(
                pools,
                logical_id,
                epoch,
                expected_epoch,
                config,
                TlsInstallMode::Qualified,
                kernel_mode,
            )
        }
        #[cfg(not(any(test, feature = "development-outbound")))]
        {
            drop((input, kernel_mode));
            Err(error(StreamErrorCode::Unsupported))
        }
    }

    // Current-kernel ownership experiment; no normal or development binary can
    // select a passing kernel accounting certificate through this entry.
    #[cfg(test)]
    pub(crate) fn install_kernel_for_accounting_reference(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: StreamProviderConfig,
    ) -> Result<Self, StreamError> {
        Self::install_with_modes(
            pools,
            logical_id,
            epoch,
            expected_epoch,
            config,
            TlsInstallMode::Qualified,
            crate::kernel::Mode::RetainUnproved,
        )
    }

    /// Explicit nonproduction logical-library reference. FD/future destruction
    /// here is not final kernel retirement and grants no accounting qualification.
    /// Removing this feature gate requires the architecture/security and actual
    /// complete platform/provider gates; normal callers must use `install`.
    #[cfg(any(test, feature = "development-outbound"))]
    pub fn install_for_qualification(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: StreamProviderConfig,
    ) -> Result<Self, StreamError> {
        Self::install_with_tls_mode(
            pools,
            logical_id,
            epoch,
            expected_epoch,
            config,
            TlsInstallMode::Qualified,
        )
    }

    // Only unit-test code can select this reference experiment. It does not
    // exist in a normal or development-outbound provider binary.
    #[cfg(test)]
    pub(crate) fn install_tls_for_accounting_reference(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: StreamProviderConfig,
    ) -> Result<Self, StreamError> {
        Self::install_with_tls_mode(
            pools,
            logical_id,
            epoch,
            expected_epoch,
            config,
            TlsInstallMode::AccountingReference,
        )
    }

    #[cfg(any(test, feature = "development-outbound"))]
    fn install_with_tls_mode(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: StreamProviderConfig,
        tls_mode: TlsInstallMode,
    ) -> Result<Self, StreamError> {
        Self::install_with_modes(
            pools,
            logical_id,
            epoch,
            expected_epoch,
            config,
            tls_mode,
            crate::kernel::Mode::LogicalReference,
        )
    }

    #[cfg(any(test, feature = "development-outbound"))]
    fn install_with_modes(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: StreamProviderConfig,
        tls_mode: TlsInstallMode,
        kernel_mode: crate::kernel::Mode,
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
        let mut tls = Vec::with_capacity(config.destinations.len());
        for destination in &config.destinations {
            tls.push(match &destination.tls {
                Some(input) => {
                    if !crate::tls::ACCOUNTING_QUALIFIED && !tls_mode.is_reference() {
                        return Err(error(StreamErrorCode::Unsupported));
                    }
                    let metadata = pools.reserve_protocol_metadata(crate::tls::ROOT_ALLOWANCE)?;
                    Some(Arc::new(crate::tls::InstalledTls {
                        config: crate::tls::configure(input)?,
                        _metadata: metadata,
                    }))
                }
                None => None,
            });
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
        let connections = crate::connection_registry::Registry::new(&pools)?;
        Ok(Self {
            inner: Arc::new(Inner {
                config,
                kernel_mode,
                installed,
                pools,
                resolvers,
                tls,
                connections,
                #[cfg(target_os = "linux")]
                native: Mutex::new(None),
                #[cfg(target_os = "linux")]
                native_bank: None, // No normal/qualification consumer selects it yet.
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
        #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
        {
            let owner = self
                .inner
                .native
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .take();
            drop(owner);
        }
        for index in 0..32 {
            let connection = self.inner.connections.snapshot(index).ok().flatten();
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
            let connection = self.inner.connections.snapshot(index)?;
            if let Some(connection) = connection {
                let usage = connection.usage()?;
                result.owners += usage.owners;
                result.connections += usage.connections;
                result.pending_operations += usage.pending_operations;
                result.retained_chunks += usage.retained_chunks;
                result.accepted_write_bytes += usage.accepted_write_bytes;
                #[cfg(any(test, feature = "development-outbound"))]
                {
                    result.input_budget_bytes += usage.input_budget_bytes;
                }
                result.delivered_read_bytes += usage.delivered_read_bytes;
            }
        }
        let quarantined = self.inner.installed.quarantined_connections();
        result.owners += quarantined;
        result.connections += quarantined;
        Ok(result)
    }

    pub(crate) fn maintenance_step(&self, now: Instant) {
        // Same existing paid maintenance turn, including failed predials that
        // have not entered the32-slot Connection registry. No new executor.
        #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
        if self.inner.native_bank.is_some() {
            self.inner
                .pools
                .maintain_stream_quarantine(&self.inner.installed, now);
        }
        for index in 0..32 {
            let connection = match self.inner.connections.snapshot(index) {
                Ok(connection) => connection,
                Err(_) => continue, // Existing bounded next turn; no owner dropped.
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
        for index in 0..crate::connection_registry::CAPACITY {
            if let Ok(Some(connection)) = self.connections.snapshot(index) {
                connection.abort(StreamErrorCode::Revoked);
            }
        }
        for resolver in self.resolvers.iter().flatten() {
            let _ = resolver.close();
        }
    }
}
