//! Local web diagnostics share admission evidence checks without creating authority.
use super::{check_evidence, CheckedEvidence, EvidenceInput, PackageVerificationRequest};
use crate::supply_chain::SupplyChainPolicy;
use latent_core::PlatformError;
use latent_packaging::{inspect_web_bundle, PackagingLimits};
use latent_signing::VerifiedWebBuildProvenance;
use serde::Serialize;

/// Web output identities never stand in for an executable component or grant.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WebPackageVerificationReport {
    format_version: u32,
    tenant: String,
    package_digest: String,
    web_manifest_digest: String,
    web_assets_digest: String,
    publisher: String,
    publisher_key: String,
    signature_digest: String,
    builder: String,
    builder_key: String,
    provenance_digest: String,
    sbom_inventory_digest: Option<String>,
    sbom_referrer_digest: Option<String>,
    policy: crate::supply_chain::config::PolicyIdentity,
    policy_digest: String,
    checked_at_unix_seconds: u64,
    valid_until_unix_seconds: u64,
    runtime_compatibility: &'static str,
    durable_policy_clock_floors: bool,
    execution_authorized: bool,
}

/// Check exact web layout, publisher, builder, SBOM and tenant policy at one
/// sampled time. A report does not admit a publication or establish clock history.
pub fn verify_web_package_once(
    policy: &SupplyChainPolicy,
    request: PackageVerificationRequest<'_>,
) -> Result<WebPackageVerificationReport, PlatformError> {
    let layout = inspect_web_bundle(request.package, PackagingLimits::default().semantics)?;
    let verifiers = policy.verifiers(request.unix_seconds)?;
    let checked: CheckedEvidence<VerifiedWebBuildProvenance> = check_evidence(
        policy,
        &verifiers,
        request.tenant,
        request.package,
        EvidenceInput {
            signatures: &request.evidence.signatures,
            provenance: &request.evidence.provenance,
            sboms: &request.evidence.sboms,
        },
        request.unix_seconds,
    )?;
    Ok(WebPackageVerificationReport {
        format_version: 1,
        tenant: request.tenant.0.clone(),
        package_digest: layout.package().to_string(),
        web_manifest_digest: layout.manifest_digest().to_string(),
        web_assets_digest: layout.assets_digest().to_string(),
        publisher: checked.publisher.publisher().0.clone(),
        publisher_key: checked.publisher.key_fingerprint().to_string(),
        signature_digest: checked.publisher.evidence_digest().to_string(),
        builder: checked.builder.builder_id().to_owned(),
        builder_key: checked.builder.key_fingerprint().to_string(),
        provenance_digest: checked.builder.evidence_digest().to_string(),
        sbom_inventory_digest: checked.sbom.inventory_digest().map(ToString::to_string),
        sbom_referrer_digest: checked.sbom.referrer_digest().map(ToString::to_string),
        policy: policy.identity.clone(),
        policy_digest: policy.identity.digest()?,
        checked_at_unix_seconds: request.unix_seconds,
        valid_until_unix_seconds: checked
            .publisher
            .valid_until()
            .min(checked.builder.valid_until())
            .min(policy.identity.valid_until),
        runtime_compatibility: "not-evaluated",
        durable_policy_clock_floors: false,
        execution_authorized: false,
    })
}
