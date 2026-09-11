use std::fs::File;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use latent_artifacts::content_digest;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use super::{Clock, Plan, Result};
use crate::standalone::measurements::read;

pub(super) struct Inputs {
    pub plan: Plan,
    pub identity: Value,
    pub directory: PathBuf,
    pub data: PathBuf,
    pub root: PathBuf,
    pub data_identity: Value,
    pub reopen: Value,
    pub plan_sha256: String,
    pub identity_sha256: String,
}

impl Inputs {
    pub fn load() -> Result<Self> {
        let plan_bytes = read(&required("LSF_PHASE1_COMPARISON_PLAN")?, 64 * 1024)?;
        let identity_bytes = read(&required("LSF_PHASE1_COMPARISON_IDENTITY")?, 1024 * 1024)?;
        let plan: Plan = serde_json::from_slice(&plan_bytes)?;
        plan.validate()?;
        let identity: Value = serde_json::from_slice(&identity_bytes)?;
        let directory = required("LSF_PHASE1_COMPARISON_OUTPUT")?.canonicalize()?;
        let data = required("LSF_PHASE1_COMPARISON_DATA_ROOT")?.canonicalize()?;
        let echo = required("LSF_ECHO_COMPONENT")?.canonicalize()?;
        let root = echo
            .parent()
            .and_then(Path::parent)
            .ok_or("catalog evidence root")?
            .to_owned();
        if !directory.starts_with(&root) || data.starts_with(&root) || root.starts_with(&data) {
            return Err("catalog evidence/data root overlap".into());
        }
        let data_identity = data_identity(&data)?;
        let marker = &data_identity["marker"];
        let group = format!(
            "pair-{:02}-{}-{}",
            plan.repetition, plan.shape, plan.variant
        );
        if marker["schema"] != "latent.optimization.catalog-data-owner.v1"
            || marker["variant"] != plan.variant
            || marker["shape"] != plan.shape
            || marker["repetition"] != plan.repetition
            || marker["group"] != group
            || marker["source_commit"] != identity["source"]["commit"]
            || marker.as_object().is_none_or(|object| object.len() != 7)
            || marker["nonce"].as_str().is_none_or(|nonce| {
                nonce.len() != 32
                    || !nonce
                        .bytes()
                        .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
            })
        {
            return Err("catalog data marker association".into());
        }
        let reopen = if plan.mode == "reopen" {
            let value: Value = serde_json::from_slice(&read(
                &required("LSF_CATALOG_REOPEN_RECEIPT")?,
                1024 * 1024,
            )?)?;
            let actual = file_reference(
                &data.join("data/deployments/catalog.json"),
                "data/deployments/catalog.json",
                1024 * 1024 * 1024,
            )?;
            if value["schema"] != "latent.optimization.catalog-reopen.v1"
                || value["data_identity"] != data_identity
                || value["catalog"] != actual
            {
                return Err("catalog reopen source state differs".into());
            }
            value
        } else {
            if std::env::var_os("LSF_CATALOG_REOPEN_RECEIPT").is_some()
                || data.join("data").exists()
            {
                return Err("catalog initial root already used".into());
            }
            Value::Null
        };
        Ok(Self {
            plan,
            identity,
            directory,
            data,
            root,
            data_identity,
            reopen,
            plan_sha256: content_digest(&plan_bytes).0,
            identity_sha256: content_digest(&identity_bytes).0,
        })
    }

    pub fn ready(&self, clock: Clock) -> Result<()> {
        emit(
            &json!({"schema":"latent.optimization.catalog-ready.v1","event":"ready",
            "process_id":std::process::id(),"mode":self.plan.mode,
            "plan_sha256":self.plan_sha256,"identity_sha256":self.identity_sha256,
            "elapsed_nanos":clock.elapsed().to_string(),"observation_hold_millis":100}),
        )
    }

    pub fn complete(&self, passed: bool, clock: Clock) -> Result<()> {
        let path = self.directory.join("catalog.json");
        let name = path
            .strip_prefix(&self.root)?
            .to_str()
            .ok_or("catalog raw path")?
            .replace('\\', "/");
        emit(
            &json!({"schema":"latent.optimization.catalog-complete.v1","event":"measurement-complete",
            "process_id":std::process::id(),"mode":self.plan.mode,
            "plan_sha256":self.plan_sha256,"identity_sha256":self.identity_sha256,
            "raw":file_reference(&path,&name,32*1024*1024)?,"outcome":if passed{"passed"}else{"failed"},
            "elapsed_nanos":clock.elapsed().to_string(),"observation_hold_millis":100}),
        )
    }
}

pub(in crate::standalone::measurements::comparison) fn file_reference(
    path: &Path,
    name: &str,
    maximum: u64,
) -> Result<Value> {
    if !std::fs::symlink_metadata(path)?.file_type().is_file() {
        return Err("catalog nonregular artifact".into());
    }
    let mut file = File::open(path)?;
    let expected = file.metadata()?.len();
    if expected == 0 || expected > maximum {
        return Err("catalog file byte bound".into());
    }
    let mut scratch = [0_u8; 16 * 1024];
    let mut bytes = 0_u64;
    let mut digest = Sha256::new();
    loop {
        let count = file.read(&mut scratch)?;
        if count == 0 {
            break;
        }
        bytes = bytes
            .checked_add(count as u64)
            .ok_or("catalog file count overflow")?;
        if bytes > maximum {
            return Err("catalog file grew beyond bound".into());
        }
        digest.update(&scratch[..count]);
    }
    if bytes != expected {
        return Err("catalog file size changed".into());
    }
    Ok(
        json!({"path":name,"bytes":bytes.to_string(),"sha256":format!("sha256:{:x}",digest.finalize())}),
    )
}

fn required(name: &str) -> Result<PathBuf> {
    let path = PathBuf::from(std::env::var_os(name).ok_or("catalog missing input")?);
    if !path.is_absolute() {
        return Err("catalog input must be absolute".into());
    }
    Ok(path)
}

pub(in crate::standalone::measurements::comparison) fn data_identity(data: &Path) -> Result<Value> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let metadata = std::fs::symlink_metadata(data)?;
        if !metadata.file_type().is_dir() {
            return Err("catalog data is not a directory".into());
        }
        let marker = data.join("owner.json");
        if !std::fs::symlink_metadata(&marker)?.file_type().is_file() {
            return Err("catalog owner marker not regular".into());
        }
        let bytes = read(&marker, 4096)?;
        let value: Value = serde_json::from_slice(&bytes)?;
        Ok(
            json!({"device":metadata.dev().to_string(),"inode":metadata.ino().to_string(),
            "marker_sha256":content_digest(&bytes).0,"marker":value}),
        )
    }
    #[cfg(not(unix))]
    {
        let _ = data;
        Err("catalog native root identity unsupported".into())
    }
}

fn emit(value: &Value) -> Result<()> {
    let bytes = serde_json::to_vec(value)?;
    if bytes.len() > 16 * 1024 {
        return Err("catalog event byte bound".into());
    }
    let mut stdout = std::io::stdout().lock();
    stdout.write_all(b"\n")?;
    stdout.write_all(&bytes)?;
    stdout.write_all(b"\n")?;
    stdout.flush()?;
    Ok(())
}
