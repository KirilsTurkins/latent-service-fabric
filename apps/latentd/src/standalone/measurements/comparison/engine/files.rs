use super::Result;
use latent_artifacts::content_digest;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::io::Read;
use std::path::{Component, Path, PathBuf};

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Reference {
    pub path: String,
    pub sha256: String,
    pub bytes: String,
}
pub(super) fn required(name: &str) -> Result<PathBuf> {
    let path = PathBuf::from(std::env::var_os(name).ok_or("engine missing input")?);
    if !path.is_absolute() {
        return Err("engine input must be absolute".into());
    }
    Ok(path)
}
pub(super) fn read(path: &Path, maximum: usize) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    std::fs::File::open(path)?
        .take(u64::try_from(maximum + 1)?)
        .read_to_end(&mut bytes)?;
    if bytes.is_empty() || bytes.len() > maximum {
        return Err("engine input byte bound".into());
    }
    Ok(bytes)
}
pub(super) fn load(root: &Path, reference: &Reference, maximum: usize) -> Result<Vec<u8>> {
    let path = Path::new(&reference.path);
    if path
        .components()
        .any(|part| !matches!(part, Component::Normal(_)))
        || reference.path.contains('\\')
    {
        return Err("engine fixture reference path".into());
    }
    let absolute = root.join(path).canonicalize()?;
    if !absolute.starts_with(root) {
        return Err("engine fixture escaped root".into());
    }
    let bytes = read(&absolute, maximum)?;
    if reference.bytes != bytes.len().to_string() || reference.sha256 != content_digest(&bytes).0 {
        return Err("engine fixture reference integrity".into());
    }
    Ok(bytes)
}
pub(super) fn emit(value: &Value) -> Result<()> {
    use std::io::Write;
    let mut output = std::io::stdout().lock();
    serde_json::to_writer(&mut output, value)?;
    output.write_all(b"\n")?;
    output.flush()?;
    Ok(())
}
