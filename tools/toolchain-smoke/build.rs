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
    let echo_wit = repository_root.join("examples/echo-contract/wit");
    let output = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR must be set by Cargo"));
    let staged_runtime_wit = output.join("runtime-wit");
    let staged_echo_wit = output.join("echo-wit");

    stage_runtime_world(&platform_wit, &staged_runtime_wit)?;
    stage_echo_world(&platform_wit, &echo_wit, &staged_echo_wit)?;
    write_bindgen_invocations(&output, &staged_runtime_wit, &staged_echo_wit)?;

    println!("cargo:rerun-if-changed={}", platform_wit.display());
    println!("cargo:rerun-if-changed={}", echo_wit.display());
    println!(
        "cargo:rerun-if-changed={}",
        repository_root
            .join("examples/echo-contract/guest-rust/src")
            .display()
    );
    Ok(())
}

fn stage_runtime_world(platform_wit: &Path, destination: &Path) -> io::Result<()> {
    reset_staging_directory(destination)?;
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

fn stage_echo_world(
    platform_wit: &Path,
    echo_wit: &Path,
    destination: &Path,
) -> io::Result<()> {
    reset_staging_directory(destination)?;
    copy_wit_tree(echo_wit, destination)?;

    for package in ["context", "log"] {
        copy_wit_tree(
            &platform_wit.join(package),
            &destination.join("deps").join(package),
        )?;
    }

    Ok(())
}

fn reset_staging_directory(destination: &Path) -> io::Result<()> {
    if destination.exists() {
        fs::remove_dir_all(destination)?;
    }
    fs::create_dir_all(destination.join("deps"))
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

fn write_bindgen_invocations(
    output: &Path,
    staged_runtime_wit: &Path,
    staged_echo_wit: &Path,
) -> io::Result<()> {
    let runtime_path = format!("{:?}", staged_runtime_wit.to_string_lossy());
    let echo_path = format!("{:?}", staged_echo_wit.to_string_lossy());

    fs::write(
        output.join("host_bindings.rs"),
        format!(
            "wasmtime::component::bindgen!({{\n    path: {runtime_path},\n    world: \"capsule\",\n}});\n"
        ),
    )?;
    fs::write(
        output.join("guest_bindings.rs"),
        format!(
            "wit_bindgen::generate!({{\n    path: {runtime_path},\n    world: \"capsule\",\n    generate_all,\n}});\n"
        ),
    )?;
    fs::write(
        output.join("echo_host_bindings.rs"),
        format!(
            "wasmtime::component::bindgen!({{\n    path: {echo_path},\n    world: \"service\",\n}});\n"
        ),
    )?;
    fs::write(
        output.join("echo_guest_bindings.rs"),
        format!(
            "wit_bindgen::generate!({{\n    path: {echo_path},\n    world: \"service\",\n    generate_all,\n}});\n"
        ),
    )?;
    Ok(())
}
