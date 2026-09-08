//! Selected adapter/network equivalence on the actual standalone composition.
//! Invoked only by the bounded conformance runner, with prebuilt fixtures.
mod cases;
mod fixture;
mod status;

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use latent_testkit::conformance::{
    encode_bounded, CaseEvidence, DriverEvidence, ReportLimits, WorkCounter,
};
use latent_testkit::{InvariantProbe, ObservedInvariantProbe};
use latent_wire::invocation::{
    AuthenticatedInvocationContext, InvocationService, InvocationServiceAdapter,
    InvocationServiceClient, InvocationServiceServices, LocalInvocationRuntime,
};
use latent_wire::management::proto as management;
use serde_json::json;

use super::{RuntimeThreads, StandaloneNode};

#[test]
#[ignore = "requires prebuilt echo and bounded Phase 1 evidence runner; exactly 16 Invoke attempts"]
fn adapter_and_rpc_have_equivalent_selected_outcomes() {
    let directory = tempfile::tempdir().unwrap();
    let (config, public_config) = fixture::configuration(directory.path());
    let config_sha256 =
        latent_artifacts::content_digest(&serde_json::to_vec(&public_config).unwrap()).0;
    let observed = RuntimeThreads::default();
    let invocation = runtime(&observed.invocation);
    let control = runtime(&observed.control);
    let evidence = invocation.block_on(async {
        tokio::time::timeout(Duration::from_secs(45), async {
            let settings = config.derive().unwrap();
            let principal = settings.transport.credentials[0].principal.clone();
            let limits = settings.invocation.clone();
            let node = StandaloneNode::start(settings, control.handle().clone(), RuntimeThreads {
                invocation: observed.invocation.clone(), control: observed.control.clone(),
            }).await.unwrap();
            let adapter = InvocationServiceAdapter::with_services(
                Arc::new(LocalInvocationRuntime::with_limits(node.manager.clone(), limits.clone()).unwrap()),
                limits,
                InvocationServiceServices { clock: node.clock.clone(), ..InvocationServiceServices::default() },
            ).unwrap();
            let channel = tonic::transport::Endpoint::from_shared(format!("http://{}", node.endpoint()))
                .unwrap().connect_timeout(Duration::from_secs(2)).timeout(Duration::from_secs(5))
                .connect().await.unwrap();
            let mut client = InvocationServiceClient::new(channel.clone());
            let work = WorkCounter::with_limits(16, 32).unwrap();
            let (upload, deployment, input_identities) = fixture::package();
            work.before_command(false).unwrap();
            management::release_service_client::ReleaseServiceClient::new(channel.clone())
                .publish_release(fixture::request(upload)).await.unwrap();
            work.before_command(false).unwrap();
            management::deployment_service_client::DeploymentServiceClient::new(channel.clone())
                .apply_deployment(fixture::request(management::ApplyDeploymentRequest {
                    deployment: Some(deployment), expected_generation: Some(0),
                })).await.unwrap();
            let context = AuthenticatedInvocationContext::new(principal);
            let mut rows = Vec::new();
            for index in 0..cases::NAMES.len() {
                let direct_id = format!("direct-{index}");
                let rpc_id = format!("remote-{index}");
                work.before_command(true).unwrap();
                let direct = adapter.invoke(context.request(cases::request(index, &direct_id))).await;
                work.before_command(true).unwrap();
                let remote = client.invoke(fixture::request(cases::request(index, &rpc_id))).await;
                match (direct, remote) {
                    (Ok(direct), Ok(remote)) => {
                        let direct = direct.into_inner();
                        let remote = remote.into_inner();
                        assert_eq!(direct.activation_id, direct_id);
                        assert_eq!(remote.activation_id, rpc_id);
                        rows.push(cases::compare(index, &direct, &remote));
                        // Check each retained receipt against its own immediate result;
                        // timestamps and activation identities intentionally differ.
                        if matches!(index, 0 | 1 | 4 | 5) {
                            status::compare(&node, &adapter, &mut client, &context, &work, (&direct, &remote)).await;
                        }
                    },
                    (Err(left), Err(right)) => {
                        assert!(matches!(index, 3 | 7), "unexpected rejected case: {} {left} {right}", cases::NAMES[index]);
                        assert_eq!(left.code(), right.code());
                        assert_eq!(left.details(), right.details());
                        rows.push(json!({"name":cases::NAMES[index],"classification":"rpc-rejection","code":format!("{:?}",left.code())}));
                    },
                    (left, right) => panic!("adapter/RPC mismatch {}: {left:?} {right:?}", cases::NAMES[index]),
                }
            }
            let probe = ObservedInvariantProbe::new(node.inventory.as_ref(), node.sink.as_ref(), None).unwrap();
            let inventory = probe.node_inventory().await.unwrap();
            assert_eq!(inventory.cache_summary.entries, 1);
            let retained_metrics = probe.telemetry().await.unwrap().len();
            assert!(probe.idle_scaling(1).await.is_err(), "no invented route latency measurement");
            drop(adapter);
            drop(client);
            drop(channel);
            let shutdown = node.shutdown().await.unwrap();
            assert!(shutdown.clean && shutdown.telemetry_flushed && shutdown.epoch_helper_joined, "{shutdown:?}");
            assert_eq!(work.snapshot().invoke_attempts, 16);
            let counts = work.snapshot();
            DriverEvidence {
                driver: "adapter".to_owned(), work: counts, artifacts: Vec::new(),
                cases: vec![CaseEvidence { diagnostics: vec!["adapter.json".to_owned()], ..CaseEvidence::passed("adapter-rpc-parity", counts, json!({
                    "pairs":rows,"shutdown":shutdown,"node_starts":"1",
                    "retained_metric_points":retained_metrics.to_string(),"inventory_cache_entries":inventory.cache_summary.entries.to_string(),
                    "public_config":public_config,"config_sha256":config_sha256,"inputs":input_identities,
                    "comparison":"typed outcome, payload/error, receipt pin, fuel/memory/log consumption and own retained status",
                    "variable_fields":["activation identity","trace identity","selected fixed-pool cell identity","wall-clock and elapsed measurements"],
                    "scope":"selected eight adapter/RPC pairs; not complete backend/context/fairness equivalence"
                })) }],
            }
        }).await.expect("45-second adapter parity deadline")
    });
    drop(invocation);
    drop(control);
    assert_eq!(observed.invocation.load(Ordering::Acquire), 0);
    assert_eq!(observed.control.load(Ordering::Acquire), 0);
    let path = std::env::var_os("LSF_PHASE1_PARITY_REPORT").expect("required parity evidence path");
    std::fs::write(
        path,
        encode_bounded(&evidence, ReportLimits::default()).unwrap(),
    )
    .unwrap();
}

fn runtime(observed: &Arc<AtomicUsize>) -> tokio::runtime::Runtime {
    let started = observed.clone();
    let stopped = observed.clone();
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(1)
        .max_blocking_threads(1)
        .on_thread_start(move || {
            started.fetch_add(1, Ordering::Release);
        })
        .on_thread_stop(move || {
            stopped.fetch_sub(1, Ordering::Release);
        })
        .enable_all()
        .build()
        .unwrap()
}
