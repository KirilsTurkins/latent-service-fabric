use super::super::{corrupt, unavailable, Result};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
};
pub(super) fn present(path: &Path) -> Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(_) => Err(unavailable()),
    }
}
pub(super) fn directory(path: &Path) -> Result<()> {
    let m = fs::symlink_metadata(path).map_err(|_| corrupt())?;
    if !m.is_dir() || m.file_type().is_symlink() {
        return Err(corrupt());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if m.uid() != rustix::process::geteuid().as_raw() || m.mode() & 0o7777 != 0o700 {
            return Err(corrupt());
        }
    }
    Ok(())
}
pub(super) fn create_directory(path: &Path) -> Result<()> {
    let mut builder = fs::DirBuilder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(path).map_err(|_| unavailable())?;
    sync(path.parent().ok_or_else(corrupt)?)
}
fn options() -> OpenOptions {
    let mut o = OpenOptions::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        o.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .mode(0o600);
    }
    o
}
fn ordinary(file: &File) -> Result<usize> {
    let m = file.metadata().map_err(|_| unavailable())?;
    if !m.is_file() {
        return Err(corrupt());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if m.nlink() != 1
            || m.uid() != rustix::process::geteuid().as_raw()
            || m.mode() & 0o7777 != 0o600
        {
            return Err(corrupt());
        }
    }
    usize::try_from(m.len()).map_err(|_| corrupt())
}
pub(super) fn read(path: &Path, max: usize) -> Result<Vec<u8>> {
    let mut f = options().read(true).open(path).map_err(|_| corrupt())?;
    let size = ordinary(&f)?;
    if size > max {
        return Err(corrupt());
    }
    let mut bytes = vec![0; size];
    f.read_exact(&mut bytes).map_err(|_| corrupt())?;
    let mut tail = [0];
    if f.read(&mut tail).map_err(|_| corrupt())? != 0 || ordinary(&f)? != size {
        return Err(corrupt());
    }
    Ok(bytes)
}
pub(super) fn sync(path: &Path) -> Result<()> {
    File::open(path)
        .and_then(|f| f.sync_all())
        .map_err(|_| unavailable())
}
pub(super) fn stage(path: &Path, bytes: &[u8]) -> Result<()> {
    let bound = registered_bound(path)?;
    if bytes.len() > bound {
        return Err(corrupt());
    }
    #[cfg(test)]
    WRITTEN.with(|w| w.set(w.get() + bytes.len()));
    if present(path)? {
        remove(path, bound)?;
    }
    let mut f = options()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|_| unavailable())?;
    f.write_all(bytes)
        .and_then(|()| f.sync_all())
        .map_err(|_| unavailable())?;
    Ok(())
}
#[cfg(test)]
thread_local! {pub(super) static WRITTEN:std::cell::Cell<usize>=const{std::cell::Cell::new(0)};}
pub(super) fn atomic(path: &Path, bytes: &[u8]) -> Result<()> {
    let bound = registered_bound(path)?;
    let next = path.with_extension("next");
    stage(&next, bytes)?;
    if present(path)? {
        let _ = read(path, bound)?;
    }
    fs::rename(next, path).map_err(|_| unavailable())?;
    sync(path.parent().ok_or_else(corrupt)?)
}
fn registered_bound(path: &Path) -> Result<usize> {
    match path.file_name().and_then(|n| n.to_str()) {
        Some("MODE" | "HEAD" | "MODE.next" | "HEAD.next") => Ok(1024),
        Some("INTENT" | "INTENT.next" | "record.next") => Ok(16384),
        _ => Err(corrupt()),
    }
}
pub(super) fn remove(path: &Path, max: usize) -> Result<()> {
    if !present(path)? {
        return Ok(());
    }
    let _ = read(path, max)?;
    fs::remove_file(path).map_err(|_| unavailable())?;
    sync(path.parent().ok_or_else(corrupt)?)
}
pub(super) fn names(path: &Path, max: usize) -> Result<Vec<String>> {
    directory(path)?;
    let mut result = Vec::new();
    for e in fs::read_dir(path).map_err(|_| unavailable())? {
        if result.len() == max {
            return Err(corrupt());
        }
        let name = e
            .map_err(|_| unavailable())?
            .file_name()
            .into_string()
            .map_err(|_| corrupt())?;
        if name.len() > 64 {
            return Err(corrupt());
        }
        result.push(name);
    }
    result.sort();
    Ok(result)
}
pub(super) struct Root {
    pub path: PathBuf,
    lock: File,
}
impl Drop for Root {
    fn drop(&mut self) {
        let _ = self.lock.unlock();
    }
}
pub(super) fn root(path: &Path) -> Result<Root> {
    #[cfg(not(unix))]
    {
        let _ = path;
        return Err(super::super::error(
            latent_core::PlatformErrorCode::IncompatibleContract,
            "audit-platform-unsupported",
        ));
    }
    #[cfg(unix)]
    {
        if path.as_os_str().len() > 4096 {
            return Err(corrupt());
        }
        let absolute = std::path::absolute(path).map_err(|_| unavailable())?;
        if absolute.as_os_str().len() > 4096
            || absolute.components().count() > 128
            || absolute.components().any(|component| {
                !matches!(
                    component,
                    std::path::Component::RootDir | std::path::Component::Normal(_)
                )
            })
        {
            return Err(corrupt());
        }
        let parent = absolute.parent().ok_or_else(corrupt)?.to_path_buf();
        trusted_ancestors(&parent)?;
        let path = parent.join(absolute.file_name().ok_or_else(corrupt)?);
        if path.as_os_str().len() > 4096 {
            return Err(corrupt());
        }
        if !present(&path)? {
            create_directory(&path)?;
        }
        directory(&path)?;
        let lock = options()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path.join(".audit.lock"))
            .map_err(|_| unavailable())?;
        if ordinary(&lock)? > 0 {
            return Err(corrupt());
        }
        lock.try_lock().map_err(|_| unavailable())?;
        Ok(Root { path, lock })
    }
}
#[cfg(unix)]
fn trusted_ancestors(path: &Path) -> Result<()> {
    use std::os::unix::fs::MetadataExt;
    let uid = rustix::process::geteuid().as_raw();
    let mut current = PathBuf::new();
    let mut depth = 0;
    for component in path.components() {
        depth += 1;
        if depth > 128 {
            return Err(corrupt());
        }
        match component {
            std::path::Component::RootDir | std::path::Component::Normal(_) => {
                current.push(component);
            }
            _ => return Err(corrupt()),
        }
        let m = match fs::symlink_metadata(&current) {
            Ok(m) => m,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                // The previous component was verified before this mutation.
                // Each newly owned ancestor is private and its name durable
                // before we continue to the next bounded path component.
                create_directory(&current)?;
                directory(&current)?;
                fs::symlink_metadata(&current).map_err(|_| corrupt())?
            }
            Err(_) => return Err(corrupt()),
        };
        if !m.is_dir() || m.file_type().is_symlink() || (m.uid() != uid && m.uid() != 0) {
            return Err(corrupt());
        }
        // Root-owned sticky system temporary parents prevent other UIDs from
        // replacing a child owned by this process; each later child is checked.
        if m.mode() & 0o022 != 0 && !(m.uid() == 0 && m.mode() & 0o1000 != 0) {
            return Err(corrupt());
        }
    }
    Ok(())
}
pub(super) fn epoch() -> Result<String> {
    #[cfg(unix)]
    {
        const HEX: &[u8; 16] = b"0123456789abcdef";
        let mut bytes = [0u8; 16];
        File::open("/dev/urandom")
            .and_then(|mut f| f.read_exact(&mut bytes))
            .map_err(|_| unavailable())?;
        let mut result = String::with_capacity(32);
        for byte in bytes {
            result.push(char::from(HEX[usize::from(byte >> 4)]));
            result.push(char::from(HEX[usize::from(byte & 15)]));
        }
        Ok(result)
    }
    #[cfg(not(unix))]
    {
        Err(unavailable())
    }
}
