use super::{capacity, corrupt, Result};
use latent_core::{
    ArtifactBlobDigest, DeploymentId, PackageDigest, ReleaseDigest, RouteGeneration, ServiceId,
    TenantId,
};
use latent_manifest::{
    __serde::{self as serde, Deserialize, Serialize},
    __serde_json as json,
};
use sha2::{Digest, Sha256};
use std::io::Write;
pub(crate) trait Text: Sized {
    fn value(&self) -> &str;
    fn parse(value: String) -> Result<Self>;
}
macro_rules! identifier {
    ($t:ident) => {
        impl Text for $t {
            fn value(&self) -> &str {
                &self.0
            }
            fn parse(s: String) -> Result<Self> {
                super::validation::token(&s, 256)?;
                Ok(Self(s))
            }
        }
    };
}
identifier!(DeploymentId);
identifier!(TenantId);
identifier!(ServiceId);
impl Text for ReleaseDigest {
    fn value(&self) -> &str {
        &self.0
    }
    fn parse(s: String) -> Result<Self> {
        s.parse::<ArtifactBlobDigest>().map_err(|_| corrupt())?;
        Ok(Self(s))
    }
}
macro_rules! digest {
    ($t:ident) => {
        impl Text for $t {
            fn value(&self) -> &str {
                self.as_str()
            }
            fn parse(s: String) -> Result<Self> {
                s.parse().map_err(|_| corrupt())
            }
        }
    };
}
digest!(ArtifactBlobDigest);
digest!(PackageDigest);
pub(crate) mod text {
    use super::{serde, Deserialize, Text};
    pub fn serialize<S: serde::Serializer, T: Text>(
        v: &T,
        s: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        s.serialize_str(v.value())
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>, T: Text>(
        d: D,
    ) -> std::result::Result<T, D::Error> {
        T::parse(String::deserialize(d)?)
            .map_err(|_| serde::de::Error::custom("invalid rollout identity"))
    }
}
pub(crate) mod optional {
    use super::{serde, text, Serialize, Text};
    #[expect(clippy::ref_option, reason = "Serde field serializer signature")]
    pub fn serialize<S: serde::Serializer, T: Text>(
        v: &Option<T>,
        s: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        v.as_ref().map(Text::value).serialize(s)
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>, T: Text>(
        d: D,
    ) -> std::result::Result<Option<T>, D::Error> {
        text::deserialize(d).map(Some)
    }
}
pub(crate) mod generation {
    use super::{serde, Deserialize, RouteGeneration, Serialize};
    #[expect(
        clippy::trivially_copy_pass_by_ref,
        reason = "serde with adapter requires a shared reference"
    )]
    pub fn serialize<S: serde::Serializer>(
        v: &RouteGeneration,
        s: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        v.0.serialize(s)
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        d: D,
    ) -> std::result::Result<RouteGeneration, D::Error> {
        u64::deserialize(d).map(RouteGeneration)
    }
}
struct Limited {
    bytes: Vec<u8>,
    maximum: usize,
}
impl Write for Limited {
    fn write(&mut self, b: &[u8]) -> std::io::Result<usize> {
        let size = self
            .bytes
            .len()
            .checked_add(b.len())
            .filter(|n| *n <= self.maximum)
            .ok_or_else(|| std::io::Error::other("rollout byte limit"))?;
        self.bytes
            .try_reserve_exact(size - self.bytes.len())
            .map_err(std::io::Error::other)?;
        self.bytes.extend_from_slice(b);
        Ok(b.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
pub(crate) fn encode<T: Serialize>(v: &T, maximum: usize) -> Result<Vec<u8>> {
    let mut writer = Limited {
        bytes: Vec::new(),
        maximum,
    };
    json::to_writer(&mut writer, v).map_err(|_| capacity())?;
    Ok(writer.bytes)
}
pub(crate) fn hash(bytes: &[u8]) -> ArtifactBlobDigest {
    format!("sha256:{:x}", Sha256::digest(bytes))
        .parse()
        .expect("canonical hash")
}
