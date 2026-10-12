use std::collections::{BTreeMap, BTreeSet};

use latent_artifacts::package::{decode_wit_lock, LayerRole, PackageConfig, WitLockedPackage};
use latent_core::PlatformError;

use crate::{PackagingLimits, BUILD_INPUTS_PATH};

use super::super::{SbomDigestScope, SbomEntryKind, SbomInventory, SbomInventoryEntry};
use super::SBOM_PATH;

pub(super) fn validate(
    config: &PackageConfig,
    layers: &[(String, Vec<u8>)],
    inventory: &SbomInventory,
    limits: PackagingLimits,
) -> Result<(), PlatformError> {
    let lock = config
        .layers
        .iter()
        .find(|layer| layer.role == LayerRole::WitLock)
        .map(|layer| {
            let bytes = &layers
                .iter()
                .find(|(path, _)| path == &layer.path)
                .expect("checked package blob set")
                .1;
            decode_wit_lock(bytes, limits.package)
        })
        .transpose()?;
    let expected = config
        .layers
        .iter()
        .filter(|layer| {
            matches!(
                layer.role,
                LayerRole::Component | LayerRole::Renderer | LayerRole::Asset
            ) && layer.path != SBOM_PATH
                && layer.path != BUILD_INPUTS_PATH
        })
        .map(|layer| (layer.path.as_str(), layer))
        .collect::<BTreeMap<_, _>>();
    let mut seen = BTreeSet::new();
    for entry in &inventory.entries {
        if !matches!(
            entry.kind,
            SbomEntryKind::Component
                | SbomEntryKind::Renderer
                | SbomEntryKind::Asset
                | SbomEntryKind::WitPackage
        ) {
            continue;
        }
        let path = entry
            .path
            .as_deref()
            .ok_or_else(|| crate::invalid("missing-sbom-output-path"))?;
        let layer = expected
            .get(path)
            .ok_or_else(|| crate::invalid("unknown-sbom-output"))?;
        if !seen.insert(path) {
            return Err(crate::invalid("duplicate-sbom-output"));
        }
        let wit = lock.as_ref().and_then(|lock| {
            lock.packages
                .iter()
                .find(|package| package.source_path == path)
        });
        let (kind, scope) = match (layer.role, wit) {
            (LayerRole::Component, _) => (SbomEntryKind::Component, SbomDigestScope::OutputBytes),
            (LayerRole::Renderer, _) => (SbomEntryKind::Renderer, SbomDigestScope::OutputBytes),
            (LayerRole::Asset, Some(_)) => (SbomEntryKind::WitPackage, SbomDigestScope::WitSource),
            (LayerRole::Asset, None) => (SbomEntryKind::Asset, SbomDigestScope::OutputBytes),
            _ => unreachable!("selected output layer role"),
        };
        if entry.kind != kind
            || entry.digest_scope != Some(scope)
            || entry.digest.as_ref() != Some(&layer.digest)
            || entry.size != Some(layer.size)
        {
            return Err(crate::invalid("sbom-output-identity-mismatch"));
        }
        if let Some(wit) = wit {
            wit_identity(entry, wit)?;
        }
    }
    if seen.len() != expected.len() {
        return Err(crate::invalid("missing-sbom-output"));
    }
    Ok(())
}

fn wit_identity(entry: &SbomInventoryEntry, wit: &WitLockedPackage) -> Result<(), PlatformError> {
    let (name, version) = wit
        .id
        .rsplit_once('@')
        .expect("checked WIT package identity");
    if entry.name != name || entry.version.as_deref() != Some(version) {
        return Err(crate::invalid("sbom-wit-identity-mismatch"));
    }
    Ok(())
}
