mod capture;

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use capture::Capture;

pub const TOKEN: &str = "standalone-command-test-secret-0000000001";
const WATCHDOG: Duration = Duration::from_secs(10);

pub fn configuration(directory: &Path) -> PathBuf {
    let path = directory.join("node.json");
    fs::write(
        &path,
        serde_json::to_vec(&json!({
            "formatVersion": 1,
            "dataDirectory": "data",
            "bind": "127.0.0.1:0",
            "nodeId": "command-test",
            "workers": {"runtime": 1, "control": 1},
            "cells": [{"class": "standard", "capacity": 1,
                "queueCapacity": 1, "maximumMemoryBytes": 65536}],
            "shutdownGraceMillis": 200,
            "credentials": [{"token": TOKEN, "subject": "operator",
                "tenant": "acme", "role": "operator"}]
        }))
        .unwrap(),
    )
    .unwrap();
    path
}

/// Actual child ownership, a parent-clock watchdog, and bounded pipe readers.
/// Every panic kills/reaps the node before joining the readers.
pub struct Process {
    child: Child,
    output: Capture,
    errors: Capture,
    readers: Vec<JoinHandle<()>>,
    deadline: Instant,
}

impl Process {
    pub fn node(config: &Path) -> Self {
        let mut command = Command::new(env!("CARGO_BIN_EXE_latentd"));
        command.arg("serve").arg("--config").arg(config);
        Self::spawn(command)
    }

    fn spawn(mut command: Command) -> Self {
        let child = command
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let mut process = Self {
            child,
            output: Capture::default(),
            errors: Capture::default(),
            readers: Vec::with_capacity(2),
            deadline: Instant::now() + WATCHDOG,
        };
        process
            .readers
            .push(process.output.read(process.child.stdout.take().unwrap()));
        process
            .readers
            .push(process.errors.read(process.child.stderr.take().unwrap()));
        process
    }

    fn check(&self) {
        self.output.check();
        self.errors.check();
        assert!(
            Instant::now() < self.deadline,
            "standalone process watchdog expired"
        );
    }

    pub fn started(&mut self) -> Value {
        loop {
            self.check();
            if let Some(record) = self.records().into_iter().next() {
                assert!(matches!(
                    record["event"].as_str(),
                    Some("ready" | "started")
                ));
                return record;
            }
            assert!(
                self.child.try_wait().unwrap().is_none(),
                "node exited before startup: {}",
                self.error_text()
            );
            thread::sleep(Duration::from_millis(5));
        }
    }

    pub fn signal(&self, signal: &str) {
        assert!(matches!(signal, "-TERM" | "-INT"));
        let mut command = Command::new("kill");
        command.arg(signal).arg(self.child.id().to_string());
        assert!(Self::spawn(command).wait().success());
    }

    pub fn wait(&mut self) -> ExitStatus {
        loop {
            self.check();
            if let Some(status) = self.child.try_wait().unwrap() {
                self.join_readers();
                self.check();
                return status;
            }
            thread::sleep(Duration::from_millis(5));
        }
    }

    pub fn records(&self) -> Vec<Value> {
        let bytes = self.output.bytes();
        bytes
            .split_inclusive(|byte| *byte == b'\n')
            .filter(|line| line.last() == Some(&b'\n'))
            .map(|line| serde_json::from_slice(line).unwrap())
            .collect()
    }

    pub fn error_text(&self) -> String {
        String::from_utf8(self.errors.bytes()).unwrap()
    }

    fn join_readers(&mut self) {
        for reader in self.readers.drain(..) {
            reader.join().unwrap();
        }
    }
}

impl Drop for Process {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        // Reader panics must not trigger a second panic during cleanup.
        for reader in self.readers.drain(..) {
            let _ = reader.join();
        }
    }
}
