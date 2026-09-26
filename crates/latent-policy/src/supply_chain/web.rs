mod grant;
mod receipt;
pub(super) use grant::Grant;
pub(super) use receipt::validate_retained;

use super::{
    denied,
    verification::{check_evidence, CheckedEvidence, EvidenceInput},
    Inner, State,
};
use latent_artifacts::{
    web::{CheckedWebLayout, VerifiedWebAdmission, WebAdmissionBinding, MAX_WEB_RENDERER_BYTES},
    AdmissionEvidence, AdmissionStorageLimits, PackageAdmissionUpload,
};
use latent_core::{PlatformError, TenantId};
use latent_packaging::{
    inspect_bundle, inspect_web_bundle, BundleInput, PackageBundle, PackagingLimits,
};
use latent_signing::VerifiedWebBuildProvenance;
use std::sync::Arc;

pub(super) struct Prepared {
    bundle: PackageBundle,
    layout: CheckedWebLayout,
    signatures: Vec<AdmissionEvidence>,
    provenance: Vec<AdmissionEvidence>,
    sboms: Vec<AdmissionEvidence>,
}

pub(super) fn check_tenant(tenant: &TenantId, state: &State) -> Result<(), PlatformError> {
    if !super::config::identifier(&tenant.0) || !state.policy.tenants.contains_key(&tenant.0) {
        return Err(denied("admission-tenant-denied"));
    }
    Ok(())
}

pub(super) fn prepare(upload: PackageAdmissionUpload) -> Result<Prepared, PlatformError> {
    let renderer_maximum = usize::try_from(MAX_WEB_RENDERER_BYTES)
        .map_err(|_| super::invalid("admission-component-limit"))?;
    AdmissionStorageLimits::default().check_upload(&upload, renderer_maximum)?;
    if upload.signatures.len() != 1 || upload.provenance.len() != 1 {
        return Err(denied("admission-required-evidence-cardinality"));
    }
    let PackageAdmissionUpload {
        manifest,
        configuration,
        layers,
        signatures,
        provenance,
        sboms,
    } = upload;
    let limits = PackagingLimits::default();
    let bundle = inspect_bundle(
        BundleInput {
            manifest,
            configuration,
            layers,
        },
        limits,
    )?;
    let layout = inspect_web_bundle(&bundle, limits.semantics)?;
    Ok(Prepared {
        bundle,
        layout,
        signatures,
        provenance,
        sboms,
    })
}

/// The single verification reservation retains the decoded inputs while the
/// short policy fence rechecks current time, policy, signatures and ownership.
pub(super) fn with_state(
    owner: &Arc<Inner>,
    tenant: &TenantId,
    prepared: Prepared,
    previous: Option<&WebAdmissionBinding>,
    state: &mut State,
) -> Result<VerifiedWebAdmission, PlatformError> {
    let now = owner.sample(state)?;
    check_tenant(tenant, state)?;
    let Prepared {
        bundle,
        layout,
        signatures,
        provenance,
        sboms,
    } = prepared;
    let checked: CheckedEvidence<VerifiedWebBuildProvenance> = check_evidence(
        &state.policy,
        state.verifiers()?,
        tenant,
        &bundle,
        EvidenceInput {
            signatures: &signatures,
            provenance: &provenance,
            sboms: &sboms,
        },
        now,
    )?;
    let receipt = receipt::Receipt::new(tenant, &layout, &checked, state, now)?;
    let binding = if let Some(previous) = previous {
        receipt::Receipt::recover(previous, &receipt)?;
        previous.clone()
    } else {
        WebAdmissionBinding {
            tenant: tenant.clone(),
            package: layout.package().clone(),
            manifest: layout.manifest_digest().clone(),
            assets: layout.assets_digest().clone(),
            receipt: receipt.encode()?,
        }
    };
    let grant = Arc::new(Grant {
        owner: Arc::clone(owner),
        binding,
        epoch: state.floor.epoch,
        publisher: checked.publisher,
        builder: checked.builder,
    });
    grant.check(owner, state)?;
    let BundleInput {
        manifest,
        configuration,
        layers,
    } = bundle.into_input();
    Ok(VerifiedWebAdmission {
        layout,
        grant,
        upload: PackageAdmissionUpload {
            manifest,
            configuration,
            layers,
            signatures,
            provenance,
            sboms,
        },
    })
}
