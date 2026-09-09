use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::{Component, Path};

use latent_artifacts::content_digest;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::Result;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Reference {
    pub path: String,
    pub sha256: String,
    pub bytes: String,
}

pub(super) fn read(path: &Path, maximum: usize) -> Result<Vec<u8>> {
    if !fs::metadata(path)?.is_file() {
        return Err("ownership nonregular input".into());
    }
    let file = fs::File::open(path)?;
    let size = file.metadata()?.len();
    if !file.metadata()?.is_file() || size == 0 || size > u64::try_from(maximum)? {
        return Err("ownership input byte bound".into());
    }
    let mut bytes = Vec::new();
    file.take(
        u64::try_from(maximum)?
            .checked_add(1)
            .ok_or("input bound overflow")?,
    )
    .read_to_end(&mut bytes)?;
    if u64::try_from(bytes.len())? != size {
        return Err("ownership input changed".into());
    }
    Ok(bytes)
}

pub(super) fn load(root: &Path, reference: &Reference, maximum: usize) -> Result<Vec<u8>> {
    let name = Path::new(&reference.path);
    if reference.path.contains('\\')
        || name
            .components()
            .any(|p| !matches!(p, Component::Normal(_)))
    {
        return Err("ownership artifact path".into());
    }
    let path = root.join(name).canonicalize()?;
    if !path.starts_with(root.canonicalize()?) {
        return Err("ownership artifact escaped root".into());
    }
    let bytes = read(&path, maximum)?;
    let size = bytes.len().to_string();
    if reference.sha256 != content_digest(&bytes).0 || reference.bytes != size {
        return Err("ownership artifact identity".into());
    }
    Ok(bytes)
}

pub(super) fn retain(root: &Path, path: &Path, bytes: &[u8]) -> Result<Reference> {
    if bytes.is_empty() || bytes.len() > 8 * 1024 * 1024 {
        return Err("ownership retained byte bound".into());
    }
    let name = path
        .strip_prefix(root)?
        .to_str()
        .ok_or("ownership artifact UTF-8")?
        .replace('\\', "/");
    if Path::new(&name)
        .components()
        .any(|p| !matches!(p, Component::Normal(_)))
    {
        return Err("ownership output path".into());
    }
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(Reference {
        path: name,
        sha256: content_digest(bytes).0,
        bytes: bytes.len().to_string(),
    })
}

pub(super) fn emit(value: &Value) -> Result<()> {
    let bytes = serde_json::to_vec(value)?;
    if bytes.len() > 16_384 {
        return Err("ownership event byte bound".into());
    }
    let mut stdout = std::io::stdout().lock();
    stdout.write_all(b"\n")?;
    stdout.write_all(&bytes)?;
    stdout.write_all(b"\n")?;
    stdout.flush()?;
    Ok(())
}
