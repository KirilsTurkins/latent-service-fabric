//! A fixed restoration origin, not a caller-supplied historical route snapshot.
use super::{codec, invalid, Result};
use latent_core::{ArtifactBlobDigest, RouteGeneration};
use latent_manifest::__serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub struct RolloutRollbackTarget {
    pub format_version: u32,
    #[serde(with = "codec::generation")]
    pub historical_route_generation: RouteGeneration,
    #[serde(with = "codec::text")]
    pub manifest_digest: ArtifactBlobDigest,
}
impl RolloutRollbackTarget {
    pub fn validate(&self) -> Result<()> {
        if self.format_version != 1 || self.historical_route_generation.0 == 0 {
            return Err(invalid());
        }
        Ok(())
    }
}
