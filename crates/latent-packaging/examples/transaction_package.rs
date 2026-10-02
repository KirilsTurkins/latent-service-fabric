//! Explicit opt-in package tool for the frozen transaction preparation profile.
//! Neither this profile nor a companion asset grants application authority.
#[path = "support/package_driver.rs"]
mod package_driver;

fn main() {
    let profile = latent_manifest::ManifestValidationProfile::phase4(
        latent_core::BudgetProfile::Phase4,
        latent_core::PHASE4_HOST_ABI_V1,
        &latent_manifest::phase4_host_abi_digest(),
    )
    .expect("the compiled transaction profile must match its frozen host ABI");
    let limits = latent_packaging::PackagingLimits {
        manifest_profile: profile,
        ..Default::default()
    };
    if let Err(error) = package_driver::run(limits) {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
