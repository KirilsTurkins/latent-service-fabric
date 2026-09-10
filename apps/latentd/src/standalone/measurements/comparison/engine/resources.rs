use super::{Clock, Result};
use serde_json::{json, Value};
use std::io::Read;

const STATUS: [(&str, &str); 4] = [
    ("VmSize", "vm_size_bytes"),
    ("VmPeak", "vm_peak_bytes"),
    ("VmRSS", "rss_bytes"),
    ("VmHWM", "vm_hwm_bytes"),
];
const ROLLUP: [(&str, &str); 5] = [
    ("Pss", "pss_bytes"),
    ("Private_Clean", "private_clean_bytes"),
    ("Private_Dirty", "private_dirty_bytes"),
    ("Shared_Clean", "shared_clean_bytes"),
    ("Shared_Dirty", "shared_dirty_bytes"),
];

fn read(path: &str, maximum: usize) -> std::result::Result<String, &'static str> {
    let file = std::fs::File::open(path).map_err(|error| match error.kind() {
        std::io::ErrorKind::NotFound => "missing",
        std::io::ErrorKind::PermissionDenied => "permission-denied",
        _ => "invalid-format",
    })?;
    let mut bytes = Vec::new();
    file.take(u64::try_from(maximum + 1).map_err(|_| "oversized")?)
        .read_to_end(&mut bytes)
        .map_err(|_| "invalid-format")?;
    if bytes.len() > maximum {
        return Err("oversized");
    }
    String::from_utf8(bytes).map_err(|_| "invalid-format")
}
fn identity() -> std::result::Result<(u32, u64), &'static str> {
    let text = read("/proc/self/stat", 4096)?;
    let end = text.rfind(')').ok_or("invalid-format")?;
    let pid = text
        .split_once(' ')
        .ok_or("invalid-format")?
        .0
        .parse()
        .map_err(|_| "invalid-format")?;
    let start = text[end + 1..]
        .split_whitespace()
        .nth(19)
        .ok_or("invalid-format")?
        .parse()
        .map_err(|_| "invalid-format")?;
    if pid != std::process::id() {
        return Err("invalid-format");
    }
    Ok((pid, start))
}
fn unavailable(fields: &[(&str, &str)], reason: &str) -> Value {
    Value::Object(
        fields
            .iter()
            .map(|(_, name)| {
                (
                    name.to_string(),
                    json!({"value_bytes":Value::Null,"reason":reason}),
                )
            })
            .collect(),
    )
}
fn parse(text: &str, fields: &[(&str, &str)]) -> Value {
    Value::Object(
        fields
            .iter()
            .map(|(key, name)| {
                let mut lines = text
                    .lines()
                    .filter_map(|line| line.split_once(':'))
                    .filter(|(field, _)| field == key);
                let value = match (lines.next(), lines.next()) {
                    (None, _) => Err("missing-field"),
                    (Some(_), Some(_)) => Err("invalid-format"),
                    (Some((_, tail)), None) => {
                        let columns = tail.split_whitespace().collect::<Vec<_>>();
                        if columns.len() != 2 || columns[1] != "kB" {
                            Err("invalid-format")
                        } else {
                            columns[0]
                                .parse::<u64>()
                                .ok()
                                .and_then(|v| v.checked_mul(1024))
                                .ok_or("invalid-format")
                        }
                    }
                };
                (
                    name.to_string(),
                    match value {
                        Ok(bytes) => json!({"value_bytes":bytes.to_string(),"reason":Value::Null}),
                        Err(reason) => json!({"value_bytes":Value::Null,"reason":reason}),
                    },
                )
            })
            .collect(),
    )
}
pub(in crate::standalone::measurements::comparison) fn capture(
    label: &str,
    clock: Clock,
) -> Result<Value> {
    let started = clock.elapsed();
    let before = if cfg!(target_os = "linux") {
        identity()
    } else {
        Err("unsupported-platform")
    };
    let (status, rollup) = if before.is_ok() {
        (
            read("/proc/self/status", 128 * 1024)
                .map_or_else(|e| unavailable(&STATUS, e), |s| parse(&s, &STATUS)),
            read("/proc/self/smaps_rollup", 64 * 1024)
                .map_or_else(|e| unavailable(&ROLLUP, e), |s| parse(&s, &ROLLUP)),
        )
    } else {
        let reason = if cfg!(target_os = "linux") {
            "identity-unavailable"
        } else {
            "unsupported-platform"
        };
        (unavailable(&STATUS, reason), unavailable(&ROLLUP, reason))
    };
    if before.is_ok() && identity() != before {
        return Err("engine memory process identity changed".into());
    }
    Ok(
        json!({"schema":"latent.optimization.engine-memory.v1","checkpoint":label,
        "collector_started_nanos":started.to_string(),"collector_finished_nanos":clock.elapsed().to_string(),
        "process_id":before.ok().map(|(pid,_)|pid.to_string()),"start_time_ticks":before.ok().map(|(_,ticks)|ticks.to_string()),
        "status":{"source":"proc-self-status","values":status},"smaps_rollup":{"source":"proc-self-smaps-rollup","values":rollup}}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn memory_projection_distinguishes_real_zero_missing_invalid_and_overflow() {
        let value = parse(
            "VmSize: 0 kB\nVmPeak: 2 kB\nVmRSS: 1 MB\nVmHWM: 18446744073709551615 kB\n",
            &STATUS,
        );
        assert_eq!(
            value["vm_size_bytes"],
            json!({"value_bytes":"0","reason":null})
        );
        assert_eq!(value["vm_peak_bytes"]["value_bytes"], "2048");
        assert_eq!(value["rss_bytes"]["reason"], "invalid-format");
        assert_eq!(value["vm_hwm_bytes"]["reason"], "invalid-format");
        let duplicate = parse("Pss: 1 kB\nPss: 1 kB\n", &ROLLUP);
        assert_eq!(duplicate["pss_bytes"]["reason"], "invalid-format");
        assert_eq!(duplicate["private_clean_bytes"]["reason"], "missing-field");
    }
}
