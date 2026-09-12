use latent_artifacts::package::PackageSubject;
use serde::{Deserialize, Serialize};

/// Explicit unsigned builder input. Public fields and deserialization confer no
/// authority. Only an approved builder's authenticated statement becomes a proof.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BuildObservation {
    pub format_version: u32,
    pub build_type: String,
    pub source: BuildSource,
    pub component_digest: String,
    pub component_size: u64,
    pub materials: Vec<BuildMaterial>,
    pub parameters: BuildParameters,
    pub started_at: u64,
    pub finished_at: u64,
    pub reproducibility: String,
    pub hermetic: bool,
    pub dependency_completeness: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BuildSource {
    pub repository: String,
    pub revision: String,
    pub snapshot_digest: String,
    pub repository_trust: String,
    pub capture: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BuildMaterial {
    pub name: String,
    pub digest: String,
    pub size: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BuildParameters {
    pub cargo_package: String,
    pub cargo_example: String,
    pub target: String,
    pub profile: String,
    pub locked: bool,
    pub incremental: bool,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct Statement {
    #[serde(rename = "_type")]
    pub(crate) kind: String,
    pub(crate) subject: [Subject; 1],
    pub(crate) predicate_type: String,
    pub(crate) predicate: Predicate,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Subject {
    pub(crate) name: String,
    pub(crate) digest: Sha256,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Sha256 {
    pub(crate) sha256: String,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct Predicate {
    pub(crate) format_version: u32,
    pub(crate) package_subject: PackageSubject,
    pub(crate) builder_id: String,
    pub(crate) issued_at: u64,
    pub(crate) expires_at: u64,
    pub(crate) observation: BuildObservation,
}
