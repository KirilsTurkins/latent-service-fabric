use super::super::{
    budget::cpu,
    catalog_mutations::{frames, observation},
    cold::call::Clock,
};
use super::*;
use latent_control_store::CatalogWorkObserver;

pub(in crate::standalone::measurements::comparison) struct ObservedStart {
    pub maximum_commands: u64,
    pub config: Value,
    pub fixture: Fixture,
    pub control: tokio::runtime::Handle,
    pub threads: RuntimeThreads,
    pub clock: Clock,
    pub observer: CatalogWorkObserver,
    pub profile_reopen: bool,
}

impl ObservedStart {
    pub async fn start(self) -> Result<(Node, Value)> {
        let parsed: crate::config::NodeConfig = serde_json::from_value(self.config.clone())?;
        let settings = parsed.derive().map_err(platform)?;
        let observer_before = self.observer.snapshot();
        let cpu_before = cpu::sample(self.clock)?;
        let mut polls = 0_u64;
        let started = self.clock.elapsed();
        let mut future: latent_core::BoxFuture<'_, _> =
            Box::pin(Catalogs::open_observed(&settings, self.observer.clone()));
        let result = if self.profile_reopen {
            std::future::poll_fn(|cx| {
                polls += 1;
                frames::measured_catalog_reopen(&mut future, cx)
            })
            .await
        } else {
            future.as_mut().await
        };
        let finished = self.clock.elapsed();
        let cpu_after = cpu::sample(self.clock)?;
        drop(future);
        let opening = json!({"started_nanos":started.to_string(),"finished_nanos":finished.to_string(),
            "cpu_before":cpu_before,"cpu_after":cpu_after,"observer_before":observation::project(&observer_before)?,
            "observer_after":observation::snapshot(&self.observer)?,"returned_ok":result.is_ok(),
            "error":result.as_ref().err().map(observation::error),
            "allocation_frame":self.profile_reopen.then(|| json!({"case":"reopen","poll_calls":polls.to_string(),"drop_calls":"0","catalog_moved_to_node":result.is_ok()}))});
        let catalogs = result.map_err(platform)?;
        let node = self.finish(settings, catalogs, finished - started).await?;
        let mut opening = opening;
        opening["verification_after"] = observation::verification(&node)?;
        Ok((node, opening))
    }

    async fn finish(
        self,
        settings: crate::config::NodeSettings,
        catalogs: Catalogs,
        catalog_open: u128,
    ) -> Result<Node> {
        let runtime_config = settings.wasmtime.clone();
        let journal = settings.manager.journal;
        let correlations = settings.observer.maximum_active_correlations;
        let artifacts = catalogs.artifacts.clone();
        let deployments = catalogs.deployments.clone();
        let started = Instant::now();
        let owner = Box::pin(StandaloneNode::start_with_catalogs(
            settings,
            catalogs,
            self.control,
            self.threads,
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
        let startup = json!({"catalog_open_nanos":catalog_open.to_string(),"node_start_nanos":node_start,
            "client_connect_nanos":started.elapsed().as_nanos().to_string(),"excluded":["fixture-loading","runtime-construction"],
            "comparable_to_historical_startup":false});
        let mut config = self.config;
        config
            .as_object_mut()
            .ok_or("comparison config shape")?
            .remove("credentials");
        config["dataDirectory"] = json!("data");
        Ok(Node {
            owner,
            fixture: self.fixture,
            config,
            runtime_config,
            startup,
            work: WorkCounts::default(),
            maximum_commands: self.maximum_commands,
            channel,
            artifacts,
            deployments,
            journal,
            correlations,
            probe: CurrentProcessOwnerProbe::bind(ProbeLimits::default())?,
            origin: self.clock.origin,
        })
    }
}
