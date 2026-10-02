//! Stateless reusable-API driver; its default profile stays unchanged.
#[path = "support/package_driver.rs"]
mod package_driver;

fn main() {
    if let Err(error) = package_driver::run(latent_packaging::PackagingLimits::default()) {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
