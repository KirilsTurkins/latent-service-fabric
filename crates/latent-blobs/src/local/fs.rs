//! Every descendant operation is relative to a retained no-follow directory FD.
//! Private directories exclude writers outside the service identity. Inode and
//! type checks additionally reject replacement between separate operations.
use super::model::{LocalBlobError as Error, Result};
use rustix::fs::{self, AtFlags, Mode, OFlags, RenameFlags};
use std::{
    ffi::OsString,
    fs::{File, Metadata},
    io::{Read, Write},
    os::unix::fs::MetadataExt,
    path::{Component, Path},
    sync::Arc,
};

#[derive(Clone, Copy, PartialEq, Eq)]
pub(crate) struct Identity {
    pub device: u64,
    pub inode: u64,
    pub size: u64,
    modified: (i64, i64),
    changed: (i64, i64),
}
impl Identity {
    pub fn of(file: &File) -> Result<Self> {
        let m = file.metadata().map_err(failure)?;
        Ok(Self {
            device: m.dev(),
            inode: m.ino(),
            size: m.len(),
            modified: (m.mtime(), m.mtime_nsec()),
            changed: (m.ctime(), m.ctime_nsec()),
        })
    }
}
pub(crate) struct Directory {
    pub file: File,
    parent: Option<(Arc<Directory>, OsString)>,
    identity: (u64, u64),
    private: bool,
    #[cfg(test)]
    faults: Arc<std::sync::Mutex<Option<Fault>>>,
}
#[cfg(test)]
struct Fault {
    operation: &'static str,
    skip: usize,
}
impl Directory {
    pub fn root(path: &Path) -> Result<Arc<Self>> {
        if !path.is_absolute() || path.as_os_str().len() > 4096 {
            return Err(Error::Invalid);
        }
        let names: Vec<_> = path.components().collect();
        if names.len() < 2 || names.len() > 64 || names[0] != Component::RootDir {
            return Err(Error::Invalid);
        }
        let file = File::from(
            fs::open(
                "/",
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                Mode::empty(),
            )
            .map_err(errno)?,
        );
        let mut directory = Self::from_file(file, None, false)?;
        for (index, component) in names.iter().enumerate().skip(1) {
            let Component::Normal(name) = component else {
                return Err(Error::Invalid);
            };
            let last = index + 1 == names.len();
            if last {
                directory.validate()?;
                match fs::mkdirat(&directory.file, *name, Mode::RWXU) {
                    Ok(()) => {
                        directory.file.sync_all().map_err(failure)?;
                    }
                    Err(rustix::io::Errno::EXIST) => (),
                    Err(e) => return Err(errno(e)),
                }
            }
            let file = File::from(
                fs::openat(
                    &directory.file,
                    *name,
                    OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                    Mode::empty(),
                )
                .map_err(errno)?,
            );
            directory = Self::from_file(file, Some((directory, (*name).to_owned())), last)?;
        }
        directory.validate()?;
        Ok(directory)
    }
    fn from_file(
        file: File,
        parent: Option<(Arc<Self>, OsString)>,
        private: bool,
    ) -> Result<Arc<Self>> {
        let m = file.metadata().map_err(failure)?;
        safe_directory(&m, private)?;
        #[cfg(test)]
        let faults = parent.as_ref().map_or_else(
            || Arc::new(std::sync::Mutex::new(None)),
            |(p, _)| p.faults.clone(),
        );
        Ok(Arc::new(Self {
            #[cfg(test)]
            faults,
            identity: (m.dev(), m.ino()),
            file,
            parent,
            private,
        }))
    }
    pub fn validate(&self) -> Result<()> {
        let m = self.file.metadata().map_err(failure)?;
        safe_directory(&m, self.private)?;
        if (m.dev(), m.ino()) != self.identity || m.nlink() == 0 {
            return Err(Error::Corrupt);
        }
        if let Some((parent, name)) = &self.parent {
            parent.validate()?;
            let actual =
                fs::statat(&parent.file, name, AtFlags::SYMLINK_NOFOLLOW).map_err(errno)?;
            if actual.st_dev != self.identity.0
                || actual.st_ino != self.identity.1
                || fs::FileType::from_raw_mode(actual.st_mode) != fs::FileType::Directory
            {
                return Err(Error::Corrupt);
            }
        }
        Ok(())
    }
    pub fn child(self: &Arc<Self>, name: &str, create: bool) -> Result<Arc<Self>> {
        name_valid(name)?;
        self.validate()?;
        if create {
            fs::mkdirat(&self.file, name, Mode::RWXU).map_err(errno)?;
            self.sync()?;
        }
        let file = File::from(
            fs::openat(
                &self.file,
                name,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                Mode::empty(),
            )
            .map_err(errno)?,
        );
        let result = Self::from_file(file, Some((Arc::clone(self), name.into())), true)?;
        result.validate()?;
        Ok(result)
    }
    pub fn names(&self, maximum: usize) -> Result<Vec<String>> {
        self.validate()?;
        let reader = fs::Dir::read_from(&self.file).map_err(errno)?;
        let mut result = Vec::new();
        for entry in reader {
            let entry = entry.map_err(errno)?;
            let name = entry.file_name().to_bytes();
            if name == b"." || name == b".." {
                continue;
            }
            if result.len() == maximum || name.len() > 128 {
                return Err(Error::Capacity);
            }
            let name = std::str::from_utf8(name).map_err(|_| Error::Corrupt)?;
            name_valid(name)?;
            result.push(name.to_owned());
        }
        self.validate()?;
        Ok(result)
    }
    pub fn present(&self, name: &str) -> Result<bool> {
        name_valid(name)?;
        self.validate()?;
        match fs::statat(&self.file, name, AtFlags::SYMLINK_NOFOLLOW) {
            Ok(_) => Ok(true),
            Err(rustix::io::Errno::NOENT) => Ok(false),
            Err(e) => Err(errno(e)),
        }
    }
    pub fn open_file(&self, name: &str, write: bool, create: bool, maximum: u64) -> Result<File> {
        name_valid(name)?;
        self.validate()?;
        let mut flags = OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC;
        flags |= if write { OFlags::RDWR } else { OFlags::RDONLY };
        if create {
            flags |= OFlags::CREATE | OFlags::EXCL;
        }
        let file = File::from(
            fs::openat(&self.file, name, flags, Mode::RUSR | Mode::WUSR).map_err(errno)?,
        );
        self.file_matches(name, &file, maximum)?;
        Ok(file)
    }
    pub fn file_matches(&self, name: &str, file: &File, maximum: u64) -> Result<()> {
        self.validate()?;
        let m = file.metadata().map_err(failure)?;
        if !m.is_file()
            || m.uid() != rustix::process::geteuid().as_raw()
            || m.mode() & 0o077 != 0
            || m.nlink() != 1
            || m.len() > maximum
        {
            return Err(Error::Corrupt);
        }
        let actual = fs::statat(&self.file, name, AtFlags::SYMLINK_NOFOLLOW).map_err(errno)?;
        if actual.st_dev != m.dev()
            || actual.st_ino != m.ino()
            || fs::FileType::from_raw_mode(actual.st_mode) != fs::FileType::RegularFile
        {
            return Err(Error::Corrupt);
        }
        Ok(())
    }
    pub fn small(&self, name: &str, maximum: usize) -> Result<Vec<u8>> {
        let mut file = self.open_file(name, false, false, maximum as u64)?;
        let before = Identity::of(&file)?;
        let mut bytes = vec![0; usize::try_from(before.size).map_err(|_| Error::Corrupt)?];
        file.read_exact(&mut bytes).map_err(failure)?;
        if file.read(&mut [0]).map_err(failure)? != 0 || Identity::of(&file)? != before {
            return Err(Error::Corrupt);
        }
        self.file_matches(name, &file, maximum as u64)?;
        Ok(bytes)
    }
    pub fn write_new(&self, name: &str, bytes: &[u8]) -> Result<()> {
        let mut file = self.open_file(name, true, true, bytes.len() as u64)?;
        file.write_all(bytes).map_err(failure)?;
        file.sync_all().map_err(failure)?;
        self.file_matches(name, &file, bytes.len() as u64)
    }
    pub fn sync(&self) -> Result<()> {
        #[cfg(test)]
        self.inject("sync")?;
        self.validate()?;
        self.file.sync_all().map_err(failure)
    }
    pub fn rename(&self, name: &str, target: &Self, new_name: &str) -> Result<()> {
        #[cfg(test)]
        self.inject("rename")?;
        name_valid(name)?;
        name_valid(new_name)?;
        self.validate()?;
        target.validate()?;
        fs::renameat_with(
            &self.file,
            name,
            &target.file,
            new_name,
            RenameFlags::NOREPLACE,
        )
        .map_err(errno)
    }
    pub fn unlink(&self, name: &str, directory: bool) -> Result<()> {
        #[cfg(test)]
        self.inject("unlink")?;
        name_valid(name)?;
        self.validate()?;
        let flags = if directory {
            AtFlags::REMOVEDIR
        } else {
            AtFlags::empty()
        };
        fs::unlinkat(&self.file, name, flags).map_err(errno)
    }
    /// Replace one verified private regular sidecar atomically. Its caller must
    /// sync this directory and retain uncertainty if that durability fence fails.
    pub(crate) fn replace(&self, source: &str, target: &str, maximum: u64) -> Result<()> {
        let source_file = self.open_file(source, false, false, maximum)?;
        if self.present(target)? {
            self.open_file(target, false, false, maximum)?;
        }
        self.file_matches(source, &source_file, maximum)?;
        fs::renameat(&self.file, source, &self.file, target).map_err(errno)
    }
}
fn safe_directory(m: &Metadata, private: bool) -> Result<()> {
    let uid = rustix::process::geteuid().as_raw();
    if !m.is_dir() || (m.uid() != uid && m.uid() != 0) {
        return Err(Error::PermissionDenied);
    }
    if private {
        if m.uid() != uid || m.mode() & 0o077 != 0 {
            return Err(Error::PermissionDenied);
        }
    } else if m.mode() & 0o022 != 0 && !(m.uid() == 0 && m.mode() & 0o1000 != 0) {
        return Err(Error::PermissionDenied);
    }
    Ok(())
}
fn name_valid(name: &str) -> Result<()> {
    if name.is_empty()
        || name.len() > 128
        || name == "."
        || name == ".."
        || name.bytes().any(|b| b == b'/' || b == b'\\' || b == 0)
    {
        return Err(Error::Corrupt);
    }
    Ok(())
}
#[expect(
    clippy::needless_pass_by_value,
    reason = "map_err consumes the filesystem error; retain only its typed classification"
)]
pub(super) fn failure(error: std::io::Error) -> Error {
    match error.kind() {
        std::io::ErrorKind::NotFound => Error::NotFound,
        std::io::ErrorKind::UnexpectedEof => Error::Corrupt,
        std::io::ErrorKind::WouldBlock => Error::Busy,
        _ => Error::Unavailable,
    }
}
fn errno(error: rustix::io::Errno) -> Error {
    match error {
        rustix::io::Errno::NOENT => Error::NotFound,
        rustix::io::Errno::EXIST | rustix::io::Errno::WOULDBLOCK => Error::Busy,
        rustix::io::Errno::LOOP | rustix::io::Errno::NOTDIR => Error::Corrupt,
        rustix::io::Errno::ACCESS | rustix::io::Errno::PERM => Error::PermissionDenied,
        _ => Error::Unavailable,
    }
}

#[cfg(test)]
impl Directory {
    pub fn fail_after(&self, operation: &'static str, skip: usize) {
        *self.faults.lock().unwrap() = Some(Fault { operation, skip });
    }
    fn inject(&self, operation: &str) -> Result<()> {
        let mut fault = self.faults.lock().unwrap();
        if let Some(value) = fault.as_mut().filter(|f| f.operation == operation) {
            if value.skip == 0 {
                *fault = None;
                return Err(Error::Unavailable);
            }
            value.skip -= 1;
        }
        Ok(())
    }
}
