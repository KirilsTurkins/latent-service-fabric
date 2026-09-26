use crate::{
    config::{subject, text},
    EventError, NatsEndpoint, Result,
};
use latent_core::ResourceBudget;
use serde::{Deserialize, Serialize};
mod decode;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RootBudget {
    pub cpu_fuel: u64,
    pub memory_bytes: u64,
    pub wall_time_millis: u64,
    pub child_calls: u32,
    pub outbound_requests: u32,
    pub blob_read_bytes: u64,
    pub blob_write_bytes: u64,
    pub log_bytes: u64,
}
impl RootBudget {
    #[must_use]
    pub fn budget(&self) -> ResourceBudget {
        ResourceBudget {
            cpu_fuel: self.cpu_fuel,
            memory_bytes: self.memory_bytes,
            wall_time_limit_millis: Some(self.wall_time_millis),
            child_calls: self.child_calls,
            outbound_requests: self.outbound_requests,
            blob_read_bytes: self.blob_read_bytes,
            blob_write_bytes: self.blob_write_bytes,
            log_bytes: self.log_bytes,
            state_read_bytes: 0,
            state_write_bytes: 0,
            effect_count: 0,
        }
    }
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TriggerBinding {
    pub id: String,
    pub tenant: String,
    pub principal_subject: String,
    pub service: String,
    pub contract: String,
    pub function: String,
    pub route: Option<String>,
    pub stream: String,
    pub consumer: String,
    pub filter_subject: String,
    pub budget: RootBudget,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TriggerConfig {
    pub format_version: u32,
    pub endpoint: NatsEndpoint,
    pub public_roots: bool,
    #[serde(deserialize_with = "decode::roots")]
    pub extra_roots: Vec<Vec<u8>>,
    #[serde(deserialize_with = "decode::bindings")]
    pub bindings: Vec<TriggerBinding>,
    pub maximum_payload_bytes: usize,
    pub operation_timeout_millis: u64,
    pub poll_interval_millis: u64,
    pub maximum_deliveries: u32,
    pub ack_wait_millis: u64,
    pub redelivery_delay_millis: u64,
}
impl TriggerConfig {
    /// Public configuration only. Credential values and consumer positions are
    /// never serialized here. The caller persists these bounded bytes explicitly.
    pub fn to_json(&self) -> Result<Vec<u8>> {
        self.validate()?;
        let bytes = serde_json::to_vec(self).map_err(|_| EventError::InvalidEvent)?;
        if bytes.len() > 524_288 {
            return Err(EventError::InvalidEvent);
        }
        Ok(bytes)
    }
    pub fn from_json(bytes: &[u8]) -> Result<Self> {
        if bytes.len() > 524_288 {
            return Err(EventError::InvalidEvent);
        }
        let config: Self = serde_json::from_slice(bytes).map_err(|_| EventError::InvalidEvent)?;
        config.validate()?;
        Ok(config)
    }
    pub fn validate(&self) -> Result<()> {
        self.endpoint.validate()?;
        if self.format_version != 1
            || self.bindings.is_empty()
            || self.bindings.capacity() > 256
            || self.extra_roots.capacity() > 8
            || (!self.public_roots && self.extra_roots.is_empty())
            || self
                .extra_roots
                .iter()
                .any(|v| v.is_empty() || v.capacity() > 16384)
            || self.extra_roots.iter().map(Vec::capacity).sum::<usize>() > 65536
            || !(1..=32768).contains(&self.maximum_payload_bytes)
            || !(100..=10000).contains(&self.operation_timeout_millis)
            || !(10..=1000).contains(&self.poll_interval_millis)
            || !(1..=16).contains(&self.maximum_deliveries)
            || self.ack_wait_millis < self.operation_timeout_millis + 1000
            || self.ack_wait_millis > 60000
            || !(100..=10000).contains(&self.redelivery_delay_millis)
        {
            return Err(EventError::InvalidEvent);
        }
        let mut tenants: Vec<&str> = Vec::with_capacity(8);
        for (i, binding) in self.bindings.iter().enumerate() {
            for name in [
                &binding.id,
                &binding.tenant,
                &binding.principal_subject,
                &binding.service,
                &binding.function,
                &binding.stream,
                &binding.consumer,
                &binding.filter_subject,
            ] {
                if !text(name, 128) || name.capacity() > 128 {
                    return Err(EventError::InvalidEvent);
                }
            }
            if !text(&binding.contract, 256)
                || binding.contract.capacity() > 256
                || binding
                    .route
                    .as_ref()
                    .is_some_and(|r| !text(r, 128) || r.capacity() > 128)
                || !subject(&binding.filter_subject)
                || !identifier(&binding.stream)
                || !identifier(&binding.consumer)
                || binding.budget.cpu_fuel == 0
                || binding.budget.memory_bytes == 0
                || binding.budget.wall_time_millis == 0
                || binding.budget.wall_time_millis > self.operation_timeout_millis
                || self.bindings[..i].iter().any(|old| {
                    old.id == binding.id
                        || (old.stream == binding.stream && old.consumer == binding.consumer)
                        || (old.tenant != binding.tenant
                            && old.filter_subject == binding.filter_subject)
                })
            {
                return Err(EventError::InvalidEvent);
            }
            latent_core::BudgetProfile::Phase3
                .validate_request(&binding.budget.budget())
                .map_err(|_| EventError::InvalidEvent)?;
            if !tenants.contains(&binding.tenant.as_str()) {
                if tenants.len() == 8 {
                    return Err(EventError::InvalidEvent);
                }
                tenants.push(&binding.tenant);
            }
        }
        Ok(())
    }
}
pub(super) fn identifier(value: &str) -> bool {
    subject(value) && !value.contains('.')
}
