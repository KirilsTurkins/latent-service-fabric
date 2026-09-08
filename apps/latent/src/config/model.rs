use serde::Deserialize;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Document {
    pub format_version: u32,
    pub default_profile: Option<String>,
    pub profiles: Vec<Profile>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Profile {
    pub name: String,
    pub endpoint: String,
    pub tenant: String,
    pub token: String,
    #[serde(default = "connect_timeout")]
    pub connect_timeout_millis: u64,
    #[serde(default = "rpc_timeout")]
    pub rpc_timeout_millis: u64,
    #[serde(default)]
    pub limits: InputLimits,
}

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
// Rust names match the operator configuration fields.
#[allow(clippy::struct_field_names)]
pub struct InputLimits {
    pub maximum_component_bytes: usize,
    pub maximum_payload_bytes: usize,
    pub maximum_response_bytes: usize,
}

impl Default for InputLimits {
    fn default() -> Self {
        Self {
            maximum_component_bytes: 16 * 1024 * 1024,
            maximum_payload_bytes: 1024 * 1024,
            maximum_response_bytes: 4 * 1024 * 1024,
        }
    }
}

const fn connect_timeout() -> u64 {
    2000
}

const fn rpc_timeout() -> u64 {
    1000
}
