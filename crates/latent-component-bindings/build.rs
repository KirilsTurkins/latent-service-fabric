use std::collections::BTreeSet;
use std::env;
use std::ffi::OsStr;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

const PLATFORM_WIT_RELATIVE: &str = "wit/platform";
const RUNTIME_WIT_RELATIVE: &str = "wit/platform/runtime";
const ECHO_WIT_RELATIVE: &str = "examples/echo-contract/wit";

fn main() -> io::Result<()> {
    let manifest_dir = PathBuf::from(
        env::var_os("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR must be set by Cargo"),
    );
    let repository_root = manifest_dir
        .parent()
        .and_then(Path::parent)
        .expect("latent-component-bindings must remain under crates/");
    let output = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR must be set by Cargo"));
    let platform_wit = repository_root.join(PLATFORM_WIT_RELATIVE);
    let runtime_wit = output.join("runtime-wit");
    let echo_wit = output.join("echo-wit");
    let phase3_wit = output.join("phase3-wit");

    stage_runtime_world(&platform_wit, &runtime_wit, "runtime")?;
    stage_runtime_world(&platform_wit, &phase3_wit, "runtime-phase3")?;
    stage_echo_world(repository_root, &echo_wit)?;
    write_host_bindings(&output, &runtime_wit, &echo_wit)?;
    write_guest_bindings(&output, &runtime_wit)?;
    write_phase3_bindings(&output, &phase3_wit)?;

    println!(
        "cargo:rerun-if-changed={}",
        repository_root.join(RUNTIME_WIT_RELATIVE).display()
    );
    println!(
        "cargo:rerun-if-changed={}",
        repository_root.join(ECHO_WIT_RELATIVE).display()
    );
    println!("cargo:rerun-if-changed={}", platform_wit.display());
    Ok(())
}

fn stage_runtime_world(platform_wit: &Path, destination: &Path, world: &str) -> io::Result<()> {
    recreate(destination)?;
    fs::create_dir_all(destination.join("deps"))?;
    copy_wit_tree(&platform_wit.join(world), destination)?;
    // These aggregate worlds deliberately contain only exact interface imports.
    // Loading unrelated package versions can rename generated Rust modules.
    let source = fs::read_to_string(platform_wit.join(world).join("world.wit"))?;
    let mut required = BTreeSet::new();
    for line in source.lines() {
        if let Some(import) = line
            .trim()
            .strip_prefix("import ")
            .and_then(|s| s.strip_suffix(';'))
        {
            let (package, interface) = import.split_once('/').expect("versioned aggregate import");
            let (_, version) = interface
                .rsplit_once('@')
                .expect("versioned aggregate import");
            required.insert(format!("{package}@{version}"));
        }
    }

    let mut packages = fs::read_dir(platform_wit)?.collect::<Result<Vec<_>, _>>()?;
    packages.sort_by_key(std::fs::DirEntry::file_name);
    for package in packages {
        if !package.file_type()?.is_dir()
            || package.file_name() == OsStr::new("runtime")
            || package.file_name() == OsStr::new("runtime-phase3")
        {
            continue;
        }
        let source = fs::read_to_string(package.path().join("package.wit"))?;
        let identity = source
            .lines()
            .find_map(|line| {
                line.trim()
                    .strip_prefix("package ")
                    .and_then(|s| s.strip_suffix(';'))
            })
            .expect("platform package identity");
        if !required.remove(identity) {
            continue;
        }
        copy_wit_tree(
            &package.path(),
            &destination.join("deps").join(package.file_name()),
        )?;
    }
    assert!(
        required.is_empty(),
        "missing runtime WIT dependencies: {required:?}"
    );
    Ok(())
}

fn stage_echo_world(repository_root: &Path, destination: &Path) -> io::Result<()> {
    recreate(destination)?;
    fs::create_dir_all(destination.join("deps"))?;
    copy_wit_tree(&repository_root.join(ECHO_WIT_RELATIVE), destination)?;
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

fn recreate(path: &Path) -> io::Result<()> {
    if path.exists() {
        fs::remove_dir_all(path)?;
    }
    fs::create_dir_all(path)
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

fn write_host_bindings(output: &Path, runtime_wit: &Path, echo_wit: &Path) -> io::Result<()> {
    let runtime_path = format!("{:?}", runtime_wit.to_string_lossy());
    let runtime = format!(
        r#"wasmtime::component::bindgen!({{
    path: {runtime_path},
    world: "latent:platform/capsule@0.1.0",
    imports: {{
        "latent:context/context@0.1.0.remaining-budget": store | trappable,
        default: async,
    }},
    exports: {{ default: async }},
}});
"#
    );
    fs::write(output.join("runtime_host.rs"), runtime)?;

    let echo_path = format!("{:?}", echo_wit.to_string_lossy());
    let echo = format!(
        r#"wasmtime::component::bindgen!({{
    path: {echo_path},
    world: "examples:echo/service@0.1.0",
    imports: {{ default: async }},
    exports: {{ default: async }},
}});
"#
    );
    fs::write(output.join("echo_host.rs"), echo)
}

fn write_guest_bindings(output: &Path, runtime_wit: &Path) -> io::Result<()> {
    let runtime_path = format!("{:?}", runtime_wit.to_string_lossy());
    let runtime = format!(
        "wit_bindgen::generate!({{\n    path: {runtime_path},\n    world: \"latent:platform/capsule@0.1.0\",\n    generate_all,\n}});\n"
    );
    fs::write(output.join("runtime_guest.rs"), runtime)
}

fn write_phase3_bindings(output: &Path, wit: &Path) -> io::Result<()> {
    let path = format!("{:?}", wit.to_string_lossy());
    let host = format!(
        r#"wasmtime::component::bindgen!({{
    path: {path},
    world: "latent:platform/capsule@0.2.0",
    imports: {{ default: async }},
    exports: {{ default: async }},
    with: {{
        "latent:context/context@0.1.0": crate::host::runtime::latent::context::context,
        "latent:log/log@0.1.0": crate::host::runtime::latent::log::log,
        "latent:clock/monotonic@0.1.0": crate::host::runtime::latent::clock::monotonic,
        "latent:clock/wall@0.1.0": crate::host::runtime::latent::clock::wall,
    }},
}});
"#
    );
    fs::write(output.join("phase3_host.rs"), host)?;
    let guest = format!(
        r#"wit_bindgen::generate!({{
    path: {path},
    world: "latent:platform/capsule@0.2.0",
    generate_all,
}});
"#
    );
    fs::write(output.join("phase3_guest.rs"), guest)
}
