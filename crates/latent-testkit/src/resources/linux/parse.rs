use std::collections::BTreeSet;
use std::io;

use super::ProcessIdentity;

pub(super) fn identity(bytes: &[u8]) -> io::Result<ProcessIdentity> {
    Ok(stat(bytes)?.identity)
}

pub(super) struct ProcessStat {
    pub identity: ProcessIdentity,
    pub parent_process_id: u32,
}

pub(super) fn stat(bytes: &[u8]) -> io::Result<ProcessStat> {
    let open = bytes
        .iter()
        .position(|byte| *byte == b'(')
        .ok_or_else(invalid)?;
    let close = bytes
        .iter()
        .rposition(|byte| *byte == b')')
        .filter(|close| *close > open)
        .ok_or_else(invalid)?;
    let process_id = text(&bytes[..open])?
        .trim()
        .parse::<u32>()
        .map_err(|_| invalid())?;
    // After comm the first token is field 3 (state), followed by field 4
    // (parent PID). After consuming that parent field, starttime is index 17.
    let mut fields = text(&bytes[close + 1..])?.split_ascii_whitespace();
    let parent_process_id = fields
        .nth(1)
        .ok_or_else(invalid)?
        .parse::<u32>()
        .map_err(|_| invalid())?;
    let start_time_ticks = fields
        .nth(17)
        .ok_or_else(invalid)?
        .parse::<u64>()
        .map_err(|_| invalid())?;
    Ok(ProcessStat {
        identity: ProcessIdentity {
            process_id,
            start_time_ticks,
        },
        parent_process_id,
    })
}

pub(super) fn status(bytes: &[u8]) -> io::Result<(u64, u64)> {
    let mut rss = None;
    let mut threads = None;
    for line in text(bytes)?.lines() {
        if let Some(value) = line.strip_prefix("VmRSS:") {
            let mut fields = value.split_ascii_whitespace();
            let kib = unsigned(fields.next().ok_or_else(invalid)?)?;
            if rss.is_some() || fields.next() != Some("kB") || fields.next().is_some() {
                return Err(invalid());
            }
            rss = Some(kib.checked_mul(1024).ok_or_else(invalid)?);
        }
        if let Some(value) = line.strip_prefix("Threads:") {
            if threads.is_some() {
                return Err(invalid());
            }
            threads = Some(unsigned(value.trim())?);
        }
    }
    Ok((
        rss.ok_or_else(invalid)?,
        threads.filter(|value| *value > 0).ok_or_else(invalid)?,
    ))
}

pub(super) fn socket_inode(bytes: &[u8]) -> io::Result<Option<u64>> {
    let Some(inode) = bytes.strip_prefix(b"socket:[") else {
        return Ok(None);
    };
    let inode = inode.strip_suffix(b"]").ok_or_else(invalid)?;
    Ok(Some(unsigned(text(inode)?)?))
}

pub(super) fn listeners(
    bytes: &[u8],
    owned: &BTreeSet<u64>,
    maximum_rows: usize,
) -> io::Result<BTreeSet<u64>> {
    let mut lines = text(bytes)?.lines();
    let header = lines.next().ok_or_else(invalid)?;
    if !header.contains("local_address") || !header.contains("inode") {
        return Err(invalid());
    }
    let mut listeners = BTreeSet::new();
    for (index, line) in lines.enumerate() {
        if index >= maximum_rows {
            return Err(limit());
        }
        let mut fields = line.split_ascii_whitespace();
        let state = fields.nth(3).ok_or_else(invalid)?;
        let inode = unsigned(fields.nth(5).ok_or_else(invalid)?)?;
        if state == "0A" && owned.contains(&inode) {
            listeners.insert(inode);
        }
    }
    Ok(listeners)
}

pub(super) fn children(bytes: &[u8], maximum: usize) -> io::Result<Vec<u32>> {
    let mut result = Vec::new();
    for value in text(bytes)?.split_ascii_whitespace() {
        if result.len() >= maximum {
            return Err(limit());
        }
        result.push(value.parse::<u32>().map_err(|_| invalid())?);
    }
    Ok(result)
}

fn unsigned(value: &str) -> io::Result<u64> {
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(invalid());
    }
    value.parse().map_err(|_| invalid())
}

fn text(bytes: &[u8]) -> io::Result<&str> {
    std::str::from_utf8(bytes).map_err(|_| invalid())
}

fn invalid() -> io::Error {
    io::Error::new(
        io::ErrorKind::InvalidData,
        "invalid child process resource data",
    )
}

fn limit() -> io::Error {
    io::Error::new(
        io::ErrorKind::InvalidData,
        "child resource probe limit exceeded",
    )
}

#[cfg(test)]
#[path = "parse/tests.rs"]
mod tests;
