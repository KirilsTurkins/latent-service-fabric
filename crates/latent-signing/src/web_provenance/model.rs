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
    pub parameters: WebBuildRecipe,
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

/// Disjoint, closed recipes. The legacy supplied-file wire shape is unchanged.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum WebBuildRecipe {
    Assembly(WebAssemblyRecipe),
    Angular(AngularBuildRecipe),
}

impl From<WebAssemblyRecipe> for WebBuildRecipe {
    fn from(value: WebAssemblyRecipe) -> Self {
        Self::Assembly(value)
    }
}

/// Observed compilation and composition, distinct from supplied-file assembly.
/// Material identities bind the compiler, embedding, adapter, WIT, locks and
/// actual installed tools. The final renderer is also an exact package output.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AngularBuildRecipe {
    pub compiler: String,
    pub recipe_version: u32,
    pub renderer_profile: String,
    pub profile_digest: String,
    pub renderer_digest: String,
    pub renderer_size: u64,
    pub max_hydration_bytes: u32,
    pub lifecycle_scripts: bool,
}
