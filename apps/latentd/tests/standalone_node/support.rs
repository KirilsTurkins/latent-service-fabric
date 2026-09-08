use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use latentd::config::{NodeConfig, NodeSettings};
use latentd::standalone::{RuntimeThreads, ShutdownReport, StandaloneNode};
use tokio::runtime::{Builder, Runtime};
use tonic::transport::{Channel, Endpoint};
use tonic::Request;

pub const OPERATOR: &str = "operator-0000000000000000000000000000";
pub const CALLER: &str = "caller-000000000000000000000000000000";
pub const FOREIGN: &str = "foreign-00000000000000000000000000000";
pub const NODE_ID: &str = "standalone-integration";
const CHILD: &str = "LSF_STANDALONE_NODE_TEST";
const DONE: &str = "standalone-node-scenario-completed";
const MAXIMUM_CHILD_LOG_BYTES: u64 = 64 * 1024;

struct SupervisedChild(Child);
impl Drop for SupervisedChild {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

pub fn supervise(name: &str, scenario: fn()) {
    if std::env::var(CHILD).as_deref() == Ok(name) {
        scenario();
        println!("{DONE}");
        return;
    }
    let directory = tempfile::tempdir().expect("child diagnostics");
    let log_path = directory.path().join("child.log");
    let log = fs::File::create(&log_path).expect("bounded scenario log");
    let mut child = SupervisedChild(
        Command::new(std::env::current_exe().expect("test executable"))
            .args([
                "--exact",
                name,
                "--include-ignored",
                "--nocapture",
                "--test-threads=1",
            ])
            .env(CHILD, name)
            .stdin(Stdio::null())
            .stdout(log.try_clone().expect("child stdout"))
            .stderr(log)
            .spawn()
            .expect("isolated standalone scenario"),
    );
    let deadline = Instant::now() + Duration::from_secs(20);
    let status = loop {
        if fs::metadata(&log_path).expect("child log size").len() > MAXIMUM_CHILD_LOG_BYTES {
            child.0.kill().expect("kill oversized-output scenario");
            child.0.wait().expect("reap oversized-output scenario");
            break None;
        }
        if let Some(status) = child.0.try_wait().expect("poll scenario") {
            break Some(status);
        }
        if Instant::now() >= deadline {
            child.0.kill().expect("kill timed-out scenario");
            child.0.wait().expect("reap timed-out scenario");
            break None;
        }
        std::thread::sleep(Duration::from_millis(10));
    };
    let output_within_limit =
        fs::metadata(&log_path).expect("final child log size").len() <= MAXIMUM_CHILD_LOG_BYTES;
    let mut output = String::new();
    fs::File::open(log_path)
        .expect("child output")
        .take(MAXIMUM_CHILD_LOG_BYTES)
        .read_to_string(&mut output)
        .expect("bounded child diagnostic");
    assert!(
        output_within_limit && status.is_some_and(|status| status.success()),
        "scenario {name} failed or exceeded the 20-second / 64-KiB output limits: {status:?}\n{output}"
    );
    assert!(
        output.contains(DONE),
        "exact child assertions were not executed: {output}"
    );
}

pub fn write_config(directory: &Path) -> PathBuf {
    let path = directory.join("node.json");
    let value = serde_json::json!({
        "formatVersion": 1, "dataDirectory": directory.join("data"),
        "nodeId": NODE_ID, "bind": "127.0.0.1:0",
        "workers": {"runtime": 1, "control": 1},
        "cells": [{"class": "standard", "capacity": 1, "queueCapacity": 2,
            "maximumMemoryBytes": 64 * 1024 * 1024}],
        "execution": {"maximumCpuFuel": 100_000_000, "maximumWallTimeMillis": 5000,
            "maximumLogBytes": 16384},
        "shutdownGraceMillis": 500,
        "credentials": [
            {"token": OPERATOR, "subject": "operator", "tenant": "examples", "role": "operator"},
            {"token": CALLER, "subject": "caller", "tenant": "examples", "role": "invoke"},
            {"token": FOREIGN, "subject": "foreign", "tenant": "other", "role": "admin"}
        ]
    });
    fs::write(
        &path,
        serde_json::to_vec(&value).expect("raw JSON configuration"),
    )
    .expect("configuration file");
    path
}

pub fn settings(path: &Path) -> NodeSettings {
    NodeConfig::load(path)
        .expect("bounded configuration load")
        .derive()
        .expect("validated settings")
}

pub struct Runtimes {
    pub invocation: Runtime,
    control: Runtime,
    pub threads: RuntimeThreads,
}

impl Runtimes {
    pub fn new() -> Self {
        let threads = RuntimeThreads::default();
        Self {
            invocation: runtime("standalone-test-invoke", &threads.invocation),
            control: runtime("standalone-test-control", &threads.control),
            threads,
        }
    }

    pub async fn start(&self, settings: NodeSettings) -> StandaloneNode {
        tokio::time::timeout(
            Duration::from_secs(5),
            StandaloneNode::start(
                settings,
                self.control.handle().clone(),
                RuntimeThreads {
                    invocation: Arc::clone(&self.threads.invocation),
                    control: Arc::clone(&self.threads.control),
                },
            ),
        )
        .await
        .expect("bounded startup")
        .expect("standalone node starts")
    }

    pub fn finish(self) {
        drop(self.invocation);
        drop(self.control);
        assert_eq!(self.threads.invocation.load(Ordering::Acquire), 0);
        assert_eq!(self.threads.control.load(Ordering::Acquire), 0);
    }
}

fn runtime(name: &str, observed: &Arc<AtomicUsize>) -> Runtime {
    let started = Arc::clone(observed);
    let stopped = Arc::clone(observed);
    Builder::new_multi_thread()
        .worker_threads(1)
        .max_blocking_threads(1)
        .thread_name(name)
        .on_thread_start(move || {
            started.fetch_add(1, Ordering::Release);
        })
        .on_thread_stop(move || {
            stopped.fetch_sub(1, Ordering::Release);
        })
        .enable_all()
        .build()
        .expect("one-worker owned runtime")
}

pub async fn channel(node: &StandaloneNode) -> Channel {
    Endpoint::from_shared(format!("http://{}", node.endpoint()))
        .expect("actual bound endpoint")
        .connect_timeout(Duration::from_secs(2))
        .timeout(Duration::from_secs(5))
        .connect()
        .await
        .expect("real loopback HTTP/2 channel")
}

pub fn request<T>(token: &str, message: T) -> Request<T> {
    let mut request = Request::new(message);
    request.metadata_mut().insert(
        "authorization",
        format!("Bearer {token}").parse().expect("fixed credential"),
    );
    request.set_timeout(Duration::from_secs(5));
    request
}

pub async fn stop(node: StandaloneNode) {
    let report = tokio::time::timeout(Duration::from_secs(3), node.shutdown())
        .await
        .expect("bounded asynchronous cleanup")
        .expect("clean shutdown report");
    assert_clean(&report);
}

fn assert_clean(report: &ShutdownReport) {
    assert!(
        report.clean && report.telemetry_flushed && report.epoch_helper_joined,
        "{report:?}"
    );
    assert_eq!(
        (
            report.active_connections,
            report.active_rpcs,
            report.active_control_jobs,
            report.active_activations
        ),
        (0, 0, 0, 0)
    );
    assert_eq!(
        (
            report.cancellation_registrations,
            report.observer_correlations
        ),
        (0, 0)
    );
    assert_eq!(
        (report.quota_reservations, report.queued_reservations),
        (0, 0)
    );
    assert_eq!(
        (
            report.reserved_cpu_fuel,
            report.reserved_memory_bytes,
            report.active_leases,
            report.queued_activations,
            report.quarantined_cells
        ),
        (0, 0, 0, 0, 0)
    );
    assert_eq!(
        (
            report.active_backend_invocations,
            report.live_stores,
            report.live_host_states,
            report.live_instances,
            report.live_temporary_buffers,
            report.live_cancellation_probes
        ),
        (0, 0, 0, 0, 0, 0)
    );
    assert_eq!(
        (
            report.instance_reservations,
            report.preparing_components,
            report.preparing_source_bytes,
            report.preparing_metadata_bytes,
        ),
        (0, 0, 0, 0),
    );
    assert!(
        report.telemetry_retained_entries > 0,
        "shutdown diagnostic was flushed"
    );
}
