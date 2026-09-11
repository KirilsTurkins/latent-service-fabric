//! Small reusable-API driver; the integrated operator CLI is delivered by #156.
use std::io::Read;
use std::path::Path;

use latent_packaging::{
    build_package, decode_package_source, read_package_directory, read_package_input,
    write_package_directory, PackageBundle, PackagingLimits,
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
            let mut bytes = Vec::new();
            std::fs::File::open(recipe)?.take(limits.package.max_document_bytes as u64 + 1).read_to_end(&mut bytes)?;
            let source = decode_package_source(&bytes, limits).map_err(|error| error.message)?;
            let input = read_package_input(Path::new(root), &source, limits).map_err(|error| error.message)?;
            let bundle = build_package(input, limits).map_err(|error| error.message)?;
            write_package_directory(&bundle, Path::new(output)).map_err(|error| error.message)?;
            print(&bundle);
        }
        [command, directory] if command == "inspect" => {
            let bundle = read_package_directory(Path::new(directory), limits).map_err(|error| error.message)?;
            print(&bundle);
        }
        _ => return Err("usage: package build <recipe.json> <input-root> <new-output-dir> | inspect <package-dir>".into()),
    }
    Ok(())
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
        })
    );
}
