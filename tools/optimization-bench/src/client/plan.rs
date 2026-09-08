use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::{record, Result};

pub(super) const MAXIMUM_ROW_BYTES: u64 = 16 * 1024;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Plan {
    pub schema: String,
    pub run_id: String,
    pub arm: String,
    pub server_process_id: u32,
    pub endpoint: String,
    pub token_file: PathBuf,
    pub tenant: String,
    pub services: Vec<String>,
    pub contract: String,
    pub route: Option<String>,
    pub function: String,
    pub payload: Value,
    pub warmup_attempts: u32,
    pub measured_attempts: u32,
    pub batch_size: u32,
    pub concurrency: u32,
    pub runtime_workers: u32,
    pub schedule: Schedule,
    pub budget_millis: u64,
    pub cpu_fuel: u64,
    pub memory_bytes: u64,
    pub log_bytes: u64,
    pub connect_timeout_millis: u64,
    pub response_timeout_millis: u64,
    pub maximum_output_bytes: u64,
}

#[derive(Deserialize, Serialize, Clone, Copy)]
#[serde(tag = "mode", deny_unknown_fields)]
pub(super) enum Schedule {
    #[serde(rename = "closed-loop")]
    ClosedLoop,
    #[serde(rename = "scheduled")]
    Scheduled { interval_nanos: u64 },
}

pub(super) struct Prepared {
    pub payload: Vec<u8>,
    pub expected: Vec<u8>,
    pub public_plan: Value,
}

impl Plan {
    pub fn prepare(&self) -> Result<Prepared> {
        self.validate()?;
        let payload = serde_json::to_vec(&self.payload).map_err(|_| "invalid-payload")?;
        if payload.len() > 900 * 1024 {
            return Err("payload-byte-limit");
        }
        let expected = latent_optimization_workloads::invoke(&self.function, &payload)
            .map_err(|_| "invalid-workload-input")?;
        if expected.len() > 1024 * 1024 {
            return Err("expected-output-byte-limit");
        }
        let mut public_plan = serde_json::to_value(self).map_err(|_| "plan-encoding-failed")?;
        let object = public_plan.as_object_mut().ok_or("plan-encoding-failed")?;
        for field in ["token_file", "endpoint", "payload"] {
            object.remove(field);
        }
        object.insert("payload_sha256".into(), record::digest(&payload).into());
        object.insert("payload_bytes".into(), payload.len().to_string().into());
        Ok(Prepared {
            payload,
            expected,
            public_plan,
        })
    }

    pub fn validate(&self) -> Result<()> {
        if self.schema != "latent.optimization.client-plan.v1"
            || !matches!(self.arm.as_str(), "lsf" | "native")
            || self.server_process_id == 0
            || self.run_id.is_empty()
            || self.run_id.len() > 48
            || !self
                .run_id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-')
        {
            return Err("invalid-plan-identity");
        }
        if !identifier(&self.tenant)
            || !identifier(&self.contract)
            || self
                .route
                .as_deref()
                .is_some_and(|route| !identifier(route))
            || self.services.is_empty()
            || self.services.len() > 64
            || !self.services.iter().all(|service| identifier(service))
            || !matches!(self.function.as_str(), "echo" | "compute" | "transform")
        {
            return Err("invalid-plan-target");
        }
        if self.endpoint.len() > 2048
            || !(self.endpoint.starts_with("http://") || self.endpoint.starts_with("https://"))
            || self.endpoint.chars().any(char::is_control)
            || self.token_file.as_os_str().is_empty()
        {
            return Err("invalid-plan-endpoint");
        }
        self.validate_work()
    }

    fn validate_work(&self) -> Result<()> {
        let total = u64::from(self.warmup_attempts) + u64::from(self.measured_attempts);
        if self.measured_attempts == 0
            || total > 1_000_000
            || !(1..=64).contains(&self.concurrency)
            || !(1..=16).contains(&self.runtime_workers)
            || self.batch_size == 0
            || total.div_ceil(u64::from(self.batch_size)) > 10_000
            || !(1..=5000).contains(&self.budget_millis)
            || self.cpu_fuel == 0
            || self.memory_bytes == 0
            || !(1..=5000).contains(&self.connect_timeout_millis)
            || !(1..=5000).contains(&self.response_timeout_millis)
            || self.response_timeout_millis < self.budget_millis
            || self.maximum_output_bytes > 512 * 1024 * 1024
            || total
                .checked_mul(MAXIMUM_ROW_BYTES)
                .and_then(|n| n.checked_add(8 * 1024 * 1024))
                .is_none_or(|n| n > self.maximum_output_bytes)
        {
            return Err("invalid-plan-work-bounds");
        }
        if let Schedule::Scheduled { interval_nanos } = self.schedule {
            if interval_nanos == 0
                || interval_nanos
                    .checked_mul(u64::from(self.measured_attempts))
                    .is_none_or(|n| n > 60 * 60 * 1_000_000_000)
            {
                return Err("invalid-arrival-schedule");
            }
        }
        Ok(())
    }
}

fn identifier(value: &str) -> bool {
    !value.is_empty() && value.len() <= 512 && !value.chars().any(char::is_control)
}

#[cfg(test)]
pub(super) mod tests;
