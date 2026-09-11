#[path = "process/capture.rs"]
mod capture;

use std::process::{Child, Command, Stdio};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use serde_json::Value;

use capture::Capture;

pub const OPERATOR: &str = "cli-operator-private-00000000000000000001";
pub const FOREIGN: &str = "cli-foreign-private-000000000000000000001";
pub const GENERIC: &str = "cli-generic-private-000000000000000000001";
pub const CALLER: &str = "cli-caller-private-0000000000000000000001";
pub const WATCHDOG: Duration = Duration::from_secs(5);

pub struct Output {
    pub code: Option<i32>,
    pub stdout: String,
    pub stderr: String,
}

impl Output {
    pub fn json(&self, code: i32, category: &str) -> Value {
        assert_eq!(self.code, Some(code), "{}\n{}", self.stdout, self.stderr);
        assert!(
            self.stderr.is_empty(),
            "JSON command emitted stderr diagnostics"
        );
        assert_eq!(self.stdout.lines().count(), 1, "one JSON result record");
        assert!(self.stdout.ends_with('\n'));
        let value: Value = serde_json::from_str(&self.stdout).expect("one complete JSON document");
        assert_eq!(value["schemaVersion"], "latent.cli.result.v1");
        assert_eq!(value["category"], category);
        assert!(value["requestDispatched"].is_boolean());
        assert!(value["outcomeKnown"].is_boolean());
        value
    }
}

/// Owns child and bounded readers together; cleanup kills/reaps before joining.
pub struct Process {
    child: Child,
    output: Capture,
    errors: Capture,
    readers: Vec<JoinHandle<()>>,
    deadline: Instant,
}

impl Process {
    pub fn spawn(mut command: Command, watchdog: Duration) -> Self {
        let mut child = command
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("bounded test child");
        let output = Capture::default();
        let errors = Capture::default();
        let readers = vec![
            output.read(child.stdout.take().expect("child stdout")),
            errors.read(child.stderr.take().expect("child stderr")),
        ];
        Self {
            child,
            output,
            errors,
            readers,
            deadline: Instant::now()
                .checked_add(watchdog)
                .expect("bounded watchdog"),
        }
    }

    fn check(&self) {
        self.output.check();
        self.errors.check();
        assert!(
            Instant::now() < self.deadline,
            "test child exceeded its watchdog"
        );
    }

    pub fn wait(mut self) -> Output {
        loop {
            self.check();
            if let Some(status) = self.child.try_wait().expect("poll test child") {
                for reader in self.readers.drain(..) {
                    reader.join().expect("bounded pipe reader");
                }
                self.check();
                let stdout = String::from_utf8(self.output.bytes()).expect("UTF-8 stdout");
                let stderr = String::from_utf8(self.errors.bytes()).expect("UTF-8 stderr");
                for secret in [OPERATOR, FOREIGN, GENERIC, CALLER] {
                    assert!(
                        !stdout.contains(secret) && !stderr.contains(secret),
                        "credential leaked"
                    );
                }
                return Output {
                    code: status.code(),
                    stdout,
                    stderr,
                };
            }
            thread::sleep(Duration::from_millis(5));
        }
    }

    #[cfg(target_os = "linux")]
    pub fn started(&mut self) -> Value {
        let deadline = Instant::now()
            .checked_add(WATCHDOG)
            .expect("startup watchdog");
        loop {
            self.check();
            assert!(
                Instant::now() < deadline,
                "node startup exceeded its watchdog"
            );
            if let Some(line) = self
                .output
                .bytes()
                .split_inclusive(|byte| *byte == b'\n')
                .find(|line| line.last() == Some(&b'\n'))
            {
                let value: Value = serde_json::from_slice(line).expect("node startup JSON");
                assert!(matches!(value["event"].as_str(), Some("ready" | "started")));
                return value;
            }
            assert!(
                self.child.try_wait().expect("node status").is_none(),
                "node exited before startup"
            );
            thread::sleep(Duration::from_millis(5));
        }
    }

    #[cfg(target_os = "linux")]
    pub fn signal(&self, signal: &str) {
        assert!(matches!(signal, "-TERM" | "-INT"));
        let mut command = Command::new("kill");
        command
            .arg(signal)
            .arg(self.child.id().to_string())
            .stdin(Stdio::null());
        assert_eq!(Self::spawn(command, WATCHDOG).wait().code, Some(0));
    }
}

impl Drop for Process {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        for reader in self.readers.drain(..) {
            let _ = reader.join();
        }
    }
}
