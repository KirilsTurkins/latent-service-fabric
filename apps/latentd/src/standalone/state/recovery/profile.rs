//! One installed codec owner for the maintained, compiler-captured Java inputs.
//! Native codec conformance is separate from actual Java execution evidence.
use latent_core::PlatformError;
use latent_state::{
    namespace::compatibility::{ReviewedSchema, SchemaDeclaration, SchemaId},
    recovery::migration::AggregateMigrationRecipe,
};
use serde::Deserialize;
use sha2::{Digest, Sha256};

pub(super) const IDENTITY: &str = "lsf.java718.aggregate-r3.v1";
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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Profile {
    Legacy,
    Compatible,
    Writer,
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
            _ => Err(super::super::denied()),
        }
    }
    pub fn review(
        self,
        package: [u8; 32],
        declaration: &[u8],
        source: &[u8],
        codec: Option<&[u8]>,
    ) -> Result<ReviewedSchema, PlatformError> {
        if declaration.len() > 4096 {
            return Err(super::super::denied());
        }
        let input: Declaration =
            serde_json::from_slice(declaration).map_err(|_| super::super::denied())?;
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
            || input.effect != "put-once"
            || input.publication_review_granted
            || input.component_compiled
            || input.state_execution_qualified
            || input.source_digest != format!("sha256:{source_digest}")
            || digest(source) != source_digest
            || !same(&input.readers, &readers)
            || !same(&input.writers, &writers)
            || match self {
                Self::Legacy => codec.is_some(),
                Self::Compatible | Self::Writer => {
                    codec.is_none_or(|bytes| digest(bytes) != CODEC_DIGEST)
                }
            }
        {
            return Err(super::super::denied());
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
        .map_err(|_| super::super::denied())
    }
    pub fn conformance(self) -> Result<[u8; 32], PlatformError> {
        let recipe: serde_json::Value =
            serde_json::from_slice(AggregateMigrationRecipe::JavaAggregate.bytes())
                .map_err(|_| super::super::denied())?;
        let (old, new) =
            latent_state::recovery::migration::schema_ids().map_err(|_| super::super::denied())?;
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
            return Err(super::super::denied());
        }
        let mut proof = Sha256::new();
        proof.update(IDENTITY);
        proof.update(self.source().0);
        proof.update(AggregateMigrationRecipe::JavaAggregate.bytes());
        for value in [0, 1, u64::MAX] {
            let old = value.to_le_bytes().to_vec();
            let mut new = vec![0x41, 0x47, 2, 0];
            new.extend_from_slice(&old);
            if self.decode(V1_MEDIA, &old) != Some(value)
                || self.decode(V2_MEDIA, &new)
                    != if self == Self::Legacy {
                        None
                    } else {
                        Some(value)
                    }
                || self.encode(value)
                    != if self == Self::Writer {
                        new.clone()
                    } else {
                        old.clone()
                    }
            {
                return Err(super::super::denied());
            }
            for (media, bytes) in [
                (V1_MEDIA, &old[..7]),
                (V1_MEDIA, &new[..9]),
                (V2_MEDIA, &new[..11]),
                ("application/octet-stream", old.as_slice()),
            ] {
                if self.decode(media, bytes).is_some() {
                    return Err(super::super::denied());
                }
            }
            let mut bad = new.clone();
            bad[3] = 1;
            if self.decode(V2_MEDIA, &bad).is_some() {
                return Err(super::super::denied());
            }
            proof.update(old);
            proof.update(new);
            proof.update(self.encode(value));
        }
        Ok(proof.finalize().into())
    }
    fn schemas(self) -> Result<(Vec<SchemaId>, Vec<SchemaId>), PlatformError> {
        let old = SchemaId::from_definition(V1).map_err(|_| super::super::denied())?;
        let new = SchemaId::from_definition(V2).map_err(|_| super::super::denied())?;
        let readers = match self {
            Self::Legacy => vec![old.clone()],
            _ => vec![new.clone(), old.clone()],
        };
        let writers = vec![if self == Self::Writer { new } else { old }];
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
        }
    }
    pub fn decode(self, media: &str, bytes: &[u8]) -> Option<u64> {
        let value = if media == V1_MEDIA && bytes.len() == 8 {
            bytes
        } else if self != Self::Legacy
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
        let mut bytes = if self == Self::Writer {
            vec![0x41, 0x47, 2, 0]
        } else {
            Vec::new()
        };
        bytes.extend_from_slice(&value.to_le_bytes());
        bytes
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
        for profile in [Profile::Legacy, Profile::Compatible, Profile::Writer] {
            assert_ne!(profile.conformance().unwrap(), [0; 32]);
            for value in [0, 1, u64::MAX] {
                let bytes = profile.encode(value);
                let media = if profile == Profile::Writer {
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
                    Some(b"changed codec")
                )
                .is_err());
        }
        assert!(profile
            .review([1; 32], &vec![b' '; 4097], b"", None)
            .is_err());
    }
}
