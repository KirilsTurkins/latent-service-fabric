use super::Harness;
use latent_testkit::conformance::ShutdownEvidence;
use latent_testkit::process::{OwnedProcess, ProcessLimits};
use serde_json::Value;
use std::process::Command;

impl Harness {
    pub async fn stop(&mut self) -> ShutdownEvidence {
        let node = self.node.take().expect("owned live node");
        let identity = self
            .probe
            .as_ref()
            .expect("bound child identity")
            .identity();
        assert_eq!(node.id(), identity.process_id);
        self.work
            .before_command(false)
            .expect("shutdown signal command budget");
        let mut command = Command::new("/bin/kill");
        command.arg("-TERM").arg(node.id().to_string());
        let signal = OwnedProcess::spawn(command, ProcessLimits::default())
            .expect("bounded SIGTERM helper")
            .wait()
            .await
            .expect("SIGTERM helper reaped and readers joined");
        assert!(signal.status.success());
        self.capture("node-signal", &signal);
        let output = node
            .wait()
            .await
            .expect("node exited, reaped, readers joined");
        self.capture("node", &output);
        assert!(output.status.success(), "clean shutdown exit");
        assert!(output.stderr.is_empty());
        let text = std::str::from_utf8(&output.stdout).expect("node UTF-8 status");
        let records = text
            .lines()
            .map(|line| serde_json::from_str::<Value>(line).expect("finite node record"))
            .collect::<Vec<_>>();
        assert_eq!(records.len(), 2);
        let stopped = &records[1];
        assert_eq!(stopped["event"], "stopped");
        assert_eq!(stopped["clean"], true);
        assert_clean(&stopped["report"]);
        ShutdownEvidence {
            node_instance: 1,
            process_id: identity.process_id,
            start_time_ticks: identity.start_time_ticks,
            exit_success: true,
            reaped: true,
            readers_joined: true,
            report: stopped["report"].clone(),
        }
    }
}

fn assert_clean(report: &Value) {
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
