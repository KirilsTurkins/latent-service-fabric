//! Read only a typed content digest below the catalog's shared blob directory.
//! The caller supplies a fresh `WebSelection`; a digest or this handle is not authority.
use latent_artifacts::DirectoryArtifactRepository;
use latent_core::ArtifactBlobDigest;

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod platform {
    use super::{ArtifactBlobDigest, DirectoryArtifactRepository};
    use rustix::fs::{Mode, OFlags};
    use std::{fs::File, io::Read, path::Component};

    pub(super) struct Source(File);

    impl Source {
        pub(super) fn new(repository: &DirectoryArtifactRepository) -> Result<Self, u16> {
            // The catalog supplies its canonical absolute root. Walk it without
            // following links, then retain the actual directory, not its pathname.
            let flags = OFlags::RDONLY
                | OFlags::DIRECTORY
                | OFlags::NOFOLLOW
                | OFlags::CLOEXEC
                | OFlags::NONBLOCK;
            let mut directory =
                File::from(rustix::fs::open("/", flags, Mode::empty()).map_err(|_| 503u16)?);
            if !repository.root().is_absolute() {
                return Err(503);
            }
            for component in repository.root().components() {
                match component {
                    Component::RootDir => (),
                    Component::Normal(name) => {
                        directory = File::from(
                            rustix::fs::openat(&directory, name, flags, Mode::empty())
                                .map_err(|_| 503u16)?,
                        );
                    }
                    _ => return Err(503),
                }
            }
            Ok(Self(directory))
        }

        pub(super) fn read(
            &self,
            digest: &ArtifactBlobDigest,
            output: &mut [u8],
        ) -> Result<(), u16> {
            let flags = OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK;
            let directory =
                rustix::fs::openat(&self.0, "blobs", flags | OFlags::DIRECTORY, Mode::empty())
                    .map_err(|_| 502u16)?;
            // Catalog content is hard-linked into committed publications. Links
            // to regular files are expected; symbolic links and special files are not.
            let name = digest.as_str().strip_prefix("sha256:").ok_or(502u16)?;
            let mut file = File::from(
                rustix::fs::openat(&directory, name, flags, Mode::empty()).map_err(|_| 502u16)?,
            );
            let before = file.metadata().map_err(|_| 502u16)?;
            if !before.is_file() || before.len() != output.len() as u64 {
                return Err(502);
            }
            file.read_exact(output).map_err(|_| 502u16)?;
            if file.read(&mut [0]).map_err(|_| 502u16)? != 0 {
                return Err(502);
            }
            let after = file.metadata().map_err(|_| 502u16)?;
            if !after.is_file() || after.len() != before.len() {
                return Err(502);
            }
            Ok(())
        }
    }
}

#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
mod platform {
    use super::{ArtifactBlobDigest, DirectoryArtifactRepository};
    pub(super) struct Source;
    impl Source {
        pub(super) fn new(_: &DirectoryArtifactRepository) -> Result<Self, u16> {
            Err(503)
        }
        pub(super) fn read(&self, _: &ArtifactBlobDigest, _: &mut [u8]) -> Result<(), u16> {
            Err(503)
        }
    }
}

pub(super) struct Source(platform::Source);
impl Source {
    pub(super) fn new(repository: &DirectoryArtifactRepository) -> Result<Self, u16> {
        platform::Source::new(repository).map(Self)
    }
    pub(super) fn read(&self, digest: &ArtifactBlobDigest, bytes: &mut [u8]) -> Result<(), u16> {
        self.0.read(digest, bytes)
    }
}
