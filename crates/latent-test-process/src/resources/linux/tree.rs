use std::collections::{BTreeSet, VecDeque};
use std::io;
use std::path::Path;

use super::{files, parse, read_identity, same_identity, ProcessIdentity, Reads};

pub(super) fn descendants(
    proc_root: &Path,
    parent: ProcessIdentity,
    tasks: &[u32],
    reads: &mut Reads,
) -> io::Result<Vec<ProcessIdentity>> {
    let mut result = Vec::new();
    let mut seen = BTreeSet::from([parent.process_id]);
    let mut pending = VecDeque::new();
    add_children(proc_root, parent, tasks, 1, reads, &mut seen, &mut pending)?;
    while let Some((pid, parent, depth)) = pending.pop_front() {
        let path = proc_root.join(pid.to_string());
        let identity = related_child(proc_root, pid, parent, reads)?;
        if identity.process_id != pid {
            return Err(io::Error::other("descendant identity mismatch"));
        }
        let tasks = files::numeric_entries(&path.join("task"), reads.limits.maximum_tasks)?;
        add_children(
            proc_root,
            identity,
            &tasks,
            depth + 1,
            reads,
            &mut seen,
            &mut pending,
        )?;
        same_identity(related_child(proc_root, pid, parent, reads)?, identity)?;
        result.push(identity);
    }
    result.sort_unstable();
    Ok(result)
}

fn add_children(
    proc_root: &Path,
    parent: ProcessIdentity,
    tasks: &[u32],
    depth: usize,
    reads: &mut Reads,
    seen: &mut BTreeSet<u32>,
    pending: &mut VecDeque<(u32, ProcessIdentity, usize)>,
) -> io::Result<()> {
    let maximum = reads.limits.maximum_descendants;
    for task in tasks {
        let path = proc_root
            .join(parent.process_id.to_string())
            .join("task")
            .join(task.to_string())
            .join("children");
        let bytes = reads.file(&path, reads.limits.maximum_file_bytes)?;
        for child in parse::children(&bytes, maximum)? {
            if child == 0 {
                return Err(io::Error::other("invalid descendant identity"));
            }
            if seen.contains(&child) {
                continue;
            }
            if seen.len() > maximum || depth > reads.limits.maximum_descendant_depth {
                return Err(files::limit());
            }
            seen.insert(child);
            pending.push_back((child, parent, depth));
        }
    }
    Ok(())
}

fn related_child(
    proc_root: &Path,
    pid: u32,
    parent: ProcessIdentity,
    reads: &mut Reads,
) -> io::Result<ProcessIdentity> {
    // A children file lists PIDs without pinning them. Validate the relation
    // and the expected parent's identity before and after walking this child,
    // so a reused foreign PID cannot become descendant resource evidence.
    let bytes = reads.file(
        &proc_root.join(pid.to_string()).join("stat"),
        reads.limits.maximum_file_bytes,
    )?;
    let child = parse::stat(&bytes)?;
    if child.parent_process_id != parent.process_id {
        return Err(io::Error::new(
            io::ErrorKind::Interrupted,
            "child process parent relation changed",
        ));
    }
    let current_parent = read_identity(&proc_root.join(parent.process_id.to_string()), reads)?;
    if current_parent != parent {
        return Err(io::Error::new(
            io::ErrorKind::Interrupted,
            "descendant parent identity changed",
        ));
    }
    Ok(child.identity)
}
