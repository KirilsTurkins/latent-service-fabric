use super::RECIPE;
use crate::embedded::StoreError;
use sha2::{Digest, Sha256};

/// Closed installed recipes. Selecting one describes data only; the original
/// checkpoint, reviewed schema, quiescence and current writer fence still apply.
/// Requests cannot provide an arbitrary key or transformer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AggregateMigrationRecipe {
    Count,
    JavaAggregate,
}

impl AggregateMigrationRecipe {
    #[must_use]
    pub fn bytes(self) -> &'static [u8] {
        match self {
            Self::Count => RECIPE,
            Self::JavaAggregate => include_bytes!(
                "../../../../../contracts/state/java-aggregate-v1-to-v2-migration.json"
            ),
        }
    }

    #[must_use]
    pub fn identity(self) -> &'static str {
        match self {
            Self::Count => "lsf.aggregate-migration.v1",
            Self::JavaAggregate => "lsf.java-aggregate-migration.v1",
        }
    }

    #[must_use]
    pub fn digest(self) -> [u8; 32] {
        Sha256::digest(self.bytes()).into()
    }

    pub(crate) fn key(self) -> &'static [u8] {
        match self {
            Self::Count => b"count",
            Self::JavaAggregate => b"aggregate/count",
        }
    }

    pub(super) fn from_digest(digest: [u8; 32]) -> Result<Self, StoreError> {
        [Self::Count, Self::JavaAggregate]
            .into_iter()
            .find(|recipe| recipe.digest() == digest)
            .ok_or(StoreError::UnsupportedFormat)
    }
}
