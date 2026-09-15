use crate::{BuildMaterial, BuildSource};
use serde::{Deserialize, Serialize};

/// Public unsigned data. Output identity is an exact web descriptor table,
/// never a fabricated capsule digest for browser files.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WebBuildObservation {
    pub format_version: u32,
    pub build_type: String,
    pub source: BuildSource,
    pub outputs_digest: String,
    pub outputs_count: usize,
    pub outputs_bytes: u64,
    pub materials: Vec<BuildMaterial>,
    pub parameters: WebAssemblyRecipe,
    pub started_at: u64,
    pub finished_at: u64,
    pub reproducibility: String,
    pub hermetic: bool,
    pub dependency_completeness: String,
}

/// No application command or compiler invocation can be smuggled into the
/// supplied-file assembly recipe. Actual compiler profiles are separately named.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WebAssemblyRecipe {
    pub assembler: String,
    pub recipe_version: u32,
    pub input_mode: String,
}
