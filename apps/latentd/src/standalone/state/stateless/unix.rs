use std::ffi::OsString;
use std::fs::File;
use std::os::unix::fs::MetadataExt;
use std::path::{Component, Path};

use latent_core::{native_capacity::NativeReservation, PlatformError};
use rustix::fs::{AtFlags, Mode, OFlags};

use super::{unavailable, MAXIMUM_COMPONENTS, STATE_DIRECTORY};

struct Anchor {
    file: File,
    name: OsString,
    identity: (u64, u64),
}

struct Chain {
    anchors: Vec<Anchor>,
    missing: Option<OsString>,
}

pub(super) fn observe(
    path: &Path,
    original: &NativeReservation,
    before_native_retirement: impl FnOnce(),
) -> Result<bool, PlatformError> {
    let chain = Chain::open(path, original)?;
    chain.check(original)?;
    let present = chain.exists(original)?;
    before_native_retirement();
    // Actual anchored directory descriptors remain owned until this final
    // check and worker-local destruction, including a detached waiter.
    chain.check(original)?;
    let present = present || chain.exists(original)?;
    drop(chain);
    Ok(present)
}

impl Chain {
    fn open(path: &Path, original: &NativeReservation) -> Result<Self, PlatformError> {
        live(original)?;
        let mut anchors = Vec::with_capacity(MAXIMUM_COMPONENTS + 1);
        let file =
            File::from(rustix::fs::open("/", flags(), Mode::empty()).map_err(|_| unavailable())?);
        let metadata = file.metadata().map_err(|_| unavailable())?;
        anchors.push(Anchor {
            file,
            name: OsString::new(),
            identity: (metadata.dev(), metadata.ino()),
        });
        let mut missing = None;
        for component in path.components() {
            let name = match component {
                Component::RootDir => continue,
                Component::Normal(name) => name,
                _ => return Err(unavailable()),
            };
            live(original)?;
            let file = match rustix::fs::openat(
                &anchors.last().expect("private root anchor").file,
                name,
                flags(),
                Mode::empty(),
            ) {
                Ok(file) => File::from(file),
                Err(rustix::io::Errno::NOENT) => {
                    missing = Some(name.to_os_string());
                    break;
                }
                Err(_) => return Err(unavailable()),
            };
            let metadata = file.metadata().map_err(|_| unavailable())?;
            if !metadata.is_dir() {
                return Err(unavailable());
            }
            anchors.push(Anchor {
                file,
                name: name.to_os_string(),
                identity: (metadata.dev(), metadata.ino()),
            });
        }
        Ok(Self { anchors, missing })
    }

    fn check(&self, original: &NativeReservation) -> Result<(), PlatformError> {
        for (index, anchor) in self.anchors.iter().enumerate() {
            live(original)?;
            let metadata = anchor.file.metadata().map_err(|_| unavailable())?;
            if !metadata.is_dir()
                || metadata.nlink() == 0
                || (metadata.dev(), metadata.ino()) != anchor.identity
            {
                return Err(unavailable());
            }
            if index != 0 {
                let named = rustix::fs::statat(
                    &self.anchors[index - 1].file,
                    &anchor.name,
                    AtFlags::SYMLINK_NOFOLLOW,
                )
                .map_err(|_| unavailable())?;
                if named_identity(&named) != anchor.identity {
                    return Err(unavailable());
                }
            }
        }
        Ok(())
    }

    fn exists(&self, original: &NativeReservation) -> Result<bool, PlatformError> {
        live(original)?;
        let name = self
            .missing
            .as_deref()
            .unwrap_or_else(|| std::ffi::OsStr::new(STATE_DIRECTORY));
        match rustix::fs::statat(
            &self.anchors.last().expect("retained private anchor").file,
            name,
            AtFlags::SYMLINK_NOFOLLOW,
        ) {
            Ok(_) => Ok(true),
            Err(rustix::io::Errno::NOENT) => Ok(false),
            Err(_) => Err(unavailable()),
        }
    }
}

fn flags() -> OFlags {
    OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK
}

fn live(original: &NativeReservation) -> Result<(), PlatformError> {
    original.with_live(|| ()).map_err(|_| unavailable())
}

#[allow(
    clippy::unnecessary_cast,
    clippy::cast_sign_loss,
    reason = "Unix dev_t and ino_t widths vary; preserve the same native identity bits as MetadataExt"
)]
fn named_identity(named: &rustix::fs::Stat) -> (u64, u64) {
    (named.st_dev as u64, named.st_ino as u64)
}
