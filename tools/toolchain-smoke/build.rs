use std::env;
use std::ffi::OsStr;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

fn main() -> io::Result<()> {
    let manifest_dir = PathBuf::from(
        env::var_os("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR must be set by Cargo"),
    );
    let repository_root = manifest_dir
        .parent()
        .and_then(Path::parent)
        .expect("toolchain smoke crate must remain under tools/");
    let platform_wit = repository_root.join("wit/platform");
    let output = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR must be set by Cargo"));
    let staged_wit = output.join("runtime-wit");

    stage_runtime_world(&platform_wit, &staged_wit)?;
    write_bindgen_invocations(&output, &staged_wit)?;

    println!("cargo:rerun-if-changed={}", platform_wit.display());
    Ok(())
}

fn stage_runtime_world(platform_wit: &Path, destination: &Path) -> io::Result<()> {
    if destination.exists() {
        fs::remove_dir_all(destination)?;
    }
    fs::create_dir_all(destination.join("deps"))?;

    copy_wit_tree(&platform_wit.join("runtime"), destination)?;

    let mut packages = fs::read_dir(platform_wit)?.collect::<Result<Vec<_>, _>>()?;
    packages.sort_by_key(std::fs::DirEntry::file_name);
    for package in packages {
        if !package.file_type()?.is_dir() || package.file_name() == OsStr::new("runtime") {
            continue;
        }
        copy_wit_tree(&package.path(), &destination.join("deps").join(package.file_name()))?;
    }

    Ok(())
}

fn copy_wit_tree(source: &Path, destination: &Path) -> io::Result<()> {
    fs::create_dir_all(destination)?;
    let mut entries = fs::read_dir(source)?.collect::<Result<Vec<_>, _>>()?;
    entries.sort_by_key(std::fs::DirEntry::file_name);

    for entry in entries {
        let source_path = entry.path();
        let destination_path = destination.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_wit_tree(&source_path, &destination_path)?;
        } else if source_path.extension() == Some(OsStr::new("wit")) {
            println!("cargo:rerun-if-changed={}", source_path.display());
            fs::copy(source_path, destination_path)?;
        }
    }

    Ok(())
}

fn write_bindgen_invocations(output: &Path, staged_wit: &Path) -> io::Result<()> {
    let path_literal = format!("{:?}", staged_wit.to_string_lossy());
    let host = format!(
        "wasmtime::component::bindgen!({{\n    path: {path_literal},\n    world: \"capsule\",\n}});\n"
    );
    let guest = format!(
        "wit_bindgen::generate!({{\n    path: {path_literal},\n    world: \"capsule\",\n    generate_all,\n}});\n"
    );

    fs::write(output.join("host_bindings.rs"), host)?;
    fs::write(output.join("guest_bindings.rs"), guest)?;
    Ok(())
}
