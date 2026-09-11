use std::time::{Duration, Instant};

use serde::{Deserialize, Deserializer, Serialize};

use super::{
    plan::{Plan, Target, MAXIMUM_COMMAND, PREFIX},
    Result,
};

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Command {
    pub schema: String,
    pub ordinal: u32,
    pub plan_sha256: String,
    #[serde(rename = "command")]
    pub operation: String,
    #[serde(deserialize_with = "nullable")]
    pub group: Option<u32>,
    #[serde(deserialize_with = "nullable")]
    pub phase: Option<u32>,
    #[serde(deserialize_with = "nullable")]
    pub barrier: Option<String>,
    #[serde(deserialize_with = "nullable")]
    pub targets: Option<Vec<Target>>,
}

fn nullable<'de, D: Deserializer<'de>, T: Deserialize<'de>>(
    deserializer: D,
) -> std::result::Result<Option<T>, D::Error> {
    Option::deserialize(deserializer)
}

#[derive(Clone, Debug)]
pub struct Expected {
    pub command: &'static str,
    pub group: Option<u32>,
    pub phase: Option<u32>,
    pub barrier: Option<&'static str>,
}

pub fn sequence(plan: &Plan) -> Vec<Expected> {
    let mut rows = Vec::with_capacity(61);
    for group in plan.groups() {
        let index = Some(group.index);
        rows.push(Expected {
            command: "begin-group",
            group: index,
            phase: None,
            barrier: None,
        });
        rows.push(Expected {
            command: "inventory",
            group: index,
            phase: None,
            barrier: Some("ready"),
        });
        for phase in plan.phases(group) {
            rows.push(Expected {
                command: "phase",
                group: index,
                phase: Some(phase.index),
                barrier: None,
            });
            if phase.index == 0 {
                rows.push(Expected {
                    command: "inventory",
                    group: index,
                    phase: None,
                    barrier: Some("served"),
                });
            }
        }
        rows.push(Expected {
            command: "inventory",
            group: index,
            phase: None,
            barrier: Some("final"),
        });
        rows.push(Expected {
            command: "finish-group",
            group: index,
            phase: None,
            barrier: None,
        });
    }
    rows.push(Expected {
        command: "finish",
        group: None,
        phase: None,
        barrier: None,
    });
    rows
}

impl Command {
    pub fn validate(&self, expected: &Expected, ordinal: u32, digest: &str) -> Result<()> {
        if self.schema != format!("{PREFIX}command.v1")
            || self.ordinal != ordinal
            || self.plan_sha256 != digest
            || self.operation != expected.command
            || self.group != expected.group
            || self.phase != expected.phase
            || self.barrier.as_deref() != expected.barrier
            || self.targets.is_some() != (self.operation == "begin-group")
        {
            return Err("session-command-order-or-association");
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct Input {
    buffered: Vec<u8>,
}

impl Input {
    pub fn finished(&self) -> Result<()> {
        if !self.buffered.is_empty() {
            return Err("session-extra-input");
        }
        Ok(())
    }

    #[cfg(unix)]
    pub fn command(&mut self, deadline: Instant) -> Result<(Command, Vec<u8>)> {
        use rustix::{
            event::{poll, PollFd, PollFlags, Timespec},
            io::{read, Errno},
        };
        let stdin = std::io::stdin();
        loop {
            if Instant::now() >= deadline {
                return Err("session-control-deadline");
            }
            if let Some(end) = self.buffered.iter().position(|byte| *byte == b'\n') {
                let bytes: Vec<_> = self.buffered.drain(..=end).collect();
                if bytes.len() > MAXIMUM_COMMAND || bytes.len() <= 1 {
                    return Err("session-command-byte-bound");
                }
                let value = serde_json::from_slice(&bytes).map_err(|_| "session-command-json")?;
                return Ok((value, bytes));
            }
            if self.buffered.len() >= MAXIMUM_COMMAND {
                return Err("session-command-byte-bound");
            }
            let remaining = deadline
                .saturating_duration_since(Instant::now())
                .min(Duration::from_millis(250));
            let timeout = Timespec {
                tv_sec: remaining
                    .as_secs()
                    .try_into()
                    .map_err(|_| "session-control-timeout")?,
                tv_nsec: remaining.subsec_nanos().into(),
            };
            let mut fds = [PollFd::new(&stdin, PollFlags::IN)];
            match poll(&mut fds, Some(&timeout)) {
                Ok(0) | Err(Errno::INTR) => continue,
                Err(_) => return Err("session-control-poll"),
                Ok(_) => {}
            }
            let mut chunk = [0_u8; 4096];
            let allowed = chunk.len().min(MAXIMUM_COMMAND - self.buffered.len());
            match read(&stdin, &mut chunk[..allowed]) {
                Ok(0) => return Err("session-control-eof"),
                Ok(count) => self.buffered.extend_from_slice(&chunk[..count]),
                Err(Errno::INTR | Errno::AGAIN) => {}
                Err(_) => return Err("session-control-read"),
            }
        }
    }

    #[cfg(not(unix))]
    pub fn command(&mut self, _deadline: Instant) -> Result<(Command, Vec<u8>)> {
        let _ = (&self.buffered, Duration::ZERO, MAXIMUM_COMMAND);
        Err("session-control-requires-unix")
    }
}
