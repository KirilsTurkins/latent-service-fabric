//! Private fixed observation-FD boundary for the selected trusted Linux image.
//!
//! This does not authenticate a boot image, mint a provider grant or reserve
//! budget. Its sole caller must retain the original admitted resource/precharge.
//! The original device is the protected root-owned /dev/lsf-stream-factory in
//! that selected image; hostile privileged replacement of the trusted kernel
//! or its protected device namespace is outside this bootstrap contract.
#![deny(unsafe_code)]

#[cfg(unix)]
use std::{fs::File, io, os::fd::OwnedFd};

/// Mint exactly one private readonly observation descriptor from the protected
/// original file. No caller-supplied opcode, flags, pointer, cost or credentials.
/// The native owner must prepay BEFORE entry and quarantine on every uncertainty.
#[cfg(unix)]
pub fn mint(factory: &File) -> io::Result<OwnedFd> {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    {
        validate_original(factory)?;
        ffi::mint(factory)
    }
    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    {
        let _ = factory;
        Err(io::ErrorKind::Unsupported.into())
    }
}

// Non-Unix consumers never link this target-only leaf: their provider rejects
// Unsupported without exposing a fake OwnedFd type or an alternate syscall.
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn validate_original(factory: &File) -> io::Result<()> {
    use std::os::unix::fs::{FileTypeExt, MetadataExt};
    let failure = || io::Error::from(io::ErrorKind::PermissionDenied);
    let original = factory.metadata()?;
    if !original.file_type().is_char_device()
        || original.uid() != 0
        || original.mode() & 0o777 != 0o600
    {
        return Err(failure());
    }
    for name in ["/", "/dev"] {
        let parent = std::fs::symlink_metadata(name)?;
        if !parent.file_type().is_dir() || parent.uid() != 0 || parent.mode() & 0o022 != 0 {
            return Err(failure());
        }
    }
    let named = std::fs::symlink_metadata("/dev/lsf-stream-factory")?;
    if !named.file_type().is_char_device()
        || named.uid() != 0
        || named.mode() & 0o777 != 0o600
        || (named.dev(), named.ino(), named.rdev())
            != (original.dev(), original.ino(), original.rdev())
    {
        return Err(failure());
    }
    Ok(())
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[allow(unsafe_code)]
mod ffi {
    use super::{io, File, OwnedFd};
    use rustix::ioctl::{self, Ioctl, IoctlOutput, Opcode};
    use std::{ffi::c_void, os::fd::FromRawFd};

    struct Mint;

    // SAFETY: The selected original factory has one closed _IO(0xb7,1) ABI.
    // It requires argument zero, never accesses userspace memory, and returns
    // ONLY a newly fd_install'ed readonly/CLOEXEC file or negative errno. All
    // errors precede installation; success is a c_int fd, including valid0.
    unsafe impl Ioctl for Mint {
        type Output = OwnedFd;
        const IS_MUTATING: bool = true;

        fn opcode(&self) -> Opcode {
            ioctl::opcode::none(0xb7, 1)
        }

        fn as_ptr(&mut self) -> *mut c_void {
            std::ptr::null_mut()
        }

        unsafe fn output_from_ptr(out: IoctlOutput, _: *mut c_void) -> rustix::io::Result<OwnedFd> {
            // SAFETY: rustix dispatches errno before this callback. The exact
            // driver success returns a fresh installed descriptor as c_int:
            // no cast/truncation, >0 predicate, fallible gap or raw-FD escape.
            Ok(unsafe { OwnedFd::from_raw_fd(out) })
        }
    }

    pub(super) fn mint(factory: &File) -> io::Result<OwnedFd> {
        // SAFETY: validate_original retained an immutable borrow of the exact
        // protected device. The trusted selected kernel implements Mint; its
        // own actor/birth checks precede every allocation and fd installation.
        unsafe { ioctl::ioctl(factory, Mint) }
            .map_err(|error| io::Error::from_raw_os_error(error.raw_os_error()))
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        use std::os::fd::{AsRawFd, IntoRawFd};

        #[test]
        fn fixed_descriptor_boundary_refuses_foreign_and_preserves_actual_ownership() {
            let original = tempfile::NamedTempFile::new().unwrap();
            let rejected = super::super::mint(original.as_file()).unwrap_err();
            assert_eq!(rejected.kind(), io::ErrorKind::PermissionDenied);
            let returned = original.reopen().unwrap().into_raw_fd();
            // SAFETY: this real descriptor was just transferred out of its
            // sole File owner, exactly the ownership shape of syscall success.
            // This tests adoption/drop, not custom-kernel mint or retirement.
            let adopted = unsafe { Mint::output_from_ptr(returned, std::ptr::null_mut()) }.unwrap();
            assert_eq!(adopted.as_raw_fd(), returned);
            let failed: io::Result<()> = {
                let _owned = adopted;
                Err(io::ErrorKind::TimedOut.into())
            };
            assert_eq!(failed.unwrap_err().kind(), io::ErrorKind::TimedOut);
            assert!(std::fs::read_link(format!("/proc/self/fd/{returned}")).is_err());
            assert!(original.as_file().metadata().unwrap().is_file());
        }
    }
}
