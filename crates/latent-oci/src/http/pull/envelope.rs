use super::super::{invalid, Result};
use crate::{OciDescriptor, OciManifestBytes, OciPushRequest, OciReference};
use latent_artifacts::package::{
    decode_manifest, decode_referrer, ArtifactDescriptor, PackageLimits, PackageManifest,
    ReferrerManifest, OCI_MANIFEST_MEDIA_TYPE,
};

pub(crate) enum Envelope {
    Package(PackageManifest),
    Evidence(ReferrerManifest),
}

impl Envelope {
    pub(super) fn decode(bytes: &[u8], limits: PackageLimits) -> Result<Self> {
        if let Ok(manifest) = decode_manifest(bytes, limits) {
            return Ok(Self::Package(manifest));
        }
        decode_referrer(bytes, limits).map(Self::Evidence)
    }

    pub(super) fn config(&self) -> &ArtifactDescriptor {
        match self {
            Self::Package(value) => &value.config,
            Self::Evidence(value) => &value.config,
        }
    }

    pub(super) fn layers(&self) -> &[ArtifactDescriptor] {
        match self {
            Self::Package(value) => &value.layers,
            Self::Evidence(value) => &value.layers,
        }
    }

    pub(super) fn descriptor(&self, bytes: &OciManifestBytes) -> OciDescriptor {
        let (artifact_type, annotations) = match self {
            Self::Package(value) => (&value.artifact_type, &value.annotations),
            Self::Evidence(value) => (&value.artifact_type, &value.annotations),
        };
        OciDescriptor {
            media_type: OCI_MANIFEST_MEDIA_TYPE.to_owned(),
            artifact_type: Some(artifact_type.clone()),
            digest: bytes.digest().as_str().to_owned(),
            size_bytes: bytes.as_bytes().len() as u64,
            annotations: annotations.clone(),
        }
    }

    pub(super) fn blob_bytes(&self) -> Result<usize> {
        self.layers()
            .iter()
            .chain(std::iter::once(self.config()))
            .try_fold(0_usize, |sum, value| {
                let size =
                    usize::try_from(value.size).map_err(|_| invalid("oci-size-not-addressable"))?;
                sum.checked_add(size)
                    .ok_or_else(|| invalid("oci-size-overflow"))
            })
    }

    pub(super) fn finish(
        self,
        reference: OciReference,
        manifest: OciManifestBytes,
        config: Vec<u8>,
        layers: Vec<(ArtifactDescriptor, Vec<u8>)>,
        limits: PackageLimits,
    ) -> Result<OciPushRequest> {
        match self {
            Self::Package(_) => OciPushRequest::new(reference, manifest, config, layers, limits),
            Self::Evidence(_) => {
                OciPushRequest::new_referrer(reference, manifest, config, layers, limits)
            }
        }
    }
}

pub(super) fn blob_descriptor(value: &ArtifactDescriptor) -> OciDescriptor {
    OciDescriptor {
        media_type: value.media_type.clone(),
        artifact_type: None,
        digest: value.digest.as_str().to_owned(),
        size_bytes: value.size,
        annotations: value.annotations.clone().unwrap_or_default(),
    }
}
