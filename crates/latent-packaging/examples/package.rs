//! Small reusable-API driver; the integrated operator CLI is delivered by #156.
use std::io::Read;
use std::path::Path;

use latent_packaging::{
    build_package, build_package_with_sbom, decode_package_source, decode_sbom_inventory,
    read_package_directory, read_package_input, write_package_directory, PackageBundle,
    PackagingLimits,
};

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let limits = PackagingLimits::default();
    match args.as_slice() {
        [command, recipe, root, output] if command == "build" => {
            build(recipe, root, output, None, limits)?;
        }
        [command, recipe, inventory, root, output] if command == "build-with-sbom" => {
            build(recipe, root, output, Some(inventory), limits)?;
        }
        [command, directory] if command == "inspect" => {
            let bundle = read_package_directory(Path::new(directory), limits).map_err(|error| error.message)?;
            print(&bundle);
        }
        _ => return Err("usage: package build <recipe.json> <input-root> <new-output-dir> | build-with-sbom <recipe.json> <sbom-inputs.json> <input-root> <new-output-dir> | inspect <package-dir>".into()),
    }
    Ok(())
}

fn build(
    recipe: &str,
    root: &str,
    output: &str,
    inventory: Option<&str>,
    limits: PackagingLimits,
) -> Result<(), Box<dyn std::error::Error>> {
    let bytes = read(recipe, limits.package.max_document_bytes)?;
    let source = decode_package_source(&bytes, limits).map_err(|error| error.message)?;
    let input =
        read_package_input(Path::new(root), &source, limits).map_err(|error| error.message)?;
    let bundle = if let Some(path) = inventory {
        let bytes = read(path, limits.sbom.max_document_bytes)?;
        let inventory =
            decode_sbom_inventory(&bytes, limits.sbom).map_err(|error| error.message)?;
        build_package_with_sbom(input, inventory, limits)
    } else {
        build_package(input, limits)
    }
    .map_err(|error| error.message)?;
    write_package_directory(&bundle, Path::new(output)).map_err(|error| error.message)?;
    print(&bundle);
    Ok(())
}

fn read(path: &str, maximum: usize) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let mut bytes = Vec::new();
    std::fs::File::open(path)?
        .take(maximum as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        return Err("input document exceeds configured byte limit".into());
    }
    Ok(bytes)
}

fn print(bundle: &PackageBundle) {
    println!(
        "{}",
        serde_json::json!({
            "packageDigest": bundle.layout().digest().as_str(),
            "kind": bundle.layout().config().kind,
            "name": bundle.layout().config().name,
            "version": bundle.layout().config().version,
            "layers": bundle.layers().len(),
            "componentDigest": bundle.layout().component_release().map(|digest| digest.0),
            "sbomDigest": bundle.sbom().map(|sbom| sbom.inventory_digest().as_str()),
            "sbomEntries": bundle.sbom().map(latent_packaging::CheckedPackageSbom::entry_count),
        })
    );
}
