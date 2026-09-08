#[path = "support/package.rs"]
pub mod package;

use std::fs;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use super::process::{Output, Process, CALLER, FOREIGN, GENERIC, OPERATOR, WATCHDOG};

pub const NODE_ID: &str = "cli-integration";

pub struct Harness {
    _node_directory: tempfile::TempDir,
    client_directory: tempfile::TempDir,
    pub profile: PathBuf,
    config: PathBuf,
    node: Option<Process>,
    deadline: Instant,
}

impl Harness {
    pub fn start() -> Self {
        Self::start_with_cells(1)
    }

    pub fn start_with_cells(cells: u32) -> Self {
        assert!((1..=2).contains(&cells));
        let node_directory = tempfile::tempdir().expect("node-only files");
        let client_directory = tempfile::tempdir().expect("separate client files");
        let config = node_directory.path().join("node.json");
        fs::write(&config, serde_json::to_vec(&json!({
            "formatVersion":1, "dataDirectory":"data", "nodeId":NODE_ID,
            "bind":"127.0.0.1:0", "workers":{"runtime":1,"control":1},
            "cells":[{"class":"standard","capacity":cells,"queueCapacity":2,"maximumMemoryBytes":67_108_864}],
            "execution":{"maximumCpuFuel":10_000_000_000_u64,"maximumWallTimeMillis":5000,"maximumLogBytes":16384},
            "cache":{"entries":4,"preparations":1}, "catalogs":{"releaseEntries":8,"deployments":8},
            "retention":{"terminalEntries":32,"terminalTtlMillis":30_000},
            "shutdownGraceMillis":200,
            "credentials":[
                {"token":OPERATOR,"subject":"operator","tenant":"examples","role":"operator"},
                {"token":CALLER,"subject":"caller","tenant":"examples","role":"invoke"},
                {"token":GENERIC,"subject":"generic-operator","tenant":"tests","role":"operator"},
                {"token":FOREIGN,"subject":"foreign","tenant":"other","role":"admin"}
            ]
        })).expect("node configuration JSON")).expect("node configuration");
        let mut harness = Self {
            profile: client_directory.path().join("client.json"),
            _node_directory: node_directory,
            client_directory,
            config,
            node: None,
            deadline: Instant::now()
                .checked_add(Duration::from_mins(1))
                .expect("scenario watchdog"),
        };
        harness.restart();
        harness
    }

    pub fn restart(&mut self) {
        assert!(self.node.is_none());
        let binary = PathBuf::from(
            std::env::var_os("LSF_LATENTD_BIN")
                .expect("contract gate must supply the prebuilt latentd binary"),
        );
        assert!(
            binary.is_absolute() && binary.is_file(),
            "explicit node binary path"
        );
        let mut command = Command::new(binary);
        command
            .arg("serve")
            .arg("--config")
            .arg(&self.config)
            .stdin(Stdio::null());
        let mut node = Process::spawn(command, Duration::from_secs(45));
        let started = node.started();
        let endpoint = format!(
            "http://{}",
            started["endpoint"].as_str().expect("bound endpoint")
        );
        let profiles = [
            ("operator", "examples", OPERATOR),
            ("caller", "examples", CALLER),
            ("generic", "tests", GENERIC),
            ("foreign", "other", FOREIGN),
        ]
        .into_iter()
        .map(|(name, tenant, token)| {
            json!({
                "name":name,"endpoint":endpoint,"tenant":tenant,"token":token,
                "connectTimeoutMillis":2000,"rpcTimeoutMillis":4000,
            })
        })
        .collect::<Vec<_>>();
        fs::write(
            &self.profile,
            serde_json::to_vec(&json!({
                "formatVersion":1,"defaultProfile":"operator","profiles":profiles,
            }))
            .expect("profiles JSON"),
        )
        .expect("client-only configuration");
        self.node = Some(node);
    }

    pub fn command(&self, profile: &str, arguments: &[&str]) -> Command {
        self.command_format(profile, arguments, "json")
    }

    pub fn human_command(&self, profile: &str, arguments: &[&str]) -> Command {
        self.command_format(profile, arguments, "human")
    }

    fn command_format(&self, profile: &str, arguments: &[&str], format: &str) -> Command {
        assert!(
            Instant::now() < self.deadline,
            "CLI scenario exceeded its watchdog"
        );
        let mut command = Command::new(env!("CARGO_BIN_EXE_latent"));
        command
            .arg("--config")
            .arg(&self.profile)
            .args(["--profile", profile, "--output", format])
            .args(arguments)
            .current_dir(self.client_directory.path())
            .stdin(Stdio::null());
        command
    }

    pub fn call(&self, profile: &str, arguments: &[&str], code: i32, category: &str) -> Value {
        self.run(profile, arguments).json(code, category)
    }

    pub fn run(&self, profile: &str, arguments: &[&str]) -> Output {
        Process::spawn(self.command(profile, arguments), WATCHDOG).wait()
    }

    pub fn ready(&self) {
        let deadline = Instant::now()
            .checked_add(Duration::from_secs(3))
            .expect("readiness watchdog");
        for _ in 0..20 {
            let value = self.call("operator", &["node", "get", NODE_ID], 0, "success");
            if value["data"]["inventory"]["health"]["ready"] == true {
                return;
            }
            assert!(
                Instant::now() < deadline,
                "fresh Linux PSI readiness was unavailable"
            );
            thread::sleep(Duration::from_millis(25));
        }
        panic!("node did not obtain a fresh ready load sample");
    }

    pub fn stop(&mut self) {
        let node = self.node.take().expect("live node");
        node.signal("-TERM");
        let output = node.wait();
        assert_eq!(output.code, Some(0), "{}", output.stderr);
        assert!(output.stderr.is_empty());
        let records = output
            .stdout
            .lines()
            .map(|line| serde_json::from_str::<Value>(line).expect("node status"))
            .collect::<Vec<_>>();
        assert_eq!(records.len(), 2);
        assert_clean(&records[1]);
    }
}

fn assert_clean(stopped: &Value) {
    assert_eq!(stopped["event"], "stopped");
    assert_eq!(stopped["clean"], true);
    let report = &stopped["report"];
    assert_eq!(report["clean"], true);
    assert_eq!(report["telemetryFlushed"], true);
    assert_eq!(report["epochHelperJoined"], true);
    for field in [
        "activeConnections",
        "activeRpcs",
        "activeControlJobs",
        "activeActivations",
        "cancellationRegistrations",
        "observerCorrelations",
        "quotaReservations",
        "queuedReservations",
        "reservedCpuFuel",
        "reservedMemoryBytes",
        "activeLeases",
        "queuedActivations",
        "activeBackendInvocations",
        "instanceReservations",
        "preparingComponents",
        "preparingSourceBytes",
        "preparingMetadataBytes",
        "liveStores",
        "liveHostStates",
        "liveInstances",
        "liveTemporaryBuffers",
        "liveCancellationProbes",
    ] {
        assert_eq!(report[field].as_u64(), Some(0), "{field}");
    }
}
