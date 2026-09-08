mod files;
#[cfg(test)]
mod tests;
mod tree;

use std::collections::BTreeSet;
use std::io;
use std::path::{Path, PathBuf};

use super::{parse, ChildProcessResources, ProbeLimits, ProcessIdentity, ProcessResources};
use files::Reads;

pub(super) fn identity(pid: u32, limits: ProbeLimits) -> io::Result<ProcessIdentity> {
    let mut reads = Reads::new(limits);
    read_identity(&root(pid), &mut reads)
}

pub(super) fn capture(
    expected: ProcessIdentity,
    limits: ProbeLimits,
    attempt: u8,
) -> io::Result<ChildProcessResources> {
    capture_at(Path::new("/proc"), expected, limits, attempt)
}

fn capture_at(
    proc_root: &Path,
    expected: ProcessIdentity,
    limits: ProbeLimits,
    attempt: u8,
) -> io::Result<ChildProcessResources> {
    let path = proc_root.join(expected.process_id.to_string());
    let mut reads = Reads::new(limits);
    same_identity(read_identity(&path, &mut reads)?, expected)?;
    let status = reads.file(&path.join("status"), limits.maximum_file_bytes)?;
    let (rss, threads) = parse::status(&status)?;
    let tasks = files::numeric_entries(&path.join("task"), limits.maximum_tasks)?;
    let (fd_count, socket_fds, socket_inodes) = sockets(&path, &mut reads)?;
    let mut listeners = BTreeSet::new();
    for name in ["tcp", "tcp6"] {
        let bytes = reads.file(
            &path.join("net").join(name),
            limits.maximum_network_table_bytes,
        )?;
        listeners.extend(parse::listeners(
            &bytes,
            &socket_inodes,
            limits.maximum_network_rows,
        )?);
    }
    let descendants = tree::descendants(proc_root, expected, &tasks, &mut reads)?;
    let final_sockets = sockets(&path, &mut reads)?;
    if final_sockets.0 != fd_count
        || final_sockets.1 != socket_fds
        || final_sockets.2 != socket_inodes
    {
        return Err(io::Error::new(
            io::ErrorKind::Interrupted,
            "child socket ownership changed during observation",
        ));
    }
    same_identity(read_identity(&path, &mut reads)?, expected)?;
    let final_tasks = files::numeric_entries(&path.join("task"), limits.maximum_tasks)?;
    if tasks != final_tasks || threads != count(tasks.len()) {
        return Err(io::Error::new(
            io::ErrorKind::Interrupted,
            "child task observation changed",
        ));
    }
    Ok(ChildProcessResources {
        identity: expected,
        process: ProcessResources {
            process_id: expected.process_id,
            resident_memory_bytes: Some(rss),
            thread_count: Some(threads),
            open_file_descriptors: Some(fd_count),
            socket_count: Some(socket_fds),
        },
        task_count: count(tasks.len()),
        unique_socket_count: count(socket_inodes.len()),
        listening_tcp_socket_count: count(listeners.len()),
        descendants,
        sample_attempts: attempt,
    })
}

fn sockets(path: &Path, reads: &mut Reads) -> io::Result<(u64, u64, BTreeSet<u64>)> {
    let fd_path = path.join("fd");
    let entries = files::numeric_entries(&fd_path, reads.limits.maximum_file_descriptors)?;
    let mut sockets = BTreeSet::new();
    let mut socket_fds = 0_u64;
    for fd in &entries {
        let link = std::fs::read_link(fd_path.join(fd.to_string()))?;
        let bytes = link.as_os_str().as_encoded_bytes();
        reads.charge(bytes.len())?;
        if let Some(inode) = parse::socket_inode(bytes)? {
            sockets.insert(inode);
            socket_fds += 1;
        }
    }
    if files::numeric_entries(&fd_path, reads.limits.maximum_file_descriptors)? != entries {
        return Err(io::Error::new(
            io::ErrorKind::Interrupted,
            "child file descriptor observation changed",
        ));
    }
    Ok((count(entries.len()), socket_fds, sockets))
}

fn read_identity(path: &Path, reads: &mut Reads) -> io::Result<ProcessIdentity> {
    parse::identity(&reads.file(&path.join("stat"), reads.limits.maximum_file_bytes)?)
}

fn same_identity(actual: ProcessIdentity, expected: ProcessIdentity) -> io::Result<()> {
    if actual == expected {
        Ok(())
    } else {
        Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "child process identity changed",
        ))
    }
}

fn root(pid: u32) -> PathBuf {
    Path::new("/proc").join(pid.to_string())
}

fn count(value: usize) -> u64 {
    u64::try_from(value).unwrap_or(u64::MAX)
}
