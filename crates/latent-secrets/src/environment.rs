//! Bounded capture of the kernel's initial process environment. Reading each
//! value with `std::env::var_os` would allocate it before checking its size.
use crate::SecretError;
use rustix::fs::{self, Mode, OFlags};
use std::{fs::File, io::Read, os::unix::fs::MetadataExt};
use zeroize::Zeroizing;

pub(crate) fn capture(
    maximum: usize,
    checkpoint: &impl Fn() -> Result<(), SecretError>,
) -> Result<Zeroizing<Vec<u8>>, SecretError> {
    checkpoint()?;
    // The procfs descriptor is verified before selecting this process, and no
    // configurable path or environment key can redirect the filesystem walk.
    let flags =
        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK;
    let proc = fs::open("/proc", flags, Mode::empty()).map_err(|_| SecretError::Unavailable)?;
    if fs::fstatfs(&proc)
        .map_err(|_| SecretError::Unavailable)?
        .f_type
        != fs::PROC_SUPER_MAGIC
    {
        return Err(SecretError::Unavailable);
    }
    let pid = rustix::process::getpid().as_raw_nonzero().get().to_string();
    let process = fs::openat(&proc, pid.as_str(), flags, Mode::empty())
        .map_err(|_| SecretError::Unavailable)?;
    let mut file = File::from(
        fs::openat(
            &process,
            "environ",
            OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
            Mode::empty(),
        )
        .map_err(|_| SecretError::Unavailable)?,
    );
    let metadata = file.metadata().map_err(|_| SecretError::Unavailable)?;
    if !metadata.is_file()
        || metadata.uid() != rustix::process::geteuid().as_raw()
        || metadata.mode() & 0o077 != 0
    {
        return Err(SecretError::PermissionDenied);
    }
    let mut bytes = Zeroizing::new(vec![0; maximum + 1]);
    let mut size = 0;
    while size < bytes.len() {
        checkpoint()?;
        let count = file
            .read(&mut bytes[size..])
            .map_err(|_| SecretError::Unavailable)?;
        if count == 0 {
            break;
        }
        size += count;
    }
    if size > maximum || (size != 0 && bytes[size - 1] != 0) {
        return Err(SecretError::Unavailable);
    }
    bytes.truncate(size);
    checkpoint()?;
    Ok(bytes)
}
pub(crate) fn get(
    bytes: &[u8],
    key: &str,
    maximum: usize,
) -> Result<Zeroizing<Vec<u8>>, SecretError> {
    let mut found = None;
    for entry in bytes.split(|b| *b == 0).filter(|e| !e.is_empty()) {
        let index = entry
            .iter()
            .position(|b| *b == b'=')
            .ok_or(SecretError::Unavailable)?;
        if &entry[..index] == key.as_bytes() {
            if found.is_some() || entry.len() - index - 1 > maximum {
                return Err(SecretError::Unavailable);
            }
            found = Some(&entry[index + 1..]);
        }
    }
    Ok(Zeroizing::new(found.ok_or(SecretError::NotFound)?.to_vec()))
}
