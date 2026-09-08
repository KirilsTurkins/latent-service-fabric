#[path = "support/supervisor.rs"]
mod supervisor;

use std::fs;
use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use latentd::config::{NodeConfig, NodeSettings};
use latentd::standalone::{RuntimeThreads, ShutdownReport, StandaloneNode};
use tokio::runtime::{Builder, Runtime};

use super::fixture;
pub use supervisor::supervise;

const TOKEN: &str = "shutdown-operator-00000000000000000000";

pub fn settings(directory: &Path) -> NodeSettings {
    let path = directory.join("node.json");
    let config = serde_json::json!({
        "formatVersion": 1, "dataDirectory": directory.join("data"),
        "nodeId": "shutdown-test", "bind": "127.0.0.1:0",
        "workers": {"runtime": 1, "control": 1},
        "cells": [{"class": "standard", "capacity": 1, "queueCapacity": 2,
            "maximumMemoryBytes": fixture::MEMORY}],
        "execution": {"maximumCpuFuel": fixture::FUEL, "maximumWallTimeMillis": 5000,
            "maximumLogBytes": 0},
        "shutdownGraceMillis": 20,
        "credentials": [{"token": TOKEN, "subject": "operator", "tenant": "tests", "role": "operator"}]
    });
    fs::write(&path, serde_json::to_vec(&config).unwrap()).unwrap();
    NodeConfig::load(&path).unwrap().derive().unwrap()
}

pub struct Runtimes {
    pub invocation: Runtime,
    control: Runtime,
    threads: RuntimeThreads,
}

impl Runtimes {
    pub fn new() -> Self {
        let threads = RuntimeThreads::default();
        Self {
            invocation: runtime("shutdown-test-invoke", &threads.invocation),
            control: runtime("shutdown-test-control", &threads.control),
            threads,
        }
    }

    pub async fn start(&self, settings: NodeSettings) -> StandaloneNode {
        StandaloneNode::start(
            settings,
            self.control.handle().clone(),
            RuntimeThreads {
                invocation: Arc::clone(&self.threads.invocation),
                control: Arc::clone(&self.threads.control),
            },
        )
        .await
        .unwrap()
    }

    pub fn finish(self) {
        self.control.shutdown_timeout(Duration::from_secs(1));
        self.invocation.shutdown_timeout(Duration::from_secs(1));
        assert_eq!(self.threads.control.load(Ordering::Acquire), 0);
        assert_eq!(self.threads.invocation.load(Ordering::Acquire), 0);
    }
}

fn runtime(name: &str, counter: &Arc<AtomicUsize>) -> Runtime {
    let started = Arc::clone(counter);
    let stopped = Arc::clone(counter);
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
        .unwrap()
}

pub fn request<T>(message: T) -> tonic::Request<T> {
    let mut request = tonic::Request::new(message);
    request
        .metadata_mut()
        .insert("authorization", format!("Bearer {TOKEN}").parse().unwrap());
    request.set_timeout(Duration::from_secs(5));
    request
}

pub fn assert_clean(report: &ShutdownReport) {
    assert!(
        report.clean && report.telemetry_flushed && report.epoch_helper_joined,
        "{report:?}"
    );
    // A running guest may be quarantined on abandonment; quarantine retains no
    // live activation or Store and the node is already shutting down.
    assert!(report.quarantined_cells <= 1);
    for count in [
        report.active_connections,
        report.active_rpcs,
        report.active_control_jobs,
        report.active_activations,
        report.observer_correlations,
        report.instance_reservations,
        report.preparing_components,
        report.preparing_source_bytes,
        report.preparing_metadata_bytes,
    ] {
        assert_eq!(count, 0, "{report:?}");
    }
    for count in [
        report.cancellation_registrations,
        report.reserved_cpu_fuel,
        report.reserved_memory_bytes,
        report.active_leases,
        report.queued_activations,
        report.active_backend_invocations,
        report.live_stores,
        report.live_host_states,
        report.live_instances,
        report.live_temporary_buffers,
        report.live_cancellation_probes,
    ] {
        assert_eq!(count, 0, "{report:?}");
    }
    assert_eq!(
        (report.quota_reservations, report.queued_reservations),
        (0, 0)
    );
}
