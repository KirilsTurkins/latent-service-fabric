pub(super) mod projection;

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use latent_artifacts::{
    encode_contract_metadata, ArtifactRepository, CapsuleArtifact, ContractMetadataLimits,
    DirectoryArtifactRepository,
};
use latent_control_store::{DirectoryDeploymentRepository, VersionedDeployment};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_testkit::conformance::WorkCounts;
use latent_testkit::resources::{CurrentProcessOwnerProbe, ProbeLimits};
use latent_wire::invocation::{proto, InvocationServiceClient};
use latent_wire::management::{deployment_to_proto, proto as management};
use serde_json::{json, Value};
use tonic::transport::Channel;

use super::{
    fixtures::{Fixture, Fixtures},
    platform, MeasurementPlan, Result,
};
use crate::standalone::{start::Catalogs, RuntimeThreads, ShutdownReport, StandaloneNode};

pub struct MeasurementNode {
    pub node: StandaloneNode,
    pub artifacts: Arc<DirectoryArtifactRepository>,
    pub deployments: Arc<DirectoryDeploymentRepository>,
    pub client: InvocationServiceClient<Channel>,
    pub fixtures: Fixtures,
    pub plan: MeasurementPlan,
    pub runtime_config: latent_wasmtime::WasmtimeConfig,
    pub startup: Value,
    pub(super) catalog_state_path: std::path::PathBuf,
    journal_config: latent_node::LocalActivationJournalConfig,
    maximum_active_correlations: usize,
    channel: Channel,
    control: tokio::runtime::Handle,
    work: Mutex<WorkCounts>,
    probe: CurrentProcessOwnerProbe,
    origin: Instant,
}

impl MeasurementNode {
    pub async fn start(
        plan: MeasurementPlan,
        directory: &std::path::Path,
        control: tokio::runtime::Handle,
        threads: RuntimeThreads,
        fixtures: Fixtures,
        origin: Instant,
    ) -> Result<(Self, Value)> {
        let config = configuration(&plan, directory);
        let parsed: crate::config::NodeConfig = serde_json::from_value(config.clone())?;
        let settings = parsed
            .derive()
            .map_err(|error| stage("config-derive", error))?;
        let runtime_config = settings.wasmtime.clone();
        let journal_config = settings.manager.journal;
        let maximum_active_correlations = settings.observer.maximum_active_correlations;
        let catalog_state_path = settings.data_directory.join("deployments/catalog.json");
        let started = Instant::now();
        let catalogs = Catalogs::open(&settings)
            .await
            .map_err(|error| stage("catalog-open", error))?;
        let catalog_open_nanos = started.elapsed().as_nanos().to_string();
        let artifacts = catalogs.artifacts.clone();
        let deployments = catalogs.deployments.clone();
        let started = Instant::now();
        let node = Box::pin(StandaloneNode::start_with_catalogs(
            settings,
            catalogs,
            control.clone(),
            threads,
        ))
        .await
        .map_err(|error| stage("node-start", error))?;
        let node_start_nanos = started.elapsed().as_nanos().to_string();
        let endpoint =
            tonic::transport::Endpoint::from_shared(format!("http://{}", node.endpoint()))?
                .connect_timeout(Duration::from_secs(5))
                .timeout(Duration::from_secs(5));
        let started = Instant::now();
        let channel = endpoint.connect().await?;
        let startup = json!({"unit":"ns","catalog_open_nanos":catalog_open_nanos,
            "node_start_nanos":node_start_nanos,"client_connect_nanos":started.elapsed().as_nanos().to_string(),
            "boundaries":{"catalog_open":"directory-artifact-and-deployment-open",
                "node_start":"standalone-start-with-open-catalogs-to-accepting",
                "client_connect":"persistent-loopback-tonic-channel-connect"},
            "excluded":["fixture-loading","runtime-construction"]});
        let probe = CurrentProcessOwnerProbe::bind(ProbeLimits::default())?;
        let mut public = config;
        public.as_object_mut().unwrap().remove("credentials");
        public["dataDirectory"] = json!("data");
        Ok((
            Self {
                node,
                artifacts,
                deployments,
                client: InvocationServiceClient::new(channel.clone()),
                fixtures,
                plan,
                runtime_config,
                startup,
                catalog_state_path,
                journal_config,
                maximum_active_correlations,
                channel,
                control,
                work: Mutex::new(WorkCounts::default()),
                probe,
                origin,
            },
            public,
        ))
    }

    pub fn before_command(&self, invoke: bool) -> Result<()> {
        let (invokes, commands) = self.plan.maximum_work();
        let mut work = self
            .work
            .lock()
            .map_err(|_| std::io::Error::other("measurement work counter poisoned"))?;
        if work.commands >= commands || (invoke && work.invoke_attempts >= invokes) {
            work.budget_exhausted = true;
            return Err(std::io::Error::other("measurement work limit").into());
        }
        work.commands += 1;
        work.invoke_attempts += u64::from(invoke);
        Ok(())
    }

    pub(super) fn channel(&self) -> Channel {
        self.channel.clone()
    }

    pub fn work(&self) -> WorkCounts {
        *self.work.lock().expect("measurement work counter")
    }

    pub async fn publish_artifact(&self, artifact: CapsuleArtifact) -> Result<()> {
        self.before_command(false)?;
        let repository = self.artifacts.clone();
        self.control
            .spawn(async move { repository.publish(artifact).await })
            .await?
            .map_err(platform)?;
        Ok(())
    }

    pub async fn apply_many(
        &self,
        deployments: Vec<latent_manifest::DeploymentManifest>,
    ) -> Result<latent_core::RouteGeneration> {
        self.before_command(false)?;
        let repository = self.deployments.clone();
        self.control
            .spawn(async move { repository.apply_many(deployments).await })
            .await?
            .map_err(platform)
    }

    pub async fn invoke(
        &self,
        tenant: &str,
        request: proto::InvokeRequest,
    ) -> Result<proto::InvokeResponse> {
        self.before_command(true)?;
        Ok(self
            .client
            .clone()
            .invoke(authenticated(tenant, request)?)
            .await?
            .into_inner())
    }

    pub async fn status(&self, tenant: &str, id: &str) -> Result<proto::ActivationStatus> {
        self.before_command(false)?;
        Ok(self
            .client
            .clone()
            .get_activation(authenticated(
                tenant,
                proto::GetActivationRequest {
                    activation_id: id.to_owned(),
                },
            )?)
            .await?
            .into_inner())
    }

    pub async fn cancel(
        &self,
        tenant: &str,
        id: &str,
        reason: &str,
    ) -> Result<proto::CancelResponse> {
        self.before_command(false)?;
        Ok(self
            .client
            .clone()
            .cancel(authenticated(
                tenant,
                proto::CancelRequest {
                    activation_id: id.to_owned(),
                    reason: reason.to_owned(),
                },
            )?)
            .await?
            .into_inner())
    }

    pub async fn publish(&self, fixture: &Fixture) -> Result<Value> {
        let codec = JsonManifestCodec::default();
        let upload = management::CapsuleArtifactUpload {
            capsule_manifest_json: codec
                .encode_capsule(&fixture.artifact.manifest)
                .map_err(|_| std::io::Error::other("fixture manifest encoding"))?,
            contract_metadata_json: encode_contract_metadata(
                &fixture.artifact.contracts,
                ContractMetadataLimits::default(),
            )
            .map_err(platform)?,
            component_digest: fixture.release_digest.clone(),
            component_bytes: fixture.artifact.component_bytes.clone(),
            component_media_type: fixture.artifact.descriptor.media_type.clone(),
        };
        let started = Instant::now();
        self.before_command(false)?;
        management::release_service_client::ReleaseServiceClient::new(self.channel.clone())
            .publish_release(authenticated(
                &fixture.target.tenant,
                management::PublishReleaseRequest {
                    package: None,
                    operation: None,
                    release: None,
                    artifact: Some(upload),
                },
            )?)
            .await?;
        let published = started.elapsed().as_nanos().to_string();
        let deployment = deployment_to_proto(&VersionedDeployment {
            manifest: fixture.deployment.clone(),
            generation: 0,
        })
        .map_err(|_| std::io::Error::other("fixture deployment conversion"))?;
        self.before_command(false)?;
        let started = Instant::now();
        management::deployment_service_client::DeploymentServiceClient::new(self.channel.clone())
            .apply_deployment(authenticated(
                &fixture.target.tenant,
                management::ApplyDeploymentRequest {
                    deployment: Some(deployment),
                    expected_generation: None,
                },
            )?)
            .await?;
        Ok(
            json!({"release_digest":fixture.release_digest,"deployment_id":fixture.deployment.id.0,
            "publish_elapsed_nanos":published,"apply_elapsed_nanos":started.elapsed().as_nanos().to_string()}),
        )
    }

    pub fn sample(&self, label: &str) -> Result<Value> {
        let started = self.origin.elapsed().as_micros();
        let resources = self.probe.capture()?;
        let inventory = self.node.inventory().map_err(platform)?;
        let backend = projection::backend(self.node.backend.resource_snapshot());
        let ownership = projection::ownership(
            &self.node,
            self.journal_config,
            self.maximum_active_correlations,
        );
        let work = self.work();
        Ok(
            json!({"label":label,"started_micros":started.to_string(),"finished_micros":self.origin.elapsed().as_micros().to_string(),
            "resources":resources,"inventory":projection::inventory(&inventory),
            "backend":backend,"ownership":ownership,"work":work}),
        )
    }

    pub async fn shutdown(self) -> Result<ShutdownReport> {
        let Self {
            node,
            artifacts,
            deployments,
            client,
            channel,
            ..
        } = self;
        drop(client);
        drop(channel);
        drop(artifacts);
        drop(deployments);
        node.shutdown()
            .await
            .map_err(|error| stage("node-shutdown", error))
    }
}

fn stage(
    name: &'static str,
    error: latent_core::PlatformError,
) -> Box<dyn std::error::Error + Send + Sync> {
    let message = format!("measurement {name} failed: {:?}", error.code);
    drop(error);
    std::io::Error::other(message).into()
}

pub(super) fn authenticated<T>(tenant: &str, message: T) -> Result<tonic::Request<T>> {
    let token = match tenant {
        "examples" => "measurement-examples-00000000000000",
        "tests" => "measurement-tests-00000000000000000",
        _ => return Err(std::io::Error::other("unknown measurement tenant").into()),
    };
    let mut request = tonic::Request::new(message);
    request
        .metadata_mut()
        .insert("authorization", format!("Bearer {token}").parse()?);
    request.set_timeout(Duration::from_secs(5));
    Ok(request)
}

fn configuration(plan: &MeasurementPlan, directory: &std::path::Path) -> Value {
    let maximum = *plan.scale_counts.last().expect("validated scales");
    json!({"formatVersion":1,"dataDirectory":directory.join("data"),"nodeId":"phase1-measurement",
        "bind":"127.0.0.1:0","workers":{"runtime":2,"control":1},
        "cells":[{"class":"standard","capacity":2,"queueCapacity":3,"maximumMemoryBytes":67_108_864}],
        "execution":{"maximumCpuFuel":10_000_000_000_u64,"maximumWallTimeMillis":5000,"maximumLogBytes":16384},
        "catalogs":{"releaseEntries":maximum.max(16),"releaseIndexBytes":1_073_741_824_u64,
            "deployments":maximum.max(16),"deploymentStateBytes":1_073_741_824_u64},
        "cache":{"entries":4,"sourceBytes":67_108_864,"metadataBytes":16_777_216,"compiledImageBytes":268_435_456,"preparations":1},
        "retention":{"terminalEntries":64,"terminalTtlMillis":60_000,"bytes":20_971_520},
        "telemetry":{"queueEntries":256,"retainedEntries":128,"retainedBytes":1_048_576},"shutdownGraceMillis":500,
        "credentials":[{"token":"measurement-examples-00000000000000","subject":"measurement-examples","tenant":"examples","role":"operator"},
            {"token":"measurement-tests-00000000000000000","subject":"measurement-tests","tenant":"tests","role":"operator"}]})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn configuration_reserves_records_for_all_running_and_queued_requests() {
        let plan = MeasurementPlan {
            schema: "latent.phase1.measurement-plan.v1".to_owned(),
            profile: super::super::Profile::Smoke,
            kind: super::super::Workload::Scale,
            repetition: 1,
            scale_counts: vec![2, 4],
            route_samples: 16,
            warmup_invocations: 4,
            measured_invocations: 20,
            batch_size: 20,
            concurrency: 2,
            benchmark_samples: 4,
            maximum_run_seconds: 90,
            maximum_output_bytes: 8 * 1024 * 1024,
        };
        plan.validate().unwrap();
        let mut config: crate::config::NodeConfig =
            serde_json::from_value(configuration(&plan, &std::env::temp_dir())).unwrap();
        let settings = config.derive().unwrap();
        let journal = settings.manager.journal;
        assert_eq!(journal.maximum_active, 5);
        assert_eq!(journal.maximum_record_bytes, 4 * 1024 * 1024);
        assert_eq!(
            journal.maximum_retained_bytes,
            journal.maximum_record_bytes * journal.maximum_active
        );
        config.retention.bytes = 4 * 1024 * 1024;
        assert_eq!(
            config.derive().err().unwrap().message,
            "invalid standalone configuration: retention.bytes"
        );
    }
}
