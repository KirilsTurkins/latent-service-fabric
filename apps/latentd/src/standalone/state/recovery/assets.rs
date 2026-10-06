//! Exact admitted package layers retained before any fixed-worker review.
use super::profile::{Profile, V1, V2};
use crate::standalone::state::InstalledTransactionOperation;
use latent_artifacts::{
    package::{
        artifact_blob_digest, decode_config, package_digest, LayerRole, PackageConfig,
        PackageLimits,
    },
    ArtifactRepository, DirectoryArtifactRepository,
};
use latent_core::PlatformError;
use latent_state::{
    namespace::compatibility::{ReviewedSchema, SchemaId},
    recovery::{migration::AggregateMigrationRecipe, snapshot::RequiredArtifact},
};
use sha2::{Digest, Sha256};
use std::sync::Arc;

pub(super) struct SchemaEvidence {
    pub operation: Arc<InstalledTransactionOperation>,
    pub schema: ReviewedSchema,
    pub profile: Profile,
    pub artifacts: Vec<RequiredArtifact>,
}

pub(super) async fn capture(
    repository: &Arc<DirectoryArtifactRepository>,
    operation: Arc<InstalledTransactionOperation>,
) -> Result<SchemaEvidence, PlatformError> {
    let publication = operation.publication();
    publication.check_current()?;
    let profile = Profile::installed(&publication.release().0)?;
    let source = repository
        .retained_package_source_selected(
            &operation.target().tenant,
            publication.release(),
            Some(publication.publication()),
            32 * 1024 * 1024,
        )
        .await?
        .ok_or_else(super::super::denied)?;
    if source.publication() != publication.publication()
        || source.tenant() != &operation.target().tenant
        || source.component() != publication.release()
        || Some(source.package()) != publication.package()
    {
        return Err(super::super::denied());
    }
    let (manifest, configuration, layers) = source.into_parts();
    let package = package_digest(&manifest);
    if Some(&package) != publication.package() {
        return Err(super::super::denied());
    }
    let config = decode_config(&configuration, PackageLimits::default())?;
    let declaration = asset(
        &config,
        &layers,
        "application-schema-inputs.json",
        "application/json",
    )?;
    let capsule = asset(
        &config,
        &layers,
        "src/dev/latent/app/Capsule.java",
        "text/plain",
    )?;
    let codec = if profile == Profile::Legacy {
        None
    } else {
        Some(asset(
            &config,
            &layers,
            "src/dev/latent/app/AggregateCodec.java",
            "text/plain",
        )?)
    };
    for (path, expected) in [
        ("schemas/application-aggregate-v1.schema.json", V1),
        ("schemas/application-aggregate-v2.schema.json", V2),
        (
            "java-aggregate-v1-to-v2-migration.json",
            AggregateMigrationRecipe::JavaAggregate.bytes(),
        ),
    ] {
        if asset(&config, &layers, path, "application/json")? != expected {
            return Err(super::super::denied());
        }
    }
    let schema = profile.review(digest_bytes(package.as_str())?, declaration, capsule, codec)?;
    let mut artifacts = required(&operation, &schema)?;
    artifacts.extend([
        artifact(
            format!("lsf.java718.{}.declaration", profile.name()),
            declaration,
        ),
        artifact(format!("lsf.java718.{}.source", profile.name()), capsule),
    ]);
    if let Some(codec) = codec {
        artifacts.push(artifact("lsf.java718.aggregate-codec.v1".into(), codec));
    }
    publication.check_current()?;
    Ok(SchemaEvidence {
        operation,
        schema,
        profile,
        artifacts,
    })
}

fn required(
    operation: &InstalledTransactionOperation,
    schema: &ReviewedSchema,
) -> Result<Vec<RequiredArtifact>, PlatformError> {
    let package = operation
        .publication()
        .package()
        .ok_or_else(super::super::denied)?;
    Ok(vec![
        RequiredArtifact {
            identity: package.to_string(),
            digest: schema.declaration().package_digest,
        },
        RequiredArtifact {
            identity: operation.publication().publication().as_str().into(),
            digest: schema.declaration().package_digest,
        },
        RequiredArtifact {
            identity: operation.publication().release().0.clone(),
            digest: digest_bytes(&operation.publication().release().0)?,
        },
        RequiredArtifact {
            identity: operation.contract_digest.clone(),
            digest: digest_bytes(&operation.contract_digest)?,
        },
        artifact(
            SchemaId::from_definition(V1)
                .map_err(|_| super::super::denied())?
                .as_str()
                .into(),
            V1,
        ),
        artifact(
            SchemaId::from_definition(V2)
                .map_err(|_| super::super::denied())?
                .as_str()
                .into(),
            V2,
        ),
        artifact(
            AggregateMigrationRecipe::JavaAggregate.identity().into(),
            AggregateMigrationRecipe::JavaAggregate.bytes(),
        ),
    ])
}

fn asset<'a>(
    config: &PackageConfig,
    layers: &'a [(String, Vec<u8>)],
    path: &str,
    media: &str,
) -> Result<&'a [u8], PlatformError> {
    let entry = config
        .layers
        .iter()
        .find(|layer| layer.path == path)
        .filter(|layer| {
            layer.role == LayerRole::Asset
                && layer.media_type == media
                && layer.size > 0
                && layer.size <= 262_144
        })
        .ok_or_else(super::super::denied)?;
    let raw = layers
        .iter()
        .find(|(name, _)| name == path)
        .map(|(_, bytes)| bytes.as_slice())
        .ok_or_else(super::super::denied)?;
    if raw.len() as u64 != entry.size || artifact_blob_digest(raw) != entry.digest {
        return Err(super::super::denied());
    }
    Ok(raw)
}
pub(super) fn digest_bytes(text: &str) -> Result<[u8; 32], PlatformError> {
    if text.len() != 71 || !text.starts_with("sha256:") {
        return Err(super::super::denied());
    }
    let mut output = [0; 32];
    for (slot, pair) in output.iter_mut().zip(text.as_bytes()[7..].chunks_exact(2)) {
        let digit = |byte| match byte {
            b'0'..=b'9' => Ok(byte - b'0'),
            b'a'..=b'f' => Ok(byte - b'a' + 10),
            _ => Err(super::super::denied()),
        };
        *slot = digit(pair[0])? * 16 + digit(pair[1])?;
    }
    if output == [0; 32] {
        return Err(super::super::denied());
    }
    Ok(output)
}
fn artifact(identity: String, bytes: &[u8]) -> RequiredArtifact {
    RequiredArtifact {
        identity,
        digest: Sha256::digest(bytes).into(),
    }
}
