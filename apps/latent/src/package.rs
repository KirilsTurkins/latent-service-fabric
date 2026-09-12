//! Local bounded package operations. Registry transfer uses its separate owner.
mod registry;

use crate::args::{Cli, PackageCommand};
use crate::{error::Failure, input, output::Outcome};
use latent_artifacts::ReleaseEvidenceUpload;
use latent_core::{PackageDigest, PlatformError, TenantId};
use latent_packaging::{PackageBundle, PackagingLimits};
use serde_json::json;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

pub(super) const MAX_EVIDENCE: usize = 16 * 1024 * 1024;

pub fn execute(cli: &Cli, command: &PackageCommand) -> Outcome {
    execute_inner(cli, command).unwrap_or_else(Into::into)
}

fn execute_inner(cli: &Cli, command: &PackageCommand) -> Result<Outcome, Failure> {
    match command {
        PackageCommand::Build(args) => {
            let source = input::read(&args.source, 256 * 1024, "package-source")?;
            let source =
                latent_packaging::decode_package_source(&source, limits()).map_err(failure)?;
            let input = latent_packaging::read_package_input(&args.input_root, &source, limits())
                .map_err(failure)?;
            let package = if let Some(path) = &args.sbom_inputs {
                let bytes = input::read(path, 1024 * 1024, "sbom-inputs")?;
                let inventory = latent_packaging::decode_sbom_inventory(&bytes, limits().sbom)
                    .map_err(failure)?;
                latent_packaging::build_package_with_sbom(input, inventory, limits())
            } else {
                latent_packaging::build_package(input, limits())
            }
            .map_err(failure)?;
            latent_packaging::write_package_directory(&package, &args.output_dir)
                .map_err(failure)?;
            Ok(Outcome::success(summary(&package)))
        }
        PackageCommand::Inspect(args) => Ok(Outcome::success(summary(&read(&args.directory)?))),
        PackageCommand::Verify(args) => {
            let package = read(&args.directory)?;
            let evidence = evidence(
                &args.evidence_index,
                &args.evidence_root,
                package.layout().digest(),
            )?;
            let bytes = input::read(&args.policy, 256 * 1024, "verification-policy")?;
            let policy = latent_policy::supply_chain::SupplyChainPolicy::from_json(&bytes)
                .map_err(failure)?;
            let now = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|_| {
                    Failure::local(
                        "clock-unavailable",
                        "The local verification clock is unavailable.",
                    )
                })?
                .as_secs();
            let tenant = TenantId(cli.tenant.clone().ok_or_else(|| {
                Failure::local("tenant-required", "Package verification requires --tenant.")
            })?);
            let report = latent_policy::supply_chain::verify_package_once(
                &policy,
                latent_policy::supply_chain::PackageVerificationRequest {
                    tenant: &tenant,
                    package: &package,
                    evidence: &evidence,
                    unix_seconds: now,
                },
            )
            .map_err(failure)?;
            let mut document = serde_json::to_value(report).map_err(|_| {
                Failure::local(
                    "report-limit",
                    "Could not encode the bounded verification report.",
                )
            })?;
            decimal_versions(&mut document);
            Ok(Outcome::success(document))
        }
        PackageCommand::Push(_) | PackageCommand::Pull(_) => registry::execute(cli, command),
    }
}

pub(super) fn limits() -> PackagingLimits {
    let mut limits = PackagingLimits::default();
    limits.package.max_layer_bytes = 16 * 1024 * 1024;
    limits.package.max_total_layer_bytes = 32 * 1024 * 1024;
    limits
}

pub(crate) fn read(directory: &Path) -> Result<PackageBundle, Failure> {
    latent_packaging::read_package_directory(directory, limits()).map_err(failure)
}

pub(crate) fn evidence(
    index: &Path,
    root: &Path,
    package: &PackageDigest,
) -> Result<ReleaseEvidenceUpload, Failure> {
    let bytes = input::read(index, 16 * 1024, "evidence-index")?;
    latent_packaging::read_package_evidence(root, &bytes, package, MAX_EVIDENCE).map_err(failure)
}

pub(super) fn summary(package: &PackageBundle) -> serde_json::Value {
    json!({"packageDigest":package.layout().digest().to_string(),
        "componentDigest":package.layout().config().component_digest.as_ref().map(ToString::to_string),
        "kind":package.layout().config().kind,"name":package.layout().config().name,
        "version":package.layout().config().version,"layers":package.layers().len(),
        "layerBytes":package.layers().iter().map(|blob|blob.bytes().len()).sum::<usize>().to_string(),
        "sbomInventoryDigest":package.sbom().map(|sbom|sbom.inventory_digest().to_string()),
        "trustEvaluated":false,"executionAuthorized":false})
}

#[expect(
    clippy::needless_pass_by_value,
    reason = "Owned Result::map_err callback."
)]
pub(super) fn failure(error: PlatformError) -> Failure {
    let mut failure = Failure::local(
        "package-operation-failed",
        "The package operation failed validation, policy or resource checks.",
    );
    failure.data = json!({"platformError": crate::error::platform_value(&error)});
    failure
}

// CLI u64 values remain lossless for consumers whose JSON number is IEEE-754.
fn decimal_versions(value: &mut serde_json::Value) {
    if let serde_json::Value::Object(fields) = value {
        for (key, value) in fields {
            if matches!(
                key.as_str(),
                "generation"
                    | "validFrom"
                    | "validUntil"
                    | "checkedAtUnixSeconds"
                    | "validUntilUnixSeconds"
            ) {
                if let Some(number) = value.as_u64() {
                    *value = json!(number.to_string());
                }
            } else {
                decimal_versions(value);
            }
        }
    }
}
