use latent_core::{ArtifactBlobDigest, PackageDigest};
use serde::{Deserialize, Deserializer, Serializer};

macro_rules! strict {
    ($name:ident, $kind:ty) => {
        pub(crate) mod $name {
            use super::*;
            pub fn serialize<S: Serializer>(
                value: &$kind,
                serializer: S,
            ) -> Result<S::Ok, S::Error> {
                serializer.serialize_str(value.as_str())
            }
            pub fn deserialize<'de, D: Deserializer<'de>>(decoder: D) -> Result<$kind, D::Error> {
                String::deserialize(decoder)?
                    .parse()
                    .map_err(serde::de::Error::custom)
            }
        }
    };
}
strict!(blob, ArtifactBlobDigest);
strict!(package, PackageDigest);

pub(crate) mod optional_blob {
    use super::{ArtifactBlobDigest, Deserialize, Deserializer, Serializer};
    #[expect(
        clippy::ref_option,
        reason = "serde(with) calls this with a borrowed Option"
    )]
    pub fn serialize<S: Serializer>(
        value: &Option<ArtifactBlobDigest>,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        match value {
            Some(value) => serializer.serialize_some(value.as_str()),
            None => serializer.serialize_none(),
        }
    }
    pub fn deserialize<'de, D: Deserializer<'de>>(
        decoder: D,
    ) -> Result<Option<ArtifactBlobDigest>, D::Error> {
        Option::<String>::deserialize(decoder)?
            .map(|value| value.parse().map_err(serde::de::Error::custom))
            .transpose()
    }
}
