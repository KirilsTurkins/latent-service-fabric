#[path = "harness/configuration.rs"]
mod configuration;
#[path = "harness/output.rs"]
mod output;
#[path = "harness/shutdown.rs"]
mod shutdown;

use std::path::PathBuf;
use std::process::Command;
use std::time::{Duration, Instant};

use latent_testkit::conformance::{ArtifactReference, ProcessSample, WorkCounter};
use latent_testkit::process::{OwnedProcess, ProcessLimits};
use latent_testkit::resources::{ChildProcessProbe, ProbeLimits};
use serde_json::Value;

use super::fixtures::{required_path, Package};
pub use configuration::NODE_ID;
pub use output::PendingCli;

pub struct Harness {
    _node_directory: tempfile::TempDir,
    client_directory: tempfile::TempDir,
    pub config: PathBuf,
    pub public_config: Value,
    profile: PathBuf,
    node: Option<OwnedProcess>,
    node_started_at: Option<Instant>,
    probe: Option<ChildProcessProbe>,
    output: PathBuf,
    artifacts: Vec<ArtifactReference>,
    pub work: WorkCounter,
    samples: u64,
    origin: Instant,
}

impl Harness {
    pub fn new(output: PathBuf, work: WorkCounter) -> Self {
        let node_directory = tempfile::tempdir().expect("isolated node directory");
        let client_directory = tempfile::tempdir().expect("separate client directory");
        let config = node_directory.path().join("node.json");
        let (private, public_config) = configuration::node();
        std::fs::write(&config, serde_json::to_vec(&private).expect("node JSON"))
            .expect("node configuration");
        Self {
            config,
            public_config,
            profile: client_directory.path().join("profiles.json"),
            _node_directory: node_directory,
            client_directory,
            node: None,
            node_started_at: None,
            probe: None,
            output,
            artifacts: Vec::new(),
            work,
            samples: 0,
            origin: Instant::now(),
        }
    }

    pub async fn start(&mut self) {
        assert!(self.node.is_none(), "at most one live conformance node");
        self.work
            .before_command(false)
            .expect("node command budget");
        let mut command = Command::new(required_path("LSF_LATENTD_BIN"));
        command.arg("serve").arg("--config").arg(&self.config);
        let mut node = OwnedProcess::spawn(
            command,
            ProcessLimits {
                timeout: Duration::from_secs(65),
                ..ProcessLimits::default()
            },
        )
        .expect("start actual node");
        let line = tokio::time::timeout(Duration::from_secs(5), node.wait_for_stdout_line())
            .await
            .expect("startup watchdog")
            .expect("bounded startup record");
        let started: Value = serde_json::from_slice(&line).expect("node startup JSON");
        assert!(matches!(
            started["event"].as_str(),
            Some("ready" | "started")
        ));
        self.node_started_at = Some(Instant::now());
        let endpoint = format!(
            "http://{}",
            started["endpoint"].as_str().expect("actual listener")
        );
        configuration::profiles(&self.profile, &endpoint);
        self.probe = Some(
            ChildProcessProbe::bind(&mut node, ProbeLimits::default())
                .expect("live retained child probe"),
        );
        self.node = Some(node);
    }

    #[must_use]
    pub fn node_age(&self) -> Duration {
        self.node_started_at
            .expect("actual startup record was observed")
            .elapsed()
    }

    pub fn spawn_cli(&mut self, profile: &str, args: &[&str]) -> PendingCli {
        self.work
            .before_command(args.first() == Some(&"invoke"))
            .expect("hard CLI command and Invoke budgets");
        let sequence = self.work.snapshot().commands;
        let mut command = Command::new(env!("CARGO_BIN_EXE_latent"));
        command
            .arg("--config")
            .arg(&self.profile)
            .args(["--profile", profile, "--output", "json"])
            .args(args)
            .current_dir(self.client_directory.path());
        PendingCli {
            sequence,
            process: OwnedProcess::spawn(
                command,
                ProcessLimits {
                    timeout: Duration::from_secs(8),
                    ..ProcessLimits::default()
                },
            )
            .expect("bounded CLI child"),
        }
    }

    pub async fn call(&mut self, profile: &str, args: &[&str], code: i32, category: &str) -> Value {
        let pending = self.spawn_cli(profile, args);
        self.finish_cli(pending, code, category).await
    }

    pub async fn invoke(
        &mut self,
        package: &Package,
        function: &str,
        id: &str,
        input: &std::path::Path,
        extra: &[&str],
        expected: (i32, &str),
    ) -> Value {
        let mut args = invoke_args(package, function, id, input);
        args.extend_from_slice(extra);
        self.call(package.profile(), &args, expected.0, expected.1)
            .await
    }

    pub async fn inventory(&mut self) -> Value {
        self.call("tests", &["node", "get", NODE_ID], 0, "success")
            .await["data"]["inventory"]
            .clone()
    }

    pub async fn ready(&mut self) -> Value {
        for _ in 0..20 {
            let inventory = self.inventory().await;
            if inventory["health"]["ready"] == true {
                return inventory;
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
        panic!("fresh ready Linux PSI observation missing");
    }

    pub async fn sample(&mut self, phase: &str) -> ProcessSample {
        let started = u64::try_from(self.origin.elapsed().as_micros()).expect("sample time");
        let inventory = self.inventory().await;
        let process = self
            .probe
            .as_ref()
            .expect("bound probe")
            .capture(self.node.as_mut().expect("live node"))
            .expect("actual child resources");
        assert_ne!(process.identity.process_id, std::process::id());
        assert!(
            process.descendants.is_empty(),
            "node owns no child process tree"
        );
        assert_eq!(process.listening_tcp_socket_count, 1, "one owned listener");
        assert!(process
            .process
            .resident_memory_bytes
            .is_some_and(|bytes| bytes > 0));
        self.samples += 1;
        ProcessSample {
            sequence: self.samples,
            node_instance: 1,
            phase: phase.to_owned(),
            process,
            inventory,
            sample_started_micros: started,
            sample_finished_micros: u64::try_from(self.origin.elapsed().as_micros())
                .expect("sample time"),
        }
    }

    pub fn take_artifacts(&mut self) -> Vec<ArtifactReference> {
        std::mem::take(&mut self.artifacts)
    }
}

pub fn invoke_args<'a>(
    package: &'a Package,
    function: &'a str,
    id: &'a str,
    input: &'a std::path::Path,
) -> Vec<&'a str> {
    vec![
        "invoke",
        "--service",
        &package.service,
        "--contract",
        &package.contract,
        "--function",
        function,
        "--input",
        super::fixtures::path(input),
        "--activation-id",
        id,
    ]
}
