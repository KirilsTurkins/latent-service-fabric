use std::io::Read;
use std::process::{ExitStatus, Stdio};
use std::time::Duration;

use serde_json::{json, Value};
use tokio::process::{Child, Command};

use super::command::{App, Args, CHILD_LISTEN};
use super::Result;

#[cfg(all(test, unix))]
#[path = "child_tests.rs"]
mod tests;

pub(super) fn spawn(args: &Args) -> Result<Child> {
    let mut command = Command::new(&args.executable);
    match args.app {
        App::Lsf => {
            command
                .arg("serve")
                .arg("--config")
                .arg(args.config.as_ref().ok_or("child-config")?);
        }
        App::Native => {
            let mut bytes = Vec::new();
            std::fs::File::open(args.token_file.as_ref().ok_or("child-token-path")?)
                .map_err(|_| "child-token-open")?
                .take(259)
                .read_to_end(&mut bytes)
                .map_err(|_| "child-token-read")?;
            if bytes.len() > 258 {
                return Err("child-token-size");
            }
            let token = std::str::from_utf8(&bytes)
                .map_err(|_| "child-token-encoding")?
                .trim_end_matches(['\r', '\n']);
            if !(32..=256).contains(&token.len())
                || !token
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
            {
                return Err("child-token-invalid");
            }
            command
                .arg("--listen")
                .arg(CHILD_LISTEN)
                .arg("--token")
                .arg(token)
                .arg("--services")
                .arg(args.service.as_ref().ok_or("child-service")?)
                .arg("--concurrency")
                .arg("4")
                .arg("--timeout-ms")
                .arg("5000");
        }
    }
    // No shell, inherited stdin, full command Debug, or credential diagnostics.
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .map_err(|_| "child-spawn")
}

pub(super) struct Exit {
    pub reaped: bool,
    pub term_sent: bool,
    pub kill_sent: bool,
    pub status: Option<ExitStatus>,
    pub error: Option<&'static str>,
}

impl Exit {
    pub fn success(&self) -> bool {
        self.reaped
            && !self.kill_sent
            && self.error.is_none()
            && self.status.is_some_and(|status| status.success())
    }
    pub fn value(&self) -> Value {
        #[cfg(unix)]
        let signal = self.status.as_ref().and_then(|status| {
            use std::os::unix::process::ExitStatusExt;
            status.signal()
        });
        #[cfg(not(unix))]
        let signal: Option<i32> = None;
        json!({"reaped":self.reaped,"term_sent":self.term_sent,"kill_sent":self.kill_sent,
            "exit_code":self.status.as_ref().and_then(ExitStatus::code),"signal":signal,"error":self.error})
    }
}

pub(super) async fn stop(child: &mut Child, already: Option<std::io::Result<ExitStatus>>) -> Exit {
    let initial_error = match already {
        Some(Ok(status)) => {
            return Exit {
                reaped: true,
                term_sent: false,
                kill_sent: false,
                status: Some(status),
                error: None,
            }
        }
        Some(Err(_)) => Some("child-wait"),
        None => None,
    };
    let mut receipt = Exit {
        reaped: false,
        term_sent: false,
        kill_sent: false,
        status: None,
        error: initial_error,
    };
    #[cfg(unix)]
    {
        let sent = child
            .id()
            .and_then(|id| i32::try_from(id).ok())
            .and_then(rustix::process::Pid::from_raw)
            .is_some_and(|pid| {
                rustix::process::kill_process(pid, rustix::process::Signal::TERM).is_ok()
            });
        receipt.term_sent = sent;
        if !sent {
            receipt.error = Some("child-term");
        }
    }
    #[cfg(not(unix))]
    {
        receipt.error = Some("child-term-unsupported");
    }
    if let Ok(result) = tokio::time::timeout(Duration::from_secs(10), child.wait()).await {
        match result {
            Ok(status) => {
                receipt.reaped = true;
                receipt.status = Some(status);
            }
            Err(_) => receipt.error = Some("child-wait"),
        }
        return receipt;
    }
    receipt.kill_sent = child.start_kill().is_ok();
    receipt.error = Some("child-grace-exceeded");
    if let Ok(Ok(status)) = tokio::time::timeout(Duration::from_secs(5), child.wait()).await {
        receipt.reaped = true;
        receipt.status = Some(status);
    }
    receipt
}
