//! One installed codec owner for the maintained, compiler-captured Java inputs.
//! Native codec conformance is separate from actual Java execution evidence.
use latent_core::PlatformError;
use latent_state::namespace::compatibility::{ReviewedSchema, SchemaDeclaration, SchemaId};
use serde::Deserialize;
use sha2::{Digest, Sha256};

pub(super) const IDENTITY: &str = "lsf.java718.aggregate-r3.v1";
pub(super) const RECIPE_IDENTITY: &str = "lsf.java-aggregate-migration.v1";
pub(super) const RECIPE: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../contracts/state/java-aggregate-v1-to-v2-migration.json"
));
pub(super) const V1: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../contracts/state/application-aggregate-v1.schema.json"
));
pub(super) const V2: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../contracts/state/application-aggregate-v2.schema.json"
));
const CODEC_DIGEST: &str = "c551c777b8cc96c1a32558e262f0137aece8692061e5ea062bca2385bf3d6237";
const V1_MEDIA: &str = "application/vnd.lsf.aggregate-v1";
const V2_MEDIA: &str = "application/vnd.lsf.aggregate-v2";
const CURRENT_MARKER: &str = "4635e27f9fa3d49e96adbd50fd5fa85197d34af328e0054ccc948102f2a7a9cf";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Profile {
    Legacy,
    Compatible,
    Writer,
    CurrentLegacy,
    CurrentCompatible,
    CurrentWriter,
    CurrentDiagnostic,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Declaration {
    schema_version: String,
    variant: String,
    effect: String,
    readers: Vec<String>,
    writers: Vec<String>,
    source_digest: String,
    publication_review_granted: bool,
    component_compiled: bool,
    state_execution_qualified: bool,
}

impl Profile {
    pub const fn name(self) -> &'static str {
        match self {
            Self::Legacy => "legacy-v1",
            Self::Compatible => "compatible-v2",
            Self::Writer => "writer-v2",
            Self::CurrentLegacy => "legacy-v1-current-http",
            Self::CurrentCompatible => "compatible-v2-current-http",
            Self::CurrentWriter => "writer-v2-current-http",
            Self::CurrentDiagnostic => "diagnostic-v1-current-http",
        }
    }
    pub fn installed(component: &str) -> Result<Self, PlatformError> {
        match component {
            "sha256:112e60fbf29c131d221f21de677d0e3b268cacf5bc17db184b94655c0513734d" => {
                Ok(Self::Legacy)
            }
            "sha256:1221ffac1d4f8db71327d56fba1624df19bff849a26f687a57888ccc4a0279ae" => {
                Ok(Self::Compatible)
            }
            "sha256:ec6ac5b4a95957406f664f7df9feb4a92829fb26e8634cde97f8b44ae21082ce" => {
                Ok(Self::Writer)
            }
            "sha256:eae8efb880744d60ba7163590fb0fd825d45cb2018760b7c1cd00272e4cefecd" => {
                Ok(Self::CurrentLegacy)
            }
            "sha256:ecd7d566a6403468a1166ad0c9042a51cce47e12f92e63907bce680daa08f813" => {
                Ok(Self::CurrentCompatible)
            }
            "sha256:05e8bbaa90168aa250d779431a317fcde8f785d93e511054e0d5facaaad5787d" => {
                Ok(Self::CurrentWriter)
            }
            "sha256:322dfed5d9838edfbbd53bf0672c31f849ac7c7309358975bf1bf6c10b0a24bb" => {
                Ok(Self::CurrentDiagnostic)
            }
            _ => Err(super::denied()),
        }
    }
    pub fn require_companion(self, schema: &str) -> Result<(), PlatformError> {
        let (_, writers) = self.schemas()?;
        if writers.iter().any(|writer| writer.as_str() == schema) {
            Ok(())
        } else {
            Err(super::denied())
        }
    }
    pub fn review(
        self,
        package: [u8; 32],
        declaration: &[u8],
        source: &[u8],
        codec: Option<&[u8]>,
        marker: Option<&[u8]>,
    ) -> Result<ReviewedSchema, PlatformError> {
        if declaration.len() > 4096 {
            return Err(super::denied());
        }
        let input: Declaration =
            serde_json::from_slice(declaration).map_err(|_| super::denied())?;
        let (variant, source_digest) = self.source();
        let (readers, writers) = self.schemas()?;
        let same = |actual: &[String], selected: &[SchemaId]| {
            actual.len() == selected.len()
                && actual
                    .iter()
                    .zip(selected)
                    .all(|(one, two)| one == two.as_str())
        };
        if input.schema_version != "latent.java.application-schema-inputs.v1"
            || input.variant != variant
            || input.effect
                != if self.current_http() {
                    "current-http"
                } else {
                    "put-once"
                }
            || input.publication_review_granted
            || input.component_compiled
            || input.state_execution_qualified
            || input.source_digest != format!("sha256:{source_digest}")
            || digest(source) != source_digest
            || !same(&input.readers, &readers)
            || !same(&input.writers, &writers)
            || match self.base() {
                Self::Legacy => codec.is_some(),
                Self::Compatible | Self::Writer => {
                    codec.is_none_or(|bytes| digest(bytes) != CODEC_DIGEST)
                }
                _ => true,
            }
            || if self.current_http() {
                marker.is_none_or(|bytes| digest(bytes) != CURRENT_MARKER)
            } else {
                marker.is_some()
            }
        {
            return Err(super::denied());
        }
        // Execute the installed reader/writer and fixed-recipe conformance on
        // every construction. The signed association alone is insufficient.
        let proof = self.conformance()?;
        ReviewedSchema::accept_with(
            SchemaDeclaration {
                package_digest: package,
                readers,
                writers,
            },
            package,
            proof,
            |_, _, _| Ok(()),
        )
        .map_err(|_| super::denied())
    }
    pub fn conformance(self) -> Result<[u8; 32], PlatformError> {
        let recipe: serde_json::Value =
            serde_json::from_slice(RECIPE).map_err(|_| super::denied())?;
        let (old, new) = (
            SchemaId::from_definition(V1).map_err(|_| super::denied())?,
            SchemaId::from_definition(V2).map_err(|_| super::denied())?,
        );
        if recipe["sourceSchema"] != old.as_str()
            || recipe["targetSchema"] != new.as_str()
            || recipe["source"]["key"] != "aggregate/count"
            || recipe["target"]["key"] != "aggregate/count"
            || recipe["source"]["bytes"] != 8
            || recipe["target"]["bytes"] != 12
            || recipe["source"]["mediaType"] != V1_MEDIA
            || recipe["target"]["mediaType"] != V2_MEDIA
            || recipe["target"]["prefixHex"] != "41470200"
            || recipe["externalEffects"] != false
            || recipe["automaticResume"] != false
            || recipe["automaticDowngrade"] != false
        {
            return Err(super::denied());
        }
        let mut proof = Sha256::new();
        if self.current_http() {
            proof.update(b"lsf.java718.aggregate-current-http.v1");
            proof.update(self.source().1);
            proof.update(CURRENT_MARKER);
        } else {
            proof.update(IDENTITY);
        }
        proof.update(self.source().0);
        proof.update(RECIPE);
        for value in [0, 1, u64::MAX] {
            let old = value.to_le_bytes().to_vec();
            let mut new = vec![0x41, 0x47, 2, 0];
            new.extend_from_slice(&old);
            if self.decode(V1_MEDIA, &old) != Some(value)
                || self.decode(V2_MEDIA, &new)
                    != if self.base() == Self::Legacy {
                        None
                    } else {
                        Some(value)
                    }
                || self.encode(value)
                    != if self.base() == Self::Writer {
                        new.clone()
                    } else {
                        old.clone()
                    }
            {
                return Err(super::denied());
            }
            for (media, bytes) in [
                (V1_MEDIA, &old[..7]),
                (V1_MEDIA, &new[..9]),
                (V2_MEDIA, &new[..11]),
                ("application/octet-stream", old.as_slice()),
            ] {
                if self.decode(media, bytes).is_some() {
                    return Err(super::denied());
                }
            }
            let mut bad = new.clone();
            bad[3] = 1;
            if self.decode(V2_MEDIA, &bad).is_some() {
                return Err(super::denied());
            }
            proof.update(old);
            proof.update(new);
            proof.update(self.encode(value));
        }
        Ok(proof.finalize().into())
    }
    fn schemas(self) -> Result<(Vec<SchemaId>, Vec<SchemaId>), PlatformError> {
        let old = SchemaId::from_definition(V1).map_err(|_| super::denied())?;
        let new = SchemaId::from_definition(V2).map_err(|_| super::denied())?;
        let readers = match self.base() {
            Self::Legacy => vec![old.clone()],
            _ => vec![new.clone(), old.clone()],
        };
        let writers = vec![if self.base() == Self::Writer {
            new
        } else {
            old
        }];
        Ok((readers, writers))
    }
    fn source(self) -> (&'static str, &'static str) {
        match self {
            Self::Legacy => (
                "legacy-v1",
                "c749a9002a050bb69c8cadd62f5d4a56587a97ca78d9a3f8066859e49b16a5dc",
            ),
            Self::Compatible => (
                "compatible-v2",
                "4fa64282235554bda233ec9852c58e84224c0e377ea39c029c6fb8ba39e5000a",
            ),
            Self::Writer => (
                "writer-v2",
                "590a44e63a9a490ac65d0f1996e71339eb3ec1e119c9222e946d1a70f0b6e1ca",
            ),
            Self::CurrentLegacy => (
                "legacy-v1",
                "31ae58fe2dac40229b9719930cf6dacaad3ea97790db6039b9d76044368ccf12",
            ),
            Self::CurrentCompatible => (
                "compatible-v2",
                "71a1ad4e95e4601a148a3642b6593c112771f443623699ed26da4e76665766ba",
            ),
            Self::CurrentWriter => (
                "writer-v2",
                "2ea02a9201cad1a5214724315e36fbb128aee101878568826918363bf3f0f743",
            ),
            Self::CurrentDiagnostic => (
                "legacy-v1",
                "ac4a89a75bc9868350f21924eefcf2c20ceefd6dc200b0b9c3c4e6064c51b1d8",
            ),
        }
    }
    pub fn decode(self, media: &str, bytes: &[u8]) -> Option<u64> {
        let value = if media == V1_MEDIA && bytes.len() == 8 {
            bytes
        } else if self.base() != Self::Legacy
            && media == V2_MEDIA
            && bytes.len() == 12
            && bytes[..4] == [0x41, 0x47, 2, 0]
        {
            &bytes[4..]
        } else {
            return None;
        };
        Some(u64::from_le_bytes(value.try_into().ok()?))
    }
    fn encode(self, value: u64) -> Vec<u8> {
        let mut bytes = if self.base() == Self::Writer {
            vec![0x41, 0x47, 2, 0]
        } else {
            Vec::new()
        };
        bytes.extend_from_slice(&value.to_le_bytes());
        bytes
    }
    pub(super) fn current_http(self) -> bool {
        !matches!(self, Self::Legacy | Self::Compatible | Self::Writer)
    }
    pub(super) fn base(self) -> Self {
        match self {
            Self::CurrentLegacy | Self::CurrentDiagnostic => Self::Legacy,
            Self::CurrentCompatible => Self::Compatible,
            Self::CurrentWriter => Self::Writer,
            original => original,
        }
    }
}

fn digest(bytes: &[u8]) -> String {
    format!(
        "{:x}",
        latent_core::digest::HexDigest(Sha256::digest(bytes))
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn installed_java_codecs_preserve_unsigned_maximum_and_refuse_wrong_media_tag_and_shape() {
        for profile in [
            Profile::Legacy,
            Profile::Compatible,
            Profile::Writer,
            Profile::CurrentLegacy,
            Profile::CurrentCompatible,
            Profile::CurrentWriter,
            Profile::CurrentDiagnostic,
        ] {
            assert_ne!(profile.conformance().unwrap(), [0; 32]);
            let (readers, writers) = profile.schemas().unwrap();
            for schema in &writers {
                assert!(profile.require_companion(schema.as_str()).is_ok());
            }
            for schema in readers.iter().filter(|schema| !writers.contains(schema)) {
                assert!(profile.require_companion(schema.as_str()).is_err());
            }
            assert!(profile
                .require_companion(
                    "sha256:e7e054b08ffb740e2b5859747a6efc7086aad826bd11e638f5b3c5dce09253ee"
                )
                .is_err());
            for value in [0, 1, u64::MAX] {
                let bytes = profile.encode(value);
                let media = if profile.base() == Profile::Writer {
                    V2_MEDIA
                } else {
                    V1_MEDIA
                };
                assert_eq!(profile.decode(media, &bytes), Some(value));
                assert_eq!(profile.decode("application/json", &bytes), None);
                assert_eq!(profile.decode(media, &bytes[..bytes.len() - 1]), None);
            }
        }
        let tagged = Profile::Writer.encode(u64::MAX);
        assert_eq!(Profile::Legacy.decode(V2_MEDIA, &tagged), None);
        assert_eq!(
            Profile::Compatible.decode(V2_MEDIA, &tagged),
            Some(u64::MAX)
        );
        let mut wrong_tag = tagged;
        wrong_tag[3] = 1;
        assert_eq!(Profile::Writer.decode(V2_MEDIA, &wrong_tag), None);
    }

    #[test]
    fn reviewed_profile_refuses_unknown_component_and_declaration_only_or_changed_source() {
        assert!(Profile::installed(
            "sha256:0000000000000000000000000000000000000000000000000000000000000000"
        )
        .is_err());
        let profile = Profile::installed(
            "sha256:ec6ac5b4a95957406f664f7df9feb4a92829fb26e8634cde97f8b44ae21082ce",
        )
        .unwrap();
        for declaration in [
            b"{}".as_slice(),
            b"{\"publicationReviewGranted\":true}".as_slice(),
        ] {
            assert!(profile
                .review(
                    [1; 32],
                    declaration,
                    b"changed source",
                    Some(b"changed codec"),
                    None
                )
                .is_err());
        }
        assert!(profile
            .review([1; 32], &vec![b' '; 4097], b"", None, None)
            .is_err());
    }
}
