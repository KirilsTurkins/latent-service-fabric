use latent_core::PlatformError;
use std::path::Path;
use zeroize::Zeroizing;

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub(super) fn read(path: &Path) -> Result<Zeroizing<[u8; 32]>, PlatformError> {
    use std::fs::OpenOptions;
    use std::io::Read;
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};

    let failure = || super::invalid("isolatedAot.keyFile");
    let uid = rustix::process::geteuid().as_raw();
    let parent = path
        .parent()
        .ok_or_else(failure)?
        .metadata()
        .map_err(|_| failure())?;
    if !parent.is_dir() || parent.uid() != uid || parent.mode() & 0o077 != 0 {
        return Err(failure());
    }
    // NONBLOCK avoids waiting on a malicious special file before fstat rejects it.
    let flags = i32::try_from((rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::NONBLOCK).bits())
        .map_err(|_| failure())?;
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(flags)
        .open(path)
        .map_err(|_| failure())?;
    let before = file.metadata().map_err(|_| failure())?;
    let valid = |metadata: &std::fs::Metadata| {
        metadata.is_file()
            && metadata.len() == 32
            && metadata.uid() == uid
            && matches!(metadata.mode() & 0o7777, 0o400 | 0o600)
            && metadata.nlink() == 1
    };
    if !valid(&before) {
        return Err(failure());
    }
    let mut secret = Zeroizing::new([0; 32]);
    file.read_exact(&mut *secret).map_err(|_| failure())?;
    let mut extra = Zeroizing::new([0; 1]);
    if file.read(&mut *extra).map_err(|_| failure())? != 0 {
        return Err(failure());
    }
    let after = file.metadata().map_err(|_| failure())?;
    if !valid(&after)
        || before.mtime() != after.mtime()
        || before.mtime_nsec() != after.mtime_nsec()
        || before.ctime() != after.ctime()
        || before.ctime_nsec() != after.ctime_nsec()
    {
        return Err(failure());
    }
    Ok(secret)
}

#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
pub(super) fn read(_path: &Path) -> Result<Zeroizing<[u8; 32]>, PlatformError> {
    Err(super::supported().expect_err("this key reader is unsupported"))
}
