use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Default, Deserialize, Serialize)]
pub enum RuntimeProfile {
    #[default]
    #[serde(rename = "standard-v1")]
    Standard,
    #[serde(rename = "java-linear-v1")]
    Java,
    #[serde(rename = "dotnet-native-aot-v1")]
    Dotnet,
    #[serde(rename = "typescript-spidermonkey-v1")]
    TypeScript,
}

impl RuntimeProfile {
    pub fn maximum_memory(self) -> u64 {
        match self {
            Self::Standard | Self::Java => 64 * 1024 * 1024,
            Self::Dotnet | Self::TypeScript => 128 * 1024 * 1024,
        }
    }
}

pub const IMPORTS: [&str; 7] = [
    latent_wasmtime::CONTEXT_IMPORT,
    latent_wasmtime::LOG_IMPORT,
    latent_wasmtime::MONOTONIC_CLOCK_IMPORT,
    latent_wasmtime::WALL_CLOCK_IMPORT,
    latent_capabilities::broker::random::RANDOM_CAPABILITY,
    latent_capabilities::broker::metrics::METRICS_CAPABILITY,
    latent_capabilities::broker::http::HTTP_CAPABILITY,
];

#[derive(Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Fixtures {
    pub entropy: Option<String>,
    #[serde(default)]
    pub metrics: Vec<latent_telemetry::custom::CustomMetricDescriptor>,
    pub http: Option<super::http_fixture::Fixture>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Request {
    pub schema_version: String,
    pub environment: String,
    pub controlled_development: bool,
    #[serde(default)]
    pub runtime_profile: RuntimeProfile,
    pub component: String,
    pub manifest: String,
    pub contracts: String,
    pub calls: Vec<Call>,
    #[serde(default)]
    pub fixtures: Fixtures,
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
    #[serde(default)]
    pub denied_capabilities: Vec<String>,
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
            || self
                .fixtures
                .entropy
                .as_ref()
                .is_some_and(|value| value.is_empty() || value.len() > 5464)
            || self.fixtures.metrics.len() > latent_policy::capability::MAX_SET_ENTRIES
            || self
                .calls
                .iter()
                .map(|call| &call.service)
                .collect::<std::collections::BTreeSet<_>>()
                .len()
                > latent_policy::capability::MAX_SET_ENTRIES
        {
            return Err("unsupported-portable-request");
        }
        let mut ids = std::collections::BTreeSet::new();
        if let Some(http) = &self.fixtures.http {
            http.validate()?;
        }
        for call in &self.calls {
            if !ids.insert(&call.id)
                || [&call.id, &call.service, &call.contract, &call.function]
                    .iter()
                    .any(|value| {
                        value.is_empty() || value.len() > 512 || value.chars().any(char::is_control)
                    })
                || call.input.len() > 1_398_104
                || call.grants.len() > IMPORTS.len()
                || call.denied_capabilities.len() > IMPORTS.len()
                || call
                    .denied_capabilities
                    .iter()
                    .any(|capability| !call.grants.contains(capability))
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
            call.budgets(self.runtime_profile)?;
        }
        Ok(())
    }
}

impl Call {
    pub fn budgets(&self, profile: RuntimeProfile) -> Result<(u64, u64), &'static str> {
        if [&self.fuel, &self.memory_bytes].iter().any(|value| {
            value.is_empty()
                || value.len() > 20
                || value.starts_with('0')
                || !value.bytes().all(|b| b.is_ascii_digit())
        }) {
            return Err("canonical-decimal-budget-required");
        }
        let fuel = self.fuel.parse::<u64>().map_err(|_| "fuel-format")?;
        let memory = self
            .memory_bytes
            .parse::<u64>()
            .map_err(|_| "memory-format")?;
        if fuel == 0
            || fuel > 10_000_000_000
            || !(65536..=profile.maximum_memory()).contains(&memory)
        {
            return Err("portable-budget-limit");
        }
        Ok((fuel, memory))
    }
}
