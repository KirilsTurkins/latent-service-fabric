use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use serde_json::json;

use super::super::{plan as legacy, Result};

pub const PREFIX: &str = "latent.optimization.infrastructure-client-";
pub const MAXIMUM_BYTES: u64 = 32 * 1024 * 1024;
pub const MAXIMUM_COMMAND: usize = 64 * 1024;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Plan {
    pub schema: String,
    pub run_id: String,
    pub profile: String,
    pub pair: u32,
    pub token_file: PathBuf,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct Group {
    pub index: u32,
    pub arm: &'static str,
    pub density: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct Phase {
    pub index: u32,
    pub name: &'static str,
    pub kind: &'static str,
    pub function: &'static str,
    pub offers: u32,
    pub concurrency: u32,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Target {
    pub service: String,
    pub endpoint: String,
    pub owner_ref: String,
    pub app_process_id: u32,
}

impl Plan {
    pub fn validate(&self) -> Result<()> {
        if self.schema != format!("{PREFIX}plan.v1")
            || !matches!(self.profile.as_str(), "smoke" | "full")
            || self.pair > 6
            || (self.profile == "smoke" && self.pair != 0)
            || self.token_file.as_os_str().is_empty()
            || !word(&self.run_id, 24)
            || self.run_id.contains('_')
        {
            return Err("invalid-session-plan");
        }
        Ok(())
    }

    pub fn groups(&self) -> Vec<Group> {
        let densities = [1, 8, 32];
        let mut groups = Vec::with_capacity(6);
        for position in 0_u32..3 {
            let index = ((position + self.pair) % 3) as usize;
            let arms = if (self.pair + position).is_multiple_of(2) {
                ["lsf", "native"]
            } else {
                ["native", "lsf"]
            };
            for (arm_index, arm) in (0_u32..).zip(arms) {
                groups.push(Group {
                    index: position * 2 + arm_index,
                    arm,
                    density: densities[index],
                });
            }
        }
        groups
    }

    pub fn phases(&self, group: Group) -> Vec<Phase> {
        let full = self.profile == "full";
        let mut phases = vec![
            Phase {
                index: 0,
                name: "first",
                kind: "first",
                function: "echo",
                offers: group.density,
                concurrency: 1,
            },
            Phase {
                index: 1,
                name: "density-warmup",
                kind: "warmup",
                function: "echo",
                offers: group.density * if full { 4 } else { 1 },
                concurrency: 4,
            },
            Phase {
                index: 2,
                name: "density-measured",
                kind: "measured",
                function: "echo",
                offers: group.density * if full { 4 } else { 1 },
                concurrency: 4,
            },
        ];
        if group.density == 1 {
            for (index, (name, kind, function, offers, concurrency)) in (3_u32..).zip([
                (
                    "echo-c1-warmup",
                    "warmup",
                    "echo",
                    if full { 8 } else { 2 },
                    1,
                ),
                (
                    "echo-c1-measured",
                    "measured",
                    "echo",
                    if full { 128 } else { 8 },
                    1,
                ),
                (
                    "compute-c1-warmup",
                    "warmup",
                    "compute",
                    if full { 4 } else { 1 },
                    1,
                ),
                (
                    "compute-c1-measured",
                    "measured",
                    "compute",
                    if full { 64 } else { 4 },
                    1,
                ),
                (
                    "echo-c4-warmup",
                    "warmup",
                    "echo",
                    if full { 8 } else { 4 },
                    4,
                ),
                (
                    "echo-c4-measured",
                    "measured",
                    "echo",
                    if full { 128 } else { 8 },
                    4,
                ),
            ]) {
                phases.push(Phase {
                    index,
                    name,
                    kind,
                    function,
                    offers,
                    concurrency,
                });
            }
        }
        phases
    }

    pub fn offers(&self) -> u32 {
        if self.profile == "full" {
            1418
        } else {
            300
        }
    }

    pub fn invocation(&self, group: Group, phase: Phase, target: &Target) -> legacy::Plan {
        legacy::Plan {
            schema: "latent.optimization.client-plan.v1".into(),
            run_id: format!(
                "{}-p{}-g{}-s{}",
                self.run_id, self.pair, group.index, phase.index
            ),
            arm: group.arm.into(),
            server_process_id: target.app_process_id,
            endpoint: target.endpoint.clone(),
            token_file: self.token_file.clone(),
            tenant: "optimization".into(),
            services: vec![target.service.clone()],
            contract: "optimization:benchmark/workloads@0.1.0".into(),
            route: None,
            function: phase.function.into(),
            payload: if phase.function == "compute" {
                json!([17, 10000])
            } else {
                json!(["optimization-reference-v1"])
            },
            warmup_attempts: 0,
            measured_attempts: phase.offers,
            batch_size: phase.offers,
            concurrency: phase.concurrency,
            runtime_workers: 2,
            schedule: legacy::Schedule::ClosedLoop,
            budget_millis: 1000,
            cpu_fuel: 10_000_000_000,
            memory_bytes: 64 * 1024 * 1024,
            log_bytes: 16_384,
            connect_timeout_millis: 5000,
            response_timeout_millis: 5000,
            maximum_output_bytes: MAXIMUM_BYTES,
        }
    }
}

pub fn service(index: u32) -> String {
    if index == 0 {
        "optimization/workloads".into()
    } else {
        format!("optimization/workloads-{index}")
    }
}

pub fn targets(group: Group, rows: &[Target]) -> Result<()> {
    if rows.len() != group.density as usize {
        return Err("session-target-count");
    }
    for (index, row) in rows.iter().enumerate() {
        let service_index = u32::try_from(index).map_err(|_| "session-target-count")?;
        if row.service != service(service_index)
            || row.app_process_id == 0
            || row.app_process_id > i32::MAX as u32
            || !word(&row.owner_ref, 128)
            || row.endpoint.len() > 2048
            || !row.endpoint.starts_with("http://")
            || row.endpoint.chars().any(char::is_control)
        {
            return Err("session-target-identity");
        }
        if index > 0 {
            let prior = &rows[..index];
            if group.arm == "lsf" {
                if row.owner_ref != rows[0].owner_ref
                    || row.app_process_id != rows[0].app_process_id
                {
                    return Err("session-lsf-owner-crossed");
                }
            } else if prior
                .iter()
                .any(|old| old.owner_ref == row.owner_ref || old.endpoint == row.endpoint)
            {
                return Err("session-native-owner-crossed");
            }
        }
    }
    Ok(())
}

fn word(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.len() <= maximum
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
}
