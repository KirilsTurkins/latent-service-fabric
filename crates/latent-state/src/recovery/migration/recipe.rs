use crate::{embedded::StoreError, namespace::compatibility::SchemaId};
use sha2::{Digest, Sha256};

const V1: &[u8] =
    include_bytes!("../../../../../contracts/state/application-aggregate-v1.schema.json");
const V2: &[u8] =
    include_bytes!("../../../../../contracts/state/application-aggregate-v2.schema.json");

/// Closed installed transformers, not a key, script, plugin or provider supplied
/// by a management client. Original v1 recipe artifacts remain historical bytes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AggregateMigrationRecipe {
    Count,
    JavaAggregate,
}

impl AggregateMigrationRecipe {
    #[must_use]
    pub fn bytes(self) -> &'static [u8] {
        match self {
            Self::Count => include_bytes!(
                "../../../../../contracts/state/aggregate-v1-to-v2-protected-migration.json"
            ),
            Self::JavaAggregate => include_bytes!(
                "../../../../../contracts/state/java-aggregate-v1-to-v2-protected-migration.json"
            ),
        }
    }

    #[must_use]
    pub const fn identity(self) -> &'static str {
        match self {
            Self::Count => "lsf.aggregate-migration.v2",
            Self::JavaAggregate => "lsf.java-aggregate-migration.v2",
        }
    }

    #[must_use]
    pub fn digest(self) -> [u8; 32] {
        Sha256::digest(self.bytes()).into()
    }

    pub(crate) const fn key(self) -> &'static [u8] {
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

pub(super) fn schema_ids() -> Result<(SchemaId, SchemaId), StoreError> {
    Ok((
        SchemaId::from_definition(V1).map_err(|_| StoreError::Invalid)?,
        SchemaId::from_definition(V2).map_err(|_| StoreError::Invalid)?,
    ))
}

pub(super) fn schema_definitions() -> [(&'static [u8], [u8; 32]); 2] {
    [
        (V1, Sha256::digest(V1).into()),
        (V2, Sha256::digest(V2).into()),
    ]
}
