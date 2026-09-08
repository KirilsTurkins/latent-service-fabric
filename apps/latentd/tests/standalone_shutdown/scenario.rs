use std::time::Duration;

use latent_wasmtime::WIT_VALUES_MEDIA_TYPE;
use latent_wire::invocation::{proto as invocation, InvocationServiceClient};
use latent_wire::management::proto;
use proto::deployment_service_client::DeploymentServiceClient;
use proto::release_service_client::ReleaseServiceClient;
use tonic::transport::{Channel, Endpoint};

use super::{fixture, support};

pub fn run() {
    let directory = tempfile::tempdir().unwrap();
    let settings = support::settings(directory.path());
    let runtimes = support::Runtimes::new();
    runtimes.invocation.block_on(async {
        let node = runtimes.start(settings).await;
        let channel = Endpoint::from_shared(format!("http://{}", node.endpoint()))
            .unwrap()
            .connect()
            .await
            .unwrap();
        publish(channel.clone()).await;
        let running = invoke(channel.clone(), "running-at-shutdown");
        let queued = invoke(channel.clone(), "queued-at-shutdown");
        tokio::time::timeout(Duration::from_millis(150), async {
            loop {
                assert!(
                    !running.is_finished() && !queued.is_finished(),
                    "guest must remain pending"
                );
                let inventory = node.inventory().unwrap();
                let class = &inventory.cell_capacity[0];
                let live = |name: &str| {
                    inventory
                        .topology
                        .entries
                        .iter()
                        .find(|entry| entry.name == name)
                        .and_then(|entry| entry.active_count)
                };
                if class.active == 1
                    && class.queue_depth == 1
                    && live("guest-stores") == Some(1)
                    && live("guest-component-instances") == Some(1)
                {
                    break;
                }
                tokio::task::yield_now().await;
            }
        })
        .await
        .expect("one real running guest plus one queued owner within 150ms");
        drop(channel);
        let report = node
            .shutdown()
            .await
            .expect("bounded shutdown owns both activations");
        for (owner, request) in [("first", running), ("second", queued)] {
            let result = tokio::time::timeout(Duration::from_secs(1), request)
                .await
                .unwrap()
                .unwrap();
            match result {
                Err(status) => assert!(
                    matches!(
                        status.code(),
                        tonic::Code::Unavailable | tonic::Code::Cancelled
                    ),
                    "{owner} shutdown RPC returned unexpected status: {status:?}"
                ),
                Ok(response) => {
                    let Some(invocation::invoke_response::Result::PlatformFailure(failure)) =
                        response.into_inner().result
                    else {
                        panic!("spinning guest cannot produce success");
                    };
                    assert!(matches!(failure.code.as_str(), "cancelled" | "unavailable"));
                }
            }
        }
        support::assert_clean(&report);
    });
    runtimes.finish();
}

async fn publish(channel: Channel) {
    let upload = fixture::upload();
    let digest = upload.artifact.as_ref().unwrap().component_digest.clone();
    ReleaseServiceClient::new(channel.clone())
        .publish_release(support::request(upload))
        .await
        .unwrap();
    DeploymentServiceClient::new(channel)
        .apply_deployment(support::request(proto::ApplyDeploymentRequest {
            deployment: Some(fixture::deployment(&digest)),
            expected_generation: Some(0),
        }))
        .await
        .unwrap();
}

fn invoke(
    channel: Channel,
    id: &str,
) -> tokio::task::JoinHandle<Result<tonic::Response<invocation::InvokeResponse>, tonic::Status>> {
    let message = invocation::InvokeRequest {
        activation_id: Some(id.to_owned()),
        target: Some(invocation::InvocationTarget {
            tenant: "tests".to_owned(),
            service: fixture::SERVICE.to_owned(),
            contract: fixture::API.to_owned(),
            function: "spin".to_owned(),
            route: None,
        }),
        payload: b"[]".to_vec(),
        media_type: WIT_VALUES_MEDIA_TYPE.to_owned(),
        budget: Some(invocation::ResourceBudget {
            cpu_fuel: fixture::FUEL,
            memory_bytes: fixture::MEMORY,
            wall_time_limit_millis: Some(5000),
            ..invocation::ResourceBudget::default()
        }),
        ..invocation::InvokeRequest::default()
    };
    tokio::spawn(async move {
        InvocationServiceClient::new(channel)
            .invoke(support::request(message))
            .await
    })
}
