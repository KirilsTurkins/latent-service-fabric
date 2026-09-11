//! Bounded in-process reads; never launch a resource observer child.

use std::collections::{BTreeMap, BTreeSet};
use std::fs::File;
use std::io::Read;
use std::path::{Component, Path, PathBuf};
use std::time::Instant;

use serde::Serialize;
use serde_json::{json, Value};

const RAW_LIMIT: u64 = 64 * 1024;
const MAX_FDS: usize = 1024;

#[derive(Serialize)]
struct Raw {
    value: Option<String>,
    unavailable_reason: Option<&'static str>,
}

impl Raw {
    fn unavailable(reason: &'static str) -> Self {
        Self {
            value: None,
            unavailable_reason: Some(reason),
        }
    }
    fn value(value: String) -> Self {
        Self {
            value: Some(value),
            unavailable_reason: None,
        }
    }
}

fn read(path: &Path) -> Raw {
    let result = (|| {
        let file = File::open(path).map_err(|_| "open-failed")?;
        let mut bytes = Vec::new();
        file.take(RAW_LIMIT + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| "read-failed")?;
        if bytes.len() > usize::try_from(RAW_LIMIT).expect("fixed bound") {
            return Err("byte-limit");
        }
        String::from_utf8(bytes).map_err(|_| "non-utf8")
    })();
    match result {
        Ok(value) => Raw::value(value),
        Err(reason) => Raw::unavailable(reason),
    }
}

fn link(path: &Path) -> Raw {
    match std::fs::read_link(path) {
        Ok(value) => match value.to_str() {
            Some(value) if value.len() <= 4096 => Raw::value(value.to_owned()),
            _ => Raw::unavailable("link-limit-or-encoding"),
        },
        Err(_) => Raw::unavailable("read-link-failed"),
    }
}

fn ticks(raw: &Raw) -> Option<&str> {
    let value = raw.value.as_deref()?;
    let (_, tail) = value.rsplit_once(") ")?;
    let token = tail.split_ascii_whitespace().nth(19)?;
    token.parse::<u64>().ok()?;
    Some(token)
}

fn status_number(raw: &Raw, name: &str, kib: bool) -> Option<String> {
    let line = raw
        .value
        .as_deref()?
        .lines()
        .find_map(|line| line.strip_prefix(name))?;
    let mut parts = line.split_ascii_whitespace();
    let value = parts.next()?.parse::<u64>().ok()?;
    if kib && parts.next() != Some("kB") {
        return None;
    }
    if parts.next().is_some() {
        return None;
    }
    Some(if kib { value.checked_mul(1024)? } else { value }.to_string())
}

fn sockets(root: &Path) -> std::result::Result<(usize, BTreeMap<String, String>), &'static str> {
    let entries = std::fs::read_dir(root.join("fd")).map_err(|_| "fd-directory")?;
    let mut count = 0;
    let mut sockets = BTreeMap::new();
    for entry in entries {
        let entry = entry.map_err(|_| "fd-entry")?;
        count += 1;
        if count > MAX_FDS {
            return Err("fd-count-limit");
        }
        let name = entry.file_name().into_string().map_err(|_| "fd-name")?;
        name.parse::<u32>().map_err(|_| "fd-name")?;
        let target = std::fs::read_link(entry.path()).map_err(|_| "fd-raced-or-unavailable")?;
        let target = target.to_str().ok_or("fd-target-encoding")?;
        if let Some(inode) = target
            .strip_prefix("socket:[")
            .and_then(|v| v.strip_suffix(']'))
        {
            inode.parse::<u64>().map_err(|_| "fd-socket-inode")?;
            sockets.insert(name, inode.to_owned());
        }
    }
    Ok((count, sockets))
}

fn listener_rows(tables: &[&Raw], sockets: &BTreeMap<String, String>) -> Option<Vec<String>> {
    let inodes = sockets
        .values()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    let mut rows = Vec::new();
    for table in tables {
        for line in table.value.as_deref()?.lines().skip(1) {
            let values = line.split_ascii_whitespace().collect::<Vec<_>>();
            if values.len() < 10 {
                return None;
            }
            if values[3] == "0A" && inodes.contains(values[9]) {
                rows.push(line.to_owned());
            }
        }
    }
    Some(rows)
}

fn process(pid: u32, origin: Instant) -> Value {
    let started = origin.elapsed().as_nanos().to_string();
    let root = PathBuf::from(format!("/proc/{pid}"));
    let before = read(&root.join("stat"));
    let status = read(&root.join("status"));
    let tcp = read(&root.join("net/tcp"));
    let tcp6 = read(&root.join("net/tcp6"));
    let fds = sockets(&root);
    let (fd_count, socket_descriptors, fd_reason, listeners) = match fds {
        Ok((count, sockets)) => {
            let listeners = listener_rows(&[&tcp, &tcp6], &sockets);
            (Some(count.to_string()), Some(sockets), None, listeners)
        }
        Err(reason) => (None, None, Some(reason), None),
    };
    let namespaces = ["pid", "mnt", "net", "user"]
        .into_iter()
        .map(|name| (name, link(&root.join("ns").join(name))))
        .collect::<BTreeMap<_, _>>();
    let cgroup = read(&root.join("cgroup"));
    let after = read(&root.join("stat"));
    let identity_stable = ticks(&before).is_some() && ticks(&before) == ticks(&after);
    json!({"pid":pid,"started_nanos":started,"finished_nanos":origin.elapsed().as_nanos().to_string(),
        "identity_stable":identity_stable,"start_time_ticks":ticks(&before),"start_time_ticks_after":ticks(&after),
        "stat":before,"stat_after":after,"status":status,
        "rss_bytes":status_number(&status,"VmRSS:",true),"threads":status_number(&status,"Threads:",false),
        "rss_unavailable_reason":if status_number(&status,"VmRSS:",true).is_none(){Some("status-field-unavailable")}else{None},
        "threads_unavailable_reason":if status_number(&status,"Threads:",false).is_none(){Some("status-field-unavailable")}else{None},
        "fd_count":fd_count,"socket_descriptors":socket_descriptors,"fd_unavailable_reason":fd_reason,
        "tcp":tcp,"tcp6":tcp6,"listener_rows":listeners,
        "listeners_unavailable_reason":if listeners.is_none(){Some("socket-table-or-fd-unavailable")}else{None},
        "namespaces":namespaces,"cgroup":cgroup})
}

fn cgroup_directory(membership: &Raw, mounts: &Raw) -> Option<PathBuf> {
    let path = membership
        .value
        .as_deref()?
        .lines()
        .find_map(|line| line.strip_prefix("0::"))?;
    let path = Path::new(path);
    if !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, Component::ParentDir))
    {
        return None;
    }
    for line in mounts.value.as_deref()?.lines() {
        let (head, tail) = line.split_once(" - ")?;
        if tail.split_ascii_whitespace().next() != Some("cgroup2") {
            continue;
        }
        let fields = head.split_ascii_whitespace().collect::<Vec<_>>();
        let root = Path::new(*fields.get(3)?);
        let mount = Path::new(*fields.get(4)?);
        // Escaped or unrelated mounts are unavailable rather than guessed.
        if root.as_os_str().to_str()?.contains('\\') || mount != Path::new("/sys/fs/cgroup") {
            continue;
        }
        if let Ok(relative) = path.strip_prefix(root) {
            return Some(mount.join(relative));
        }
    }
    None
}

fn cgroup(origin: Instant) -> Value {
    let started = origin.elapsed().as_nanos().to_string();
    let membership = read(Path::new("/proc/self/cgroup"));
    let mountinfo = read(Path::new("/proc/self/mountinfo"));
    let directory = cgroup_directory(&membership, &mountinfo);
    let files = [
        "cpu.max",
        "cpu.stat",
        "cpu.pressure",
        "cpuset.cpus.effective",
        "memory.max",
        "memory.current",
        "memory.peak",
        "memory.events",
        "memory.swap.max",
        "memory.swap.current",
        "memory.pressure",
        "pids.max",
        "pids.current",
        "cgroup.procs",
    ]
    .into_iter()
    .map(|name| {
        (
            name,
            directory.as_ref().map_or_else(
                || Raw::unavailable("cgroup-v2-mapping-unavailable"),
                |root| read(&root.join(name)),
            ),
        )
    })
    .collect::<BTreeMap<_, _>>();
    json!({"started_nanos":started,"finished_nanos":origin.elapsed().as_nanos().to_string(),
        "membership":membership,"mountinfo":mountinfo,"directory":directory,
        "mapping_unavailable_reason":if directory.is_none(){Some("cgroup-v2-mapping-unavailable")}else{None},"files":files})
}

pub(super) fn snapshot(child: u32, index: u32, origin: Instant) -> Value {
    let started = origin.elapsed().as_nanos().to_string();
    let wrapper = process(std::process::id(), origin);
    let child = process(child, origin);
    let cgroup = cgroup(origin);
    json!({"snapshot_index":index,"started_nanos":started,"finished_nanos":origin.elapsed().as_nanos().to_string(),
        "wrapper":wrapper,"child":child,"cgroup":cgroup})
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[cfg(target_os = "linux")]
    fn stat_start_time_uses_last_parenthesis_and_mapping_does_not_escape_mount() {
        let suffix = (0..20)
            .map(|index| index.to_string())
            .collect::<Vec<_>>()
            .join(" ");
        let raw = Raw::value(format!("1 (name ) with spaces) {suffix}"));
        assert_eq!(ticks(&raw), Some("19"));
        let mounts = Raw::value("1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n".into());
        assert_eq!(
            cgroup_directory(&Raw::value("0::/owned\n".into()), &mounts),
            Some(PathBuf::from("/sys/fs/cgroup/owned"))
        );
        assert!(cgroup_directory(&Raw::value("0::/../foreign\n".into()), &mounts).is_none());
    }
}
