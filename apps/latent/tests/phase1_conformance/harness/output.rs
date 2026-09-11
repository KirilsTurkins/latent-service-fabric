use latent_testkit::process::{CapturedProcess, OwnedProcess};
use serde_json::Value;

use super::{configuration::TOKENS, Harness};
use crate::evidence::write_artifact;

pub struct PendingCli {
    pub(super) sequence: u64,
    pub(super) process: OwnedProcess,
}

impl Harness {
    pub async fn finish_cli(&mut self, pending: PendingCli, code: i32, category: &str) -> Value {
        let output = pending
            .process
            .wait()
            .await
            .expect("CLI exited and readers joined within watchdog");
        self.capture(&format!("cli-{:03}", pending.sequence), &output);
        response(&output, code, category)
    }

    pub async fn finish_status_poll(&mut self, pending: PendingCli) -> Option<Value> {
        let output = pending
            .process
            .wait()
            .await
            .expect("Status child reaped within watchdog");
        self.capture(&format!("cli-{:03}", pending.sequence), &output);
        if output.status.code() == Some(0) {
            Some(response(&output, 0, "success"))
        } else {
            response(&output, 6, "not-found");
            None
        }
    }

    pub(super) fn capture(&mut self, prefix: &str, output: &CapturedProcess) {
        for (suffix, bytes) in [("stdout", &output.stdout), ("stderr", &output.stderr)] {
            let text = std::str::from_utf8(bytes).expect("finite UTF-8 process output");
            assert!(
                TOKENS.iter().all(|token| !text.contains(token)),
                "credentials leaked"
            );
            self.artifacts.push(write_artifact(
                &self.output,
                &format!("{prefix}.{suffix}"),
                bytes,
            ));
        }
    }
}

pub fn response(output: &CapturedProcess, code: i32, category: &str) -> Value {
    assert_eq!(
        output.status.code(),
        Some(code),
        "unexpected bounded CLI exit"
    );
    assert!(
        output.stderr.is_empty(),
        "JSON CLI diagnostics belong in the envelope"
    );
    let text = std::str::from_utf8(&output.stdout).expect("CLI UTF-8 output");
    assert_eq!(text.lines().count(), 1);
    assert!(text.ends_with('\n'));
    let value: Value = serde_json::from_slice(&output.stdout).expect("CLI result JSON");
    assert_eq!(value["schemaVersion"], "latent.cli.result.v1");
    assert_eq!(value["category"], category);
    assert!(value["requestDispatched"].is_boolean());
    assert!(value["outcomeKnown"].is_boolean());
    value
}
