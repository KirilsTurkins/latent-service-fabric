use std::sync::Arc;
use std::time::Duration;

use latent_testkit::conformance::{ArtifactReference, WorkCounter};
use latent_wire::invocation::{
    AuthenticatedInvocationContext, InvocationServiceAdapter, InvocationServiceClient,
    InvocationServiceServices, LocalInvocationRuntime,
};
use latent_wire::management::proto as management;
use serde_json::{json, Value};
use tonic::transport::Channel;

use super::{fixture, RuntimeThreads, StandaloneNode};

pub struct Session {
    pub node: StandaloneNode,
    pub adapter: InvocationServiceAdapter<LocalInvocationRuntime>,
    pub client: InvocationServiceClient<Channel>,
    pub examples: AuthenticatedInvocationContext,
    pub tests: AuthenticatedInvocationContext,
    pub work: WorkCounter,
    pub inputs: Value,
    pub published_inputs: Value,
    pub artifacts: Vec<ArtifactReference>,
    pub echo_release: String,
    pub capability_release: String,
}

impl Session {
    pub async fn start(
        config: &crate::config::NodeConfig,
        control: tokio::runtime::Handle,
        threads: RuntimeThreads,
    ) -> Self {
        let settings = config.derive().unwrap();
        let examples = AuthenticatedInvocationContext::new(
            settings.transport.credentials[0].principal.clone(),
        );
        let tests = AuthenticatedInvocationContext::new(
            settings.transport.credentials[1].principal.clone(),
        );
        let limits = settings.invocation.clone();
        let node = StandaloneNode::start(settings, control, threads)
            .await
            .unwrap();
        let adapter = InvocationServiceAdapter::with_services(
            Arc::new(
                LocalInvocationRuntime::with_limits(node.manager.clone(), limits.clone()).unwrap(),
            ),
            limits,
            InvocationServiceServices {
                clock: node.clock.clone(),
                ..InvocationServiceServices::default()
            },
        )
        .unwrap();
        let channel =
            tonic::transport::Endpoint::from_shared(format!("http://{}", node.endpoint()))
                .unwrap()
                .connect_timeout(Duration::from_secs(2))
                .timeout(Duration::from_secs(5))
                .connect()
                .await
                .unwrap();
        let work = WorkCounter::with_limits(28, 64).unwrap();
        let echo = fixture::echo();
        let caps = fixture::capabilities();
        assert_ne!(echo.digest, caps.digest);
        let inputs = json!(echo.inputs);
        let published_inputs = json!([echo.published, caps.published]);
        let artifacts = echo
            .artifacts
            .iter()
            .chain(&caps.artifacts)
            .cloned()
            .collect();
        let echo_release = echo.digest.clone();
        let capability_release = caps.digest.clone();
        publish(&channel, &work, echo, fixture::TOKEN).await;
        publish(&channel, &work, caps, fixture::TESTS_TOKEN).await;
        Self {
            node,
            adapter,
            client: InvocationServiceClient::new(channel),
            examples,
            tests,
            work,
            inputs,
            published_inputs,
            artifacts,
            echo_release,
            capability_release,
        }
    }
}

async fn publish(channel: &Channel, work: &WorkCounter, package: fixture::Package, token: &str) {
    work.before_command(false).unwrap();
    management::release_service_client::ReleaseServiceClient::new(channel.clone())
        .publish_release(fixture::authenticated(package.upload, token))
        .await
        .unwrap();
    work.before_command(false).unwrap();
    management::deployment_service_client::DeploymentServiceClient::new(channel.clone())
        .apply_deployment(fixture::authenticated(
            management::ApplyDeploymentRequest {
                operation: None,
                deployment: Some(package.deployment),
                expected_generation: Some(0),
            },
            token,
        ))
        .await
        .unwrap();
}
