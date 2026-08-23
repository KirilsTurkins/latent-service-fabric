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
        .expect("latent-wasmtime must remain under crates/");
    let output = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR must be set by Cargo"));
    let target = env::var("TARGET").expect("TARGET must be set by Cargo");
    let staged_wit = output.join("echo-runtime-wit");

    println!("cargo:rustc-env=LATENT_WASMTIME_HOST_TARGET={target}");

    stage_echo_world(repository_root, &staged_wit)?;
    write_bindings_invocation(&output, &staged_wit)?;

    println!(
        "cargo:rerun-if-changed={}",
        repository_root.join("examples/echo-contract/wit").display()
    );
    println!(
        "cargo:rerun-if-changed={}",
        repository_root.join("wit/platform/context").display()
    );
    println!(
        "cargo:rerun-if-changed={}",
        repository_root.join("wit/platform/log").display()
    );
    Ok(())
}

fn stage_echo_world(repository_root: &Path, destination: &Path) -> io::Result<()> {
    if destination.exists() {
        fs::remove_dir_all(destination)?;
    }
    fs::create_dir_all(destination.join("deps"))?;

    copy_wit_tree(
        &repository_root.join("examples/echo-contract/wit"),
        destination,
    )?;
    copy_wit_tree(
        &repository_root.join("wit/platform/context"),
        &destination.join("deps/context"),
    )?;
    copy_wit_tree(
        &repository_root.join("wit/platform/log"),
        &destination.join("deps/log"),
    )?;
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
            fs::copy(source_path, destination_path)?;
        }
    }
    Ok(())
}

fn write_bindings_invocation(output: &Path, staged_wit: &Path) -> io::Result<()> {
    let path_literal = format!("{:?}", staged_wit.to_string_lossy());
    let source = format!(
        r#"wasmtime::component::bindgen!({{
    path: {path_literal},
    world: "examples:echo/service@0.1.0",
    imports: {{ default: async }},
    exports: {{ default: async }},
}});
"#
    );
    fs::write(output.join("echo_bindings.rs"), source)
}
