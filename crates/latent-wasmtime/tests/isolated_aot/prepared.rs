//! Immutable test inputs only. This manifest is never production sandbox evidence.
use std::collections::BTreeMap;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};

use serde::Deserialize;
use sha2::{Digest, Sha256};

const MAX_EXECUTABLE: u64 = 512 * 1024 * 1024;
const MAX_MANIFEST: u64 = 64 * 1024;
const PROFILE: &str = "debug-all-features-v2";
const SCHEMA: &str = "latent.aot-test-inputs.v1";

pub struct Executable {
    pub path: PathBuf,
    pub digest: [u8; 32],
}

#[derive(Deserialize)]
struct Identity {
    path: PathBuf,
    sha256: [u8; 32],
    bytes: u64,
}
#[derive(Deserialize)]
struct Entry {
    original: Identity,
    prepared: Option<Identity>,
}
#[derive(Deserialize)]
struct Manifest {
    schema: String,
    profile: String,
    entries: BTreeMap<String, Entry>,
}

pub fn digest(path: &Path) -> Result<[u8; 32], &'static str> {
    let mut source = File::open(path).map_err(|_| "missing-executable")?;
    let metadata = source.metadata().map_err(|_| "executable-metadata")?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > MAX_EXECUTABLE {
        return Err("executable-size-limit");
    }
    let mut hash = Sha256::new();
    let mut buffer = [0; 16 * 1024];
    let mut total = 0_u64;
    loop {
        let size = source.read(&mut buffer).map_err(|_| "executable-read")?;
        if size == 0 {
            break;
        }
        total += size as u64;
        if total > MAX_EXECUTABLE {
            return Err("executable-size-limit");
        }
        hash.update(&buffer[..size]);
    }
    if total != metadata.len() {
        return Err("executable-length-changed");
    }
    Ok(hash.finalize().into())
}

fn canonical_file(path: &Path) -> Result<(), &'static str> {
    use std::os::unix::fs::PermissionsExt;
    if !path.is_absolute() || path.as_os_str().len() > 4096 {
        return Err("noncanonical-executable-path");
    }
    let metadata = path.symlink_metadata().map_err(|_| "missing-executable")?;
    if !metadata.is_file()
        || path.canonicalize().map_err(|_| "executable-path")? != path
        || metadata.permissions().mode() & 0o111 == 0
    {
        return Err("noncanonical-or-nonexecutable-file");
    }
    Ok(())
}

pub fn load(
    manifest_path: &Path,
    expected_manifest: [u8; 32],
    role: &str,
    original: &Path,
) -> Result<Executable, &'static str> {
    if !matches!(role, "compiler" | "aot_supervisor") {
        return Err("wrong-executable-role");
    }
    if !manifest_path.is_absolute()
        || manifest_path
            .canonicalize()
            .map_err(|_| "missing-manifest")?
            != manifest_path
    {
        return Err("noncanonical-manifest-path");
    }
    let mut bytes = Vec::new();
    File::open(manifest_path)
        .map_err(|_| "missing-manifest")?
        .take(MAX_MANIFEST + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "manifest-read")?;
    if bytes.len() as u64 > MAX_MANIFEST {
        return Err("manifest-size-limit");
    }
    let actual: [u8; 32] = Sha256::digest(&bytes).into();
    if actual != expected_manifest {
        return Err("stale-manifest-identity");
    }
    let manifest: Manifest = serde_json::from_slice(&bytes).map_err(|_| "invalid-manifest")?;
    if manifest.schema != SCHEMA || manifest.profile != PROFILE {
        return Err("wrong-manifest-schema-or-profile");
    }
    let entry = manifest
        .entries
        .get(role)
        .ok_or("missing-executable-role")?;
    canonical_file(original)?;
    if entry.original.path != original || digest(original)? != entry.original.sha256 {
        return Err("stale-original-identity");
    }
    let selected = entry
        .prepared
        .as_ref()
        .ok_or("missing-prepared-executable")?;
    if selected.path != manifest_path.parent().ok_or("manifest-parent")?.join(role)
        || selected.path == original
    {
        return Err("wrong-prepared-path");
    }
    canonical_file(&selected.path)?;
    if selected.bytes
        != selected
            .path
            .metadata()
            .map_err(|_| "missing-executable")?
            .len()
        || digest(&selected.path)? != selected.sha256
    {
        return Err("modified-prepared-executable");
    }
    Ok(Executable {
        path: selected.path.clone(),
        digest: selected.sha256,
    })
}

fn parse_digest(text: &str) -> Result<[u8; 32], &'static str> {
    if text.len() != 64 || !text.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("invalid-manifest-digest");
    }
    let mut result = [0; 32];
    for (index, byte) in result.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&text[index * 2..index * 2 + 2], 16)
            .map_err(|_| "invalid-manifest-digest")?;
    }
    Ok(result)
}

pub fn select(role: &str, original: &Path) -> Executable {
    let _stage = super::diagnostics::Span::new("expected-digest-and-input-validation");
    let result = (|| {
        let original = original
            .canonicalize()
            .map_err(|_| "missing-cargo-executable")?;
        match std::env::var_os("LSF_AOT_TEST_INPUTS") {
            Some(path) => {
                let expected = std::env::var("LSF_AOT_TEST_INPUTS_SHA256")
                    .map_err(|_| "missing-manifest-identity")?;
                load(Path::new(&path), parse_digest(&expected)?, role, &original)
            }
            None => {
                if std::env::var_os("LSF_AOT_TEST_EXECUTION_ONLY").is_some() {
                    return Err("missing-prepared-inputs");
                }
                Ok(Executable {
                    digest: digest(&original)?,
                    path: original,
                })
            }
        }
    })();
    result.unwrap_or_else(|reason| {
        panic!(
            "AOT test inputs: {reason}; prepare explicitly using tools/aot_test_inputs.py \
             prepare --inventory target/aot-tests.jsonl --output target/aot-test-inputs \
             (see docs/development/aot-test-inputs.md)"
        )
    })
}
