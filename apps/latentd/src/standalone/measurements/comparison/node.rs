use std::path::Path;
use std::time::{Duration, Instant};

use latent_artifacts::{ArtifactRepository, CapsuleArtifact};
use latent_node::LocalActivationJournalConfig;
use latent_testkit::conformance::WorkCounts;
use latent_testkit::resources::{CurrentProcessOwnerProbe, ProbeLimits};
use latent_wire::invocation::{proto, InvocationServiceClient};
use serde_json::{json, Value};
use tonic::transport::Channel;

use super::super::{fixtures::Fixture, node::projection, platform};
use super::{Plan, Result};
use crate::standalone::{start::Catalogs, RuntimeThreads, ShutdownReport, StandaloneNode};

mod publication;

pub(super) struct Node {
    pub owner: StandaloneNode,
    pub fixture: Fixture,
    pub config: Value,
    pub runtime_config: latent_wasmtime::WasmtimeConfig,
    pub startup: Value,
    pub work: WorkCounts,
    pub maximum_commands: u64,
    channel: Channel,
    pub(super) artifacts: std::sync::Arc<latent_artifacts::DirectoryArtifactRepository>,
    journal: LocalActivationJournalConfig,
    correlations: usize,
    probe: CurrentProcessOwnerProbe,
    origin: Instant,
}

impl Node {
    pub async fn start(
        plan: &Plan,
        directory: &Path,
        fixture: Fixture,
        control: tokio::runtime::Handle,
        threads: RuntimeThreads,
        origin: Instant,
    ) -> Result<Self> {
        Self::start_configured(
            2 + u64::from(plan.count()) * 2,
            configuration(directory),
            fixture,
            control,
            threads,
            origin,
        )
        .await
    }

    pub async fn start_configured(
        maximum_commands: u64,
        config: Value,
        fixture: Fixture,
        control: tokio::runtime::Handle,
        threads: RuntimeThreads,
        origin: Instant,
    ) -> Result<Self> {
        Self::start_with_clock(
            maximum_commands,
            config,
            fixture,
            control,
            threads,
            origin,
            std::sync::Arc::new(latent_core::SystemActivationClock),
        )
        .await
    }

    #[expect(
        clippy::too_many_arguments,
        reason = "The bounded collector shares production composition and injects only its observing clock."
    )]
    pub async fn start_with_clock(
        maximum_commands: u64,
        mut config: Value,
        fixture: Fixture,
        control: tokio::runtime::Handle,
        threads: RuntimeThreads,
        origin: Instant,
        clock: std::sync::Arc<dyn latent_core::ActivationClock>,
    ) -> Result<Self> {
        let parsed: crate::config::NodeConfig = serde_json::from_value(config.clone())?;
        let settings = parsed.derive().map_err(platform)?;
        let runtime_config = settings.wasmtime.clone();
        let journal = settings.manager.journal;
        let correlations = settings.observer.maximum_active_correlations;
        let started = Instant::now();
        let catalogs = Catalogs::open(&settings).await.map_err(platform)?;
        let catalog_open = started.elapsed().as_nanos().to_string();
        let artifacts = catalogs.artifacts.clone();
        let started = Instant::now();
        let owner = Box::pin(StandaloneNode::start_with_catalogs_and_clock(
            settings, catalogs, control, threads, clock,
        ))
        .await
        .map_err(platform)?;
        let node_start = started.elapsed().as_nanos().to_string();
        let started = Instant::now();
        let channel =
            tonic::transport::Endpoint::from_shared(format!("http://{}", owner.endpoint()))?
                .connect_timeout(Duration::from_secs(5))
                .timeout(Duration::from_secs(5))
                .connect()
                .await?;
        let startup = json!({"catalog_open_nanos":catalog_open,"node_start_nanos":node_start,
            "client_connect_nanos":started.elapsed().as_nanos().to_string(),
            "excluded":["fixture-loading","runtime-construction"],"comparable_to_historical_startup":false});
        config
            .as_object_mut()
            .ok_or("comparison config shape")?
            .remove("credentials");
        config["dataDirectory"] = json!("data");
        Ok(Self {
            owner,
            fixture,
            config,
            runtime_config,
            startup,
            work: WorkCounts::default(),
            maximum_commands,
            channel,
            artifacts,
            journal,
            correlations,
            probe: CurrentProcessOwnerProbe::bind(ProbeLimits::default())?,
            origin,
        })
    }

    pub fn command(&mut self, invoke: bool) -> Result<()> {
        if self.work.commands >= self.maximum_commands {
            self.work.budget_exhausted = true;
            return Err("comparison command budget exceeded".into());
        }
        self.work.commands += 1;
        if invoke {
            self.work.invoke_attempts += 1;
        }
        Ok(())
    }

    pub fn channel(&self) -> Channel {
        self.channel.clone()
    }

    /// Create the channel on the caller's runtime, including its connection task.
    pub async fn reconnect(&mut self) -> Result<()> {
        self.channel =
            tonic::transport::Endpoint::from_shared(format!("http://{}", self.owner.endpoint()))?
                .connect_timeout(Duration::from_secs(5))
                .timeout(Duration::from_secs(5))
                .connect()
                .await?;
        Ok(())
    }

    pub async fn published(&self) -> Result<CapsuleArtifact> {
        let artifact = self
            .artifacts
            .fetch(&self.fixture.artifact.descriptor.release_digest)
            .await
            .map_err(platform)?;
        if artifact.manifest != self.fixture.artifact.manifest
            || artifact.contracts != self.fixture.artifact.contracts
            || artifact.component_bytes != self.fixture.artifact.component_bytes
            || artifact.descriptor.release_digest != self.fixture.artifact.descriptor.release_digest
        {
            return Err("published comparison inputs differ from the recorded fixture".into());
        }
        Ok(artifact)
    }

    pub async fn invoke(&mut self, request: proto::InvokeRequest) -> Result<proto::InvokeResponse> {
        self.command(true)?;
        Ok(InvocationServiceClient::new(self.channel.clone())
            .invoke(authenticated(request)?)
            .await?
            .into_inner())
    }

    pub async fn status(&mut self, id: &str) -> Result<proto::ActivationStatus> {
        self.command(false)?;
        Ok(InvocationServiceClient::new(self.channel.clone())
            .get_activation(authenticated(proto::GetActivationRequest {
                activation_id: id.to_owned(),
            })?)
            .await?
            .into_inner())
    }

    pub fn sample(&self, label: &str) -> Result<Value> {
        let started = self.origin.elapsed().as_micros();
        let resources = self.probe.capture()?;
        let inventory = self.owner.inventory().map_err(platform)?;
        Ok(json!({"label":label,"started_micros":started.to_string(),
            "finished_micros":self.origin.elapsed().as_micros().to_string(),"resources":resources,
            "inventory":projection::inventory(&inventory),
            "backend":projection::backend(self.owner.backend.resource_snapshot()),
            "ownership":projection::ownership(&self.owner,self.journal,self.correlations),
            "work":self.work}))
    }

    pub async fn shutdown(self) -> Result<ShutdownReport> {
        let Self {
            owner,
            channel,
            artifacts,
            ..
        } = self;
        drop(channel);
        drop(artifacts);
        owner.shutdown().await.map_err(platform)
    }
}

fn authenticated<T>(message: T) -> Result<tonic::Request<T>> {
    let mut request = tonic::Request::new(message);
    request.metadata_mut().insert(
        "authorization",
        "Bearer comparison-examples-000000000000000".parse()?,
    );
    request.set_timeout(Duration::from_secs(1));
    Ok(request)
}

fn configuration(directory: &Path) -> Value {
    json!({"formatVersion":1,"dataDirectory":directory.join("data"),"nodeId":"phase1-comparison",
        "bind":"127.0.0.1:0","workers":{"runtime":2,"control":1},
        "cells":[{"class":"standard","capacity":2,"queueCapacity":3,"maximumMemoryBytes":16_777_216}],
        "execution":{"maximumCpuFuel":10_000_000_000_u64,"maximumWallTimeMillis":1000,"maximumLogBytes":16384},
        "catalogs":{"releaseEntries":16,"releaseIndexBytes":16_777_216,"deployments":16,"deploymentStateBytes":16_777_216},
        "cache":{"entries":4,"sourceBytes":67_108_864,"metadataBytes":16_777_216,"compiledImageBytes":268_435_456,"preparations":1},
        "retention":{"terminalEntries":64,"terminalTtlMillis":60_000,"bytes":20_971_520},
        "telemetry":{"queueEntries":256,"retainedEntries":128,"retainedBytes":1_048_576},"shutdownGraceMillis":500,
        "credentials":[{"token":"comparison-examples-000000000000000","subject":"comparison-examples","tenant":"examples","role":"operator"}]})
}
