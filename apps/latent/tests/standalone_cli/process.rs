#[path = "process/common.rs"]
mod common;

#[cfg(target_os = "linux")]
use serde_json::Value;
use std::time::Duration;
#[cfg(target_os = "linux")]
use std::{
    process::{Command, Stdio},
    thread,
    time::Instant,
};

pub use common::{Output, Process, OPERATOR};
#[cfg(target_os = "linux")]
pub use common::{CALLER, FOREIGN, GENERIC};

pub const WATCHDOG: Duration = Duration::from_secs(5);

impl Process {
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
                .output_bytes()
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
