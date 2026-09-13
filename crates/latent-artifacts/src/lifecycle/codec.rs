use latent_core::{ArtifactBlobDigest, PackageDigest, ReleaseDigest};
use serde::{Deserialize, Deserializer, Serializer};

macro_rules! strict {
    ($module:ident,$kind:ty) => {
        pub(super) mod $module {
            use super::*;
            pub fn serialize<S: Serializer>(
                value: &$kind,
                serializer: S,
            ) -> Result<S::Ok, S::Error> {
                serializer.serialize_str(value.as_str())
            }
            pub fn deserialize<'de, D: Deserializer<'de>>(
                deserializer: D,
            ) -> Result<$kind, D::Error> {
                String::deserialize(deserializer)?
                    .parse()
                    .map_err(|_| serde::de::Error::custom("invalid digest"))
            }
        }
    };
}
strict!(blob, ArtifactBlobDigest);
macro_rules! optional {
    ($module:ident,$kind:ty) => {
        pub(super) mod $module {
            use super::*;
            pub fn serialize<S: Serializer>(
                value: &Option<$kind>,
                serializer: S,
            ) -> Result<S::Ok, S::Error> {
                match value {
                    Some(value) => serializer.serialize_some(value.as_str()),
                    None => serializer.serialize_none(),
                }
            }
            pub fn deserialize<'de, D: Deserializer<'de>>(
                deserializer: D,
            ) -> Result<Option<$kind>, D::Error> {
                Option::<String>::deserialize(deserializer)?
                    .map(|value| {
                        value
                            .parse()
                            .map_err(|_| serde::de::Error::custom("invalid digest"))
                    })
                    .transpose()
            }
        }
    };
}
optional!(optional_blob, ArtifactBlobDigest);
optional!(optional_package, PackageDigest);
pub(super) mod release {
    use super::*;
    pub fn serialize<S: Serializer>(
        value: &ReleaseDigest,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&value.0)
    }
    pub fn deserialize<'de, D: Deserializer<'de>>(
        deserializer: D,
    ) -> Result<ReleaseDigest, D::Error> {
        let value = String::deserialize(deserializer)?;
        value
            .parse::<ArtifactBlobDigest>()
            .map_err(|_| serde::de::Error::custom("invalid release digest"))?;
        Ok(ReleaseDigest(value))
    }
}
pub(super) mod optional_release {
    use super::*;
    pub fn serialize<S: Serializer>(
        value: &Option<ReleaseDigest>,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        match value {
            Some(value) => serializer.serialize_some(&value.0),
            None => serializer.serialize_none(),
        }
    }
    pub fn deserialize<'de, D: Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Option<ReleaseDigest>, D::Error> {
        Option::<String>::deserialize(deserializer)?
            .map(|value| {
                value
                    .parse::<ArtifactBlobDigest>()
                    .map_err(|_| serde::de::Error::custom("invalid release digest"))?;
                Ok(ReleaseDigest(value))
            })
            .transpose()
    }
}
