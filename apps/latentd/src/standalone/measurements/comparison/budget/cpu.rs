use serde_json::{json, Value};

use super::{cold::call::Clock, Result};

/// Whole owned process, including its client/control workers. These ticks never
/// become per-invocation CPU or an allocation of CPU to a particular stage.
pub(in crate::standalone::measurements::comparison) fn sample(clock: Clock) -> Result<Value> {
    let started = clock.elapsed();
    let bytes = super::super::super::read(std::path::Path::new("/proc/self/stat"), 8192)?;
    let text = std::str::from_utf8(&bytes)?;
    let close = text.rfind(')').ok_or("process stat command")?;
    let open = text.find('(').ok_or("process stat identity")?;
    let pid = text[..open].trim().parse::<u32>()?;
    if pid != std::process::id() {
        return Err("process CPU identity mismatch".into());
    }
    let fields: Vec<_> = text[close + 1..].split_ascii_whitespace().collect();
    let value = |index: usize| -> Result<u64> {
        Ok(fields.get(index).ok_or("process CPU fields")?.parse()?)
    };
    Ok(
        json!({"collector_started_nanos":started.to_string(),"collector_finished_nanos":clock.elapsed().to_string(),
        "pid":pid.to_string(),"start_time_ticks":value(19)?.to_string(),
        "user_ticks":value(11)?.to_string(),"system_ticks":value(12)?.to_string()}),
    )
}
