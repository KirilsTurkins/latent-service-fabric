//! A serial real-worker case: only this owned descriptor becomes inheritable.

use std::fs::{File, OpenOptions};
use std::io::{Read, Seek, Write};
use std::os::fd::AsRawFd;
use std::time::Duration;

use latent_wasmtime::AotResourceSnapshot;
use rustix::io::{fcntl_dupfd_cloexec, fcntl_getfd, fcntl_setfd, FdFlags};

use super::support::{self, Directory, Fixture};

pub fn run() {
    let directory = Directory::new();
    let mut original = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(directory.path().join("parent-owned"))
        .unwrap();
    original.write_all(b"parent-owned-descriptor").unwrap();
    // Exercise descriptors above the child's lowered 16-FD ceiling as well as
    // keeping a genuinely owned file alive in this process throughout the job.
    let mut inherited = File::from(fcntl_dupfd_cloexec(&original, 64).unwrap());
    assert!(inherited.as_raw_fd() >= 64);
    fcntl_setfd(&inherited, FdFlags::empty()).unwrap();
    assert!(fcntl_getfd(&inherited).unwrap().is_empty());

    let fixture = Fixture::tiny();
    let limits = support::limits();
    assert!(u64::try_from(inherited.as_raw_fd()).unwrap() > limits.sandbox.maximum_fds);
    let compiler = support::compiler(limits);
    let output = compiler
        .reserve(fixture.source(), fixture.release())
        .unwrap()
        .run()
        .expect("real compiler must clean inherited non-stdio descriptors");
    assert!(!output.output().is_empty());
    support::authority(limits)
        .verify(&output, output.compatibility())
        .unwrap();

    // Child close/re-exec must not close the parent's owner or alter its flags.
    assert!(fcntl_getfd(&inherited).unwrap().is_empty());
    inherited.rewind().unwrap();
    let mut sentinel = [0; b"parent-owned-descriptor".len()];
    inherited.read_exact(&mut sentinel).unwrap();
    assert_eq!(&sentinel, b"parent-owned-descriptor");
    original.rewind().unwrap();
    original.read_exact(&mut sentinel).unwrap();
    assert_eq!(&sentinel, b"parent-owned-descriptor");
    drop(output);
    compiler.shutdown(Duration::from_secs(1)).unwrap();
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
}
