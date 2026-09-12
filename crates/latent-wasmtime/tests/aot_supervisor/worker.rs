use std::fs::OpenOptions;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde::Deserialize;

const SANDBOX_PROFILE: &str = "lsf-linux-x86_64-landlock3-seccomp-v1";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    mode: String,
    marker: PathBuf,
}

pub fn run() -> i32 {
    // The fixture emits no raw panic/argument/input diagnostics into the pipe.
    std::panic::set_hook(Box::new(|_| {}));
    match std::panic::catch_unwind(work) {
        Ok(Ok(code)) => code,
        _ => 43,
    }
}

fn work() -> io::Result<i32> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    if arguments.len() != 8
        || arguments[0] != "--worker-v1"
        || std::env::vars_os().next().is_some()
        || std::env::current_dir()? != Path::new("/")
    {
        return Err(invalid());
    }
    let maximum_input: usize = arguments[6].parse().map_err(|_| invalid())?;
    let maximum_output: u64 = arguments[7].parse().map_err(|_| invalid())?;
    if maximum_input > 4096 {
        return Err(invalid());
    }
    let mut input = io::stdin().lock();
    let mut output = io::stdout().lock();
    let mut prefix = [0; 4];
    input.read_exact(&mut prefix)?;
    let bootstrap = body(&mut input, u32::from_le_bytes(prefix) as usize, 4096)?;
    let value: serde_json::Value = serde_json::from_slice(&bootstrap).map_err(|_| invalid())?;
    let digest = value
        .get("engineCompatibility")
        .and_then(serde_json::Value::as_str)
        .and_then(|text| text.strip_prefix("sha256:"))
        .ok_or_else(invalid)?;
    if digest.len() != 64 {
        return Err(invalid());
    }
    let mut readiness = Vec::with_capacity(128);
    readiness.extend_from_slice(b"LSFAOTR1");
    for index in (0..digest.len()).step_by(2) {
        readiness.push(u8::from_str_radix(&digest[index..index + 2], 16).map_err(|_| invalid())?);
    }
    readiness.extend_from_slice(
        &u16::try_from(SANDBOX_PROFILE.len())
            .map_err(|_| invalid())?
            .to_le_bytes(),
    );
    readiness.extend_from_slice(SANDBOX_PROFILE.as_bytes());
    // A fixed test-only malformed-readiness scenario selected by an ordinary
    // bounded output limit; no production hook or inherited environment exists.
    if maximum_output == 17 {
        readiness[0] ^= 1;
    }
    output.write_all(&readiness)?;
    output.flush()?;
    let mut length = [0; 8];
    input.read_exact(&mut length)?;
    let bytes = body(
        &mut input,
        usize::try_from(u64::from_le_bytes(length)).map_err(|_| invalid())?,
        maximum_input,
    )?;
    let mut extra = [0; 1];
    if input.read(&mut extra)? != 0 {
        return Err(invalid());
    }
    let command: Input = serde_json::from_slice(&bytes).map_err(|_| invalid())?;
    if command.mode.len() > 32 || command.marker.as_os_str().len() > 1024 {
        return Err(invalid());
    }
    match command.mode.as_str() {
        "oversized" => output.write_all(&u64::MAX.to_le_bytes())?,
        "zero" => output.write_all(&0_u64.to_le_bytes())?,
        "truncated-header" => output.write_all(&[1, 0, 0])?,
        "truncated-body" => {
            output.write_all(&4_u64.to_le_bytes())?;
            output.write_all(b"x")?;
        }
        "trailing" => {
            output.write_all(&1_u64.to_le_bytes())?;
            output.write_all(b"xy")?;
        }
        "nonzero-exit" => {
            mark(&command.marker)?;
            return Ok(42);
        }
        "diagnostic-overflow" => {
            io::stderr().write_all(&[b'x'; 16 * 1024])?;
            io::stderr().write_all(b"x")?;
        }
        "hang" => {}
        "complete-then-hang" => {
            output.write_all(&1_u64.to_le_bytes())?;
            output.write_all(b"x")?;
        }
        _ => return Err(invalid()),
    }
    output.flush()?;
    // Publication happens only after the complete bounded input was consumed
    // and, for complete-then-hang, a complete native frame was emitted.
    mark(&command.marker)?;
    if matches!(
        command.mode.as_str(),
        "hang" | "complete-then-hang" | "oversized" | "zero" | "diagnostic-overflow"
    ) {
        loop {
            std::thread::sleep(Duration::from_secs(1));
        }
    }
    Ok(0)
}

fn body(input: &mut impl Read, length: usize, maximum: usize) -> io::Result<Vec<u8>> {
    if length == 0 || length > maximum {
        return Err(invalid());
    }
    let mut bytes = vec![0; length];
    input.read_exact(&mut bytes)?;
    Ok(bytes)
}

fn mark(path: &Path) -> io::Result<()> {
    // This fixture is host-approved test code, not the production sandbox. It
    // opens only the fresh owner-selected rendezvous file and never executes a
    // guest or descendant process.
    if !path.is_absolute() || path.file_name().and_then(|name| name.to_str()) != Some("worker.pid")
    {
        return Err(invalid());
    }
    let mut marker = OpenOptions::new().write(true).create_new(true).open(path)?;
    writeln!(marker, "{}", std::process::id())?;
    marker.flush()
}

fn invalid() -> io::Error {
    io::Error::other("invalid supervisor fixture protocol")
}
