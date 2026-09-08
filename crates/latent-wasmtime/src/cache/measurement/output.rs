use std::io::Write;

pub(super) fn emit(value: &serde_json::Value) -> Result<(), Box<dyn std::error::Error>> {
    let bytes = serde_json::to_vec(value)?;
    if bytes.len() > 16_384 {
        return Err("lookup event exceeds bound".into());
    }
    let mut output = std::io::stdout().lock();
    // Libtest's unterminated test-name prefix must not absorb the ready event.
    output.write_all(b"\n")?;
    output.write_all(&bytes)?;
    output.write_all(b"\n")?;
    output.flush()?;
    Ok(())
}

pub(super) fn nanos(value: rustix::time::Timespec) -> Result<u128, Box<dyn std::error::Error>> {
    let seconds = u128::try_from(value.tv_sec)?;
    let nanos = u128::try_from(value.tv_nsec)?;
    if nanos >= 1_000_000_000 {
        return Err("invalid thread CPU clock nanos".into());
    }
    Ok(seconds * 1_000_000_000 + nanos)
}
