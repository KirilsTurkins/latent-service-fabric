use super::{capacity, corrupt, Result};
pub(crate) use crate::rollouts::codec::hash;
use latent_core::ArtifactBlobDigest;
use latent_manifest::{
    __serde::{self as serde, Deserialize, Serialize},
    __serde_json as json,
};
pub(crate) fn encode<T: Serialize>(value: &T, maximum: usize) -> Result<Vec<u8>> {
    crate::rollouts::codec::encode(value, maximum).map_err(|_| capacity())
}
pub(crate) fn receipt_hash(
    value: &super::DeploymentOperationReceipt,
) -> Result<ArtifactBlobDigest> {
    let mut value = json::to_value(value).map_err(|_| corrupt())?;
    value
        .as_object_mut()
        .ok_or_else(corrupt)?
        .remove("receiptDigest");
    Ok(hash(&encode(&value, super::MAX_RECEIPT_BYTES)?))
}
macro_rules! identity {
    ($module:ident, $kind:ident) => {
        pub(crate) mod $module {
            use super::*;
            pub fn serialize<S: serde::Serializer>(
                value: &latent_core::$kind,
                serializer: S,
            ) -> std::result::Result<S::Ok, S::Error> {
                serializer.serialize_str(&value.0)
            }
            pub fn deserialize<'de, D: serde::Deserializer<'de>>(
                deserializer: D,
            ) -> std::result::Result<latent_core::$kind, D::Error> {
                let value = String::deserialize(deserializer)?;
                super::super::validation::token(&value, 1024).map_err(|_| {
                    serde::de::Error::custom("invalid deployment operation identity")
                })?;
                Ok(latent_core::$kind(value))
            }
        }
    };
}
identity!(tenant, TenantId);
identity!(id, DeploymentId);
pub(crate) fn present<'de, D: serde::Deserializer<'de>, T: Deserialize<'de>>(
    deserializer: D,
) -> std::result::Result<Option<T>, D::Error> {
    T::deserialize(deserializer).map(Some)
}
