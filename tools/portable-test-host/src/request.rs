use serde::Deserialize;

pub const IMPORTS: [&str; 4] = [
    latent_wasmtime::CONTEXT_IMPORT,
    latent_wasmtime::LOG_IMPORT,
    latent_wasmtime::MONOTONIC_CLOCK_IMPORT,
    latent_wasmtime::WALL_CLOCK_IMPORT,
];

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Request {
    pub schema_version: String,
    pub environment: String,
    pub controlled_development: bool,
    pub component: String,
    pub manifest: String,
    pub contracts: String,
    pub calls: Vec<Call>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Call {
    pub id: String,
    pub service: String,
    pub contract: String,
    pub function: String,
    pub input: String,
    pub grants: Vec<String>,
    pub fuel: String,
    pub memory_bytes: String,
    pub timeout_millis: u64,
    pub cancel_before_start: bool,
}

impl Request {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.schema_version != "latent.dev.portable-request.v1"
            || self.environment != "portable"
            || !self.controlled_development
            || self.calls.is_empty()
            || self.calls.len() > 128
            || self.component.len() > 24 * 1024 * 1024
            || self.manifest.len() > 2 * 1024 * 1024
            || self.contracts.len() > 2 * 1024 * 1024
        {
            return Err("unsupported-portable-request");
        }
        let mut ids = std::collections::BTreeSet::new();
        for call in &self.calls {
            if !ids.insert(&call.id)
                || [&call.id, &call.service, &call.contract, &call.function]
                    .iter()
                    .any(|value| {
                        value.is_empty() || value.len() > 512 || value.chars().any(char::is_control)
                    })
                || call.input.len() > 1_398_104
                || call.grants.len() > IMPORTS.len()
                || call
                    .grants
                    .iter()
                    .any(|grant| !IMPORTS.contains(&grant.as_str()))
                || call
                    .grants
                    .iter()
                    .collect::<std::collections::BTreeSet<_>>()
                    .len()
                    != call.grants.len()
                || call.timeout_millis == 0
                || call.timeout_millis > 5000
            {
                return Err("invalid-portable-call");
            }
            call.budgets()?;
        }
        Ok(())
    }
}

impl Call {
    pub fn budgets(&self) -> Result<(u64, u64), &'static str> {
        let fuel = self.fuel.parse::<u64>().map_err(|_| "fuel-format")?;
        let memory = self
            .memory_bytes
            .parse::<u64>()
            .map_err(|_| "memory-format")?;
        if fuel == 0 || fuel > 10_000_000_000 || !(65536..=64 * 1024 * 1024).contains(&memory) {
            return Err("portable-budget-limit");
        }
        Ok((fuel, memory))
    }
}
