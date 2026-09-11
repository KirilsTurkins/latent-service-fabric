//! Optional complete-metadata eligibility; never an additional admission rule.
use std::collections::{BTreeMap, BTreeSet};
use std::mem::size_of;

use latent_artifacts::{
    preparation_metadata_fingerprint, PreparationMetadataFingerprint, VerifiedArtifactMetadata,
};
use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest};
use latent_manifest::{__serde::Deserialize, __serde_json as json};

use super::{
    error, CompiledCatalog, DirectoryDeploymentRepositoryConfig, RecordIndex, RevisionRecord,
};

const MAXIMUM_STAMP_BYTES: usize = 512 * 1024;
const MAXIMUM_STAMP_DEPTH: usize = 64;

pub(super) struct ReleaseStamp {
    representative: RecordIndex,
    fingerprint: PreparationMetadataFingerprint,
}
pub(super) struct ReuseState {
    pub config: DirectoryDeploymentRepositoryConfig,
    releases: Box<[ReleaseStamp]>,
}

pub(super) struct MemoBuilder {
    stamps: Vec<ReleaseStamp>,
    maximum: usize,
}
impl MemoBuilder {
    pub fn new(count: usize, config: DirectoryDeploymentRepositoryConfig) -> Self {
        let maximum = count.min(config.max_state_bytes / size_of::<ReleaseStamp>());
        let mut stamps = Vec::new();
        let maximum = if stamps.try_reserve_exact(maximum).is_ok() {
            maximum
        } else {
            0
        };
        Self { stamps, maximum }
    }
    pub fn push(
        &mut self,
        representative: RecordIndex,
        fingerprint: Option<PreparationMetadataFingerprint>,
    ) {
        if let Some(fingerprint) = fingerprint {
            if self.stamps.len() < self.maximum {
                self.stamps.push(ReleaseStamp {
                    representative,
                    fingerprint,
                });
            }
        }
    }
    pub fn finish(
        mut self,
        config: DirectoryDeploymentRepositoryConfig,
        remaining: &mut usize,
    ) -> Option<Box<ReuseState>> {
        let available = remaining.checked_sub(size_of::<ReuseState>())?;
        let retain = self.stamps.len().min(available / size_of::<ReleaseStamp>());
        if retain == 0 {
            return None;
        }
        self.stamps.truncate(retain);
        *remaining -= size_of::<ReuseState>() + retain * size_of::<ReleaseStamp>();
        Some(Box::new(ReuseState {
            config,
            releases: self.stamps.into_boxed_slice(),
        }))
    }
}

pub(super) fn metadata_stamp(
    value: &VerifiedArtifactMetadata,
) -> Option<PreparationMetadataFingerprint> {
    preparation_metadata_fingerprint(
        value.descriptor(),
        value.manifest(),
        value.contracts(),
        MAXIMUM_STAMP_BYTES,
        MAXIMUM_STAMP_DEPTH,
    )
    .ok()
}

pub(super) fn compatible(
    previous: Option<&CompiledCatalog>,
    config: DirectoryDeploymentRepositoryConfig,
) -> Option<&CompiledCatalog> {
    previous.filter(|previous| {
        previous
            .reuse
            .as_ref()
            .is_some_and(|memo| memo.config == config)
    })
}

pub(super) fn prior_release<'a>(
    previous: Option<&'a CompiledCatalog>,
    release: &ReleaseDigest,
    stamp: Option<PreparationMetadataFingerprint>,
) -> Option<&'a RevisionRecord> {
    let previous = previous?;
    let stamp = stamp?;
    let memo = previous.reuse.as_ref()?;
    let position = memo
        .releases
        .binary_search_by(|candidate| {
            previous
                .record(candidate.representative)
                .deployment
                .release
                .cmp(release)
        })
        .ok()?;
    let candidate = &memo.releases[position];
    (candidate.fingerprint == stamp).then(|| previous.record(candidate.representative))
}

#[derive(Deserialize)]
#[serde(crate = "latent_manifest::__serde", deny_unknown_fields)]
pub(super) struct ExportShape {
    pub schema: String,
    pub functions: BTreeSet<String>,
}
pub(super) struct Surface<'a> {
    pub fragment: &'a str,
    pub exports: BTreeMap<String, ExportShape>,
}
impl<'a> Surface<'a> {
    pub fn new(record: &'a RevisionRecord) -> Result<Self, PlatformError> {
        let fragment = record.attributes.get("lsf.exports").ok_or_else(invariant)?;
        // Only compiler-produced fragments enter here. Their owned strings and
        // entries are bounded by the fragment and the original per-record charges.
        let exports: BTreeMap<String, ExportShape> =
            json::from_str(fragment).map_err(|_| invariant())?;
        if exports
            .values()
            .any(|shape| shape.functions.is_empty() || !shape.schema.starts_with("sha256:"))
        {
            return Err(invariant());
        }
        Ok(Self { fragment, exports })
    }
    pub fn callable(&self) -> BTreeSet<(String, String)> {
        self.exports
            .iter()
            .flat_map(|(contract, shape)| {
                shape
                    .functions
                    .iter()
                    .map(move |function| (contract.clone(), function.clone()))
            })
            .collect()
    }
}

pub(super) fn invariant() -> PlatformError {
    error(PlatformErrorCode::Internal, "invalid-compiled-reuse-state")
}
