//! Safe bounded Linux task CPU sampling. Unsupported/failed probes stay absent.

use super::model::{PreparationThreadCpu, PreparationThreadCpuInterval};

pub(super) fn interval(
    before: Option<PreparationThreadCpu>,
    after: Option<PreparationThreadCpu>,
) -> Option<PreparationThreadCpuInterval> {
    let (before, after) = (before?, after?);
    (before.identity == after.identity
        && before.user_ticks <= after.user_ticks
        && before.system_ticks <= after.system_ticks)
        .then_some(PreparationThreadCpuInterval { before, after })
}

#[cfg(not(target_os = "linux"))]
pub(super) fn sample() -> Option<PreparationThreadCpu> {
    None
}

#[cfg(target_os = "linux")]
pub(super) fn sample() -> Option<PreparationThreadCpu> {
    use std::io::Read as _;

    let mut input = std::fs::File::open("/proc/thread-self/stat").ok()?;
    let mut bytes = [0_u8; 4097];
    let mut used = 0;
    let mut interruptions = 0;
    loop {
        if used == bytes.len() {
            return None;
        }
        match input.read(&mut bytes[used..]) {
            Ok(0) => break,
            Ok(count) => used += count,
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted && interruptions < 8 => {
                interruptions += 1;
            }
            Err(_) => return None,
        }
    }
    parse(
        std::str::from_utf8(&bytes[..used]).ok()?,
        std::process::id(),
    )
}

#[cfg(any(target_os = "linux", test))]
pub(super) fn parse(input: &str, process_id: u32) -> Option<PreparationThreadCpu> {
    use super::model::PreparationThreadIdentity;

    if input.len() > 4096 {
        return None;
    }
    let (identifier, _) = input.split_once(" (")?;
    let thread_id: u32 = identifier.parse().ok()?;
    if thread_id == 0 || process_id == 0 {
        return None;
    }
    // Linux comm may contain spaces and parentheses. Fields follow the LAST ).
    let (_, fields) = input.rsplit_once(") ")?;
    let mut fields = fields.split_ascii_whitespace();
    let user_ticks = fields.nth(11)?.parse().ok()?;
    let system_ticks = fields.next()?.parse().ok()?;
    let start_time_ticks = fields.nth(6)?.parse().ok()?;
    Some(PreparationThreadCpu {
        identity: PreparationThreadIdentity {
            process_id,
            thread_id,
            start_time_ticks,
        },
        user_ticks,
        system_ticks,
    })
}
