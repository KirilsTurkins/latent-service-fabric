//! One bounded roll-forward intent. Only HEAD, never staging, grants retention.
use super::{
    capacity, check_time, corrupt, fs, io_error, model, read_bounded_file, shared_content,
    sync_dir, uncertain, write_synced, Instant, Path, PathBuf, PlatformError,
    PublicationRetentionFence,
};
use model::{decode, digest, encode, Head, MARKER, MAX_HEAD, MAX_INTENT};
use serde::{Deserialize, Serialize};
use std::io::{Read, Seek, SeekFrom};

const DIRECTORY: &str = "retention";
const INITIALIZED: &[u8] = b"lsf-publication-retention-v1\n";

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Saved {
    head: Head,
    checksum: [u8; 32],
}
impl Saved {
    fn new(head: Head) -> Result<Self, PlatformError> {
        let checksum = digest(&encode(&head, MAX_HEAD - 1024)?);
        Ok(Self { head, checksum })
    }
    fn validate(&self, authority: [u8; 32]) -> Result<(), PlatformError> {
        self.head.validate(authority)?;
        if self.head.authority == [0; 32] {
            return Err(corrupt());
        }
        if self.checksum != digest(&encode(&self.head, MAX_HEAD - 1024)?) {
            return Err(corrupt());
        }
        Ok(())
    }
}
#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Intent {
    old: [u8; 32],
    next: Saved,
}

pub(super) fn authority(root: &Path) -> Result<[u8; 32], PlatformError> {
    Ok(digest(&required(&root.join("lifecycle/MODE"), 4096)?))
}
fn directory(root: &Path) -> PathBuf {
    root.join("lifecycle").join(DIRECTORY)
}

pub(super) fn load(
    root: &Path,
    promoted: bool,
    recover: bool,
) -> Result<Option<Head>, PlatformError> {
    let path = directory(root);
    if !exists(&path)? {
        return if promoted { Err(corrupt()) } else { Ok(None) };
    }
    shared_content::directory(&path)?;
    let authority = authority(root)?;
    validate_names(&path)?;
    let initialized = optional(&path.join("INITIALIZED"), 64)?;
    if initialized
        .as_deref()
        .is_some_and(|bytes| bytes != INITIALIZED)
    {
        return Err(corrupt());
    }
    let head_bytes = optional(&path.join("HEAD"), MAX_HEAD)?;
    let Some(head_bytes) = head_bytes else {
        if promoted || initialized.is_some() || exists(&path.join("INTENT"))? {
            return Err(corrupt());
        }
        if recover {
            for name in ["HEAD.next", "INTENT.next", "INITIALIZED.next"] {
                if exists(&path.join(name))? {
                    remove(&path.join(name))?;
                }
            }
        }
        return Ok(None); // interrupted empty initialization, no committed pins
    };
    let saved: Saved = decode(&head_bytes, MAX_HEAD)?;
    saved.validate(authority)?;
    if (initialized.is_none() || !promoted) && saved.head.revision != 0 {
        return Err(corrupt());
    }
    if promoted && initialized.is_none() {
        return Err(corrupt());
    }
    let mut head = saved.head;
    if let Some(bytes) = optional(&path.join("INTENT"), MAX_INTENT)? {
        if !promoted || initialized.is_none() {
            return Err(corrupt());
        }
        let intent: Intent = decode(&bytes, MAX_INTENT)?;
        intent.next.validate(authority)?;
        let receipt = intent.next.head.receipts.last().ok_or_else(corrupt)?;
        if digest(&head_bytes) == intent.old {
            if head.next(&receipt.request).map_err(|_| corrupt())? != intent.next.head
                || fence(root, &head)? != receipt.request.expected_catalog_fence
            {
                return Err(corrupt());
            }
        } else if head != intent.next.head {
            return Err(corrupt());
        }
        head = intent.next.head;
        if recover {
            // Never execute a fresh request on recovery. This is exactly the
            // already-authorized durable intent, with original receipt identity.
            atomic(
                &path.join("HEAD"),
                &encode(&Saved::new(head.clone())?, MAX_HEAD)?,
            )?;
            remove(&path.join("INTENT"))?;
        }
    }
    if recover {
        for name in ["HEAD.next", "INTENT.next", "INITIALIZED.next"] {
            if exists(&path.join(name))? {
                remove(&path.join(name))?;
            }
        }
    }
    Ok(Some(head))
}

pub(super) fn persist(
    root: &Path,
    old: &Head,
    next: &Head,
    deadline: Instant,
) -> Result<(), PlatformError> {
    check_time(deadline)?;
    let path = directory(root);
    initialize(root, old)?;
    check_time(deadline)?;
    let old_bytes = encode(&Saved::new(old.clone())?, MAX_HEAD)?;
    if required(&path.join("HEAD"), MAX_HEAD)? != old_bytes {
        return Err(corrupt());
    }
    if exists(&path.join("INTENT"))? {
        return Err(uncertain());
    }
    let intent = Intent {
        old: digest(&old_bytes),
        next: Saved::new(next.clone())?,
    };
    let bytes = encode(&intent, MAX_INTENT)?;
    atomic(&path.join("INTENT"), &bytes)?;
    fault(1)?;
    check_time(deadline)?;
    atomic(&path.join("HEAD"), &encode(&intent.next, MAX_HEAD)?)?;
    fault(2)?;
    check_time(deadline)?;
    remove(&path.join("INTENT"))?;
    fault(3)?;
    Ok(())
}
fn initialize(root: &Path, old: &Head) -> Result<(), PlatformError> {
    let path = directory(root);
    if !exists(&path)? {
        fs::create_dir(&path).map_err(io_error)?;
        sync_dir(&root.join("lifecycle"))?;
    }
    shared_content::directory(&path)?;
    let initialized = path.join("INITIALIZED");
    if !exists(&initialized)? {
        if old.revision != 0 {
            return Err(corrupt());
        }
        atomic(
            &path.join("HEAD"),
            &encode(&Saved::new(old.clone())?, MAX_HEAD)?,
        )?;
        atomic(&initialized, INITIALIZED)?;
    }
    if required(&initialized, 64)? != INITIALIZED {
        return Err(corrupt());
    }
    let marker = root.join("LIFECYCLE_MODE");
    let previous = required(&marker, 64)?;
    if previous != MARKER {
        if previous != b"lsf-release-lifecycle-v1\n" || old.revision != 0 {
            return Err(corrupt());
        }
        // Publish refusal for older readers before accepting any durable pin.
        atomic(&marker, MARKER)?;
    }
    fault(4)
}

/// Only fixed-size control records and the web HEAD's existing digest trailer
/// are read: no publication-directory scan or payload verification per batch.
pub(super) fn fence(root: &Path, head: &Head) -> Result<PublicationRetentionFence, PlatformError> {
    use sha2::Digest;
    let mut hash = sha2::Sha256::new();
    hash.update(b"lsf-publication-retention-fence-v1\0");
    for bytes in [
        required(&root.join("lifecycle/HEAD"), 4096)?,
        web_head(root)?,
        encode(head, MAX_HEAD)?,
    ] {
        hash.update((bytes.len() as u64).to_le_bytes());
        hash.update(bytes);
    }
    Ok(PublicationRetentionFence(hash.finalize().into()))
}
fn web_head(root: &Path) -> Result<Vec<u8>, PlatformError> {
    let path = root.join("web/HEAD");
    if !exists(&path)? {
        return Ok(Vec::new());
    }
    let metadata = shared_content::regular(&path)?;
    if metadata.len() < 73 {
        return Err(corrupt());
    }
    let mut file = fs::File::open(path).map_err(io_error)?;
    if file.metadata().map_err(io_error)?.len() != metadata.len() {
        return Err(corrupt());
    }
    file.seek(SeekFrom::End(-72)).map_err(io_error)?;
    let mut trailer = [0u8; 72];
    file.read_exact(&mut trailer).map_err(io_error)?;
    if !trailer.starts_with(b"sha256:")
        || trailer[71] != b'\n'
        || !trailer[7..71].iter().all(u8::is_ascii_hexdigit)
    {
        return Err(corrupt());
    }
    let mut result = metadata.len().to_le_bytes().to_vec();
    result.extend_from_slice(&trailer);
    Ok(result)
}

fn validate_names(path: &Path) -> Result<(), PlatformError> {
    for (index, entry) in fs::read_dir(path).map_err(io_error)?.enumerate() {
        if index >= 6 {
            return Err(corrupt());
        }
        let entry = entry.map_err(io_error)?;
        let limit = match entry.file_name().to_str() {
            Some("HEAD" | "HEAD.next") => MAX_HEAD,
            Some("INTENT" | "INTENT.next") => MAX_INTENT,
            Some("INITIALIZED" | "INITIALIZED.next") => 64,
            _ => return Err(corrupt()),
        };
        if shared_content::regular(&entry.path())?.len() > limit as u64 {
            return Err(capacity());
        }
    }
    Ok(())
}
pub(super) fn exists(path: &Path) -> Result<bool, PlatformError> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(io_error(error)),
    }
}
fn optional(path: &Path, limit: usize) -> Result<Option<Vec<u8>>, PlatformError> {
    if exists(path)? {
        required(path, limit).map(Some)
    } else {
        Ok(None)
    }
}
fn required(path: &Path, limit: usize) -> Result<Vec<u8>, PlatformError> {
    shared_content::regular(path)?;
    read_bounded_file(path, limit, "publication retention")
}
fn atomic(path: &Path, bytes: &[u8]) -> Result<(), PlatformError> {
    let temporary = path.with_extension("next");
    if exists(&temporary)? {
        remove(&temporary)?;
    }
    write_synced(&temporary, bytes)?;
    if exists(path)? {
        shared_content::regular(path)?;
    }
    fs::rename(&temporary, path).map_err(io_error)?;
    sync_dir(path.parent().ok_or_else(corrupt)?)
}
fn remove(path: &Path) -> Result<(), PlatformError> {
    shared_content::regular(path)?;
    fs::remove_file(path).map_err(io_error)?;
    sync_dir(path.parent().ok_or_else(corrupt)?)
}
#[cfg(any(test, feature = "development-test-host"))]
thread_local! {pub(super) static FAIL:std::cell::Cell<u8>=const{std::cell::Cell::new(0)};}
fn fault(point: u8) -> Result<(), PlatformError> {
    #[cfg(any(test, feature = "development-test-host"))]
    if FAIL.with(|value| {
        if value.get() == point {
            value.set(0);
            true
        } else {
            false
        }
    }) {
        return Err(uncertain());
    }
    let _ = point;
    Ok(())
}
