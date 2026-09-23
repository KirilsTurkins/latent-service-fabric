use super::{Binding, Call, DevelopmentTestArtifact, PolicyStore};
use crate::http_fixture::{Fixture, Peer};
use latent_capabilities::broker::{
    http::HTTP_CAPABILITY,
    io::{IoLimits, IoRuntime},
    pools::{ProviderPoolLimits, ProviderPools},
    ActivationCapabilityBroker,
};
use latent_http::{
    HttpAddressPolicy, HttpDestination, HttpLimits, HttpProvider, HttpProviderConfig,
    HttpResolution,
};
use latent_policy::capability::HttpOrigin;
use serde_json::json;
use std::{
    collections::BTreeSet,
    sync::Arc,
    time::{Duration, Instant},
};

pub(super) struct Installed {
    pub provider: HttpProvider,
    peer: Peer,
    pools: Arc<ProviderPools>,
    io: Arc<IoRuntime>,
}
impl Installed {
    pub fn check_idle(&self) -> Result<(), &'static str> {
        let snapshot = self.io.snapshot();
        if snapshot != latent_capabilities::broker::io::IoSnapshot::default() {
            return Err("portable-http-io-resource-leak");
        }
        let pools = self
            .pools
            .snapshot()
            .map_err(|_| "portable-http-pool-snapshot")?;
        if pools.pending_requests != 0
            || pools.running_requests != 0
            || pools.active_connections != 0
        {
            return Err("portable-http-pool-resource-leak");
        }
        Ok(())
    }
    pub async fn shutdown(&mut self) -> Result<usize, &'static str> {
        let snapshot = self
            .pools
            .shutdown(Instant::now() + Duration::from_secs(3))
            .await
            .map_err(|_| "portable-http-pool-cleanup")?;
        if !snapshot.is_clean() {
            return Err("portable-http-pool-cleanup");
        }
        self.check_idle()?;
        self.peer.shutdown().await
    }
}
pub(super) fn install(
    broker: &Arc<ActivationCapabilityBroker>,
    policies: &PolicyStore,
    artifact: &DevelopmentTestArtifact,
    calls: &[Call],
    fixture: &Fixture,
) -> Result<(Binding, Installed), &'static str> {
    // Bind first. An occupied port cannot cause a test to contact another peer.
    let peer = Peer::start(fixture)?;
    let io = Arc::new(IoRuntime::new(IoLimits::default()).map_err(|_| "portable-http-io")?);
    let pools = Arc::new(
        ProviderPools::new(
            broker.clone(),
            io.clone(),
            tokio::runtime::Handle::current(),
            ProviderPoolLimits::default(),
        )
        .map_err(|_| "portable-http-pools")?,
    );
    let origin = HttpOrigin {
        scheme: "http".into(),
        host: "127.0.0.1".into(),
        port: fixture.port,
    };
    let provider = HttpProvider::install(
        pools.clone(),
        "portable-http",
        1,
        0,
        HttpProviderConfig {
            format_version: 1,
            limits: HttpLimits::default(),
            public_roots: false,
            extra_roots: vec![],
            destinations: vec![HttpDestination {
                origin: origin.clone(),
                addresses: HttpAddressPolicy {
                    networks: vec!["127.0.0.1/32".parse().expect("fixed loopback")],
                    special_addresses: vec!["127.0.0.1".parse().expect("fixed loopback")],
                },
                resolution: HttpResolution::Static {
                    addresses: vec!["127.0.0.1".parse().expect("fixed loopback")],
                },
                allowed_request_headers: vec![],
                redirect_destinations: vec![],
            }],
        },
        &[],
    )
    .map_err(|_| "portable-http-provider")?;
    let methods = fixture
        .exchanges
        .iter()
        .map(|item| &item.method)
        .collect::<BTreeSet<_>>();
    let paths = fixture
        .exchanges
        .iter()
        .map(|item| &item.path)
        .collect::<BTreeSet<_>>();
    let binding = super::install(
        policies,
        artifact,
        calls,
        "http",
        HTTP_CAPABILITY,
        provider.reference(),
        &["send"],
        &json!({"kind":"http","origins":[origin],"methods":methods,"paths":paths,"pathPrefixes":[]}),
    )?;
    Ok((
        binding,
        Installed {
            provider,
            peer,
            pools,
            io,
        },
    ))
}
