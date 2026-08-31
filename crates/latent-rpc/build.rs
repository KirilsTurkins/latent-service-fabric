use std::collections::BTreeSet;
use std::env;
use std::error::Error;
use std::ffi::OsStr;
use std::fs;
use std::path::{Path, PathBuf};

const PROTO_ROOT_RELATIVE: &str = "api/proto";
const PROTO_MANIFEST_RELATIVE: &str = "api/proto/latent-api.protos";

fn main() -> Result<(), Box<dyn Error>> {
    let manifest_dir = PathBuf::from(
        env::var_os("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR must be set by Cargo"),
    );
    let repository_root = manifest_dir
        .parent()
        .and_then(Path::parent)
        .expect("latent-rpc must remain under crates/");
    let proto_root = repository_root.join(PROTO_ROOT_RELATIVE);
    let proto_manifest = repository_root.join(PROTO_MANIFEST_RELATIVE);
    let proto_files = read_proto_manifest(&proto_root, &proto_manifest)?;
    let output = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR must be set by Cargo"));

    env::set_var("PROTOC", protoc_bin_vendored::protoc_bin_path()?);

    tonic_prost_build::configure()
        .build_client(true)
        .build_server(true)
        .build_transport(true)
        .emit_rerun_if_changed(false)
        .file_descriptor_set_path(output.join("latent_descriptor.bin"))
        .compile_protos(&proto_files, &[proto_root.clone()])?;

    println!("cargo:rerun-if-changed={}", proto_manifest.display());
    println!("cargo:rerun-if-changed={}", proto_root.display());
    for proto in proto_files {
        println!("cargo:rerun-if-changed={}", proto.display());
    }
    Ok(())
}

fn read_proto_manifest(proto_root: &Path, manifest: &Path) -> Result<Vec<PathBuf>, Box<dyn Error>> {
    let text = fs::read_to_string(manifest)?;
    let mut relative_files = Vec::new();
    let mut unique = BTreeSet::new();

    for (index, line) in text.lines().enumerate() {
        let entry = line.trim();
        if entry.is_empty() || entry.starts_with('#') {
            continue;
        }
        if !entry.ends_with(".proto") || Path::new(entry).is_absolute() || entry.contains("..") {
            return Err(format!(
                "invalid Protobuf manifest entry at {}:{}: {entry}",
                manifest.display(),
                index + 1
            )
            .into());
        }
        if !unique.insert(entry.to_owned()) {
            return Err(format!("duplicate Protobuf manifest entry: {entry}").into());
        }
        let path = proto_root.join(entry);
        if !path.is_file() {
            return Err(format!("listed Protobuf file does not exist: {}", path.display()).into());
        }
        relative_files.push(entry.to_owned());
    }

    let mut sorted = relative_files.clone();
    sorted.sort();
    if relative_files != sorted {
        return Err("api/proto/latent-api.protos must be sorted".into());
    }

    let actual = collect_proto_files(proto_root)?;
    let listed = relative_files.iter().cloned().collect::<BTreeSet<_>>();
    if actual != listed {
        let missing = actual.difference(&listed).cloned().collect::<Vec<_>>();
        let stale = listed.difference(&actual).cloned().collect::<Vec<_>>();
        return Err(format!(
            "Protobuf input manifest is not exhaustive; missing={missing:?}, stale={stale:?}"
        )
        .into());
    }

    Ok(relative_files
        .into_iter()
        .map(|relative| proto_root.join(relative))
        .collect())
}

fn collect_proto_files(proto_root: &Path) -> Result<BTreeSet<String>, Box<dyn Error>> {
    let mut pending = vec![proto_root.to_path_buf()];
    let mut files = BTreeSet::new();
    while let Some(directory) = pending.pop() {
        let mut entries = fs::read_dir(&directory)?.collect::<Result<Vec<_>, _>>()?;
        entries.sort_by_key(std::fs::DirEntry::file_name);
        for entry in entries {
            let path = entry.path();
            if entry.file_type()?.is_dir() {
                pending.push(path);
            } else if path.extension() == Some(OsStr::new("proto")) {
                files.insert(
                    path.strip_prefix(proto_root)?
                        .to_string_lossy()
                        .replace('\\', "/"),
                );
            }
        }
    }
    Ok(files)
}
