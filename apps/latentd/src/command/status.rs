use std::io::{self, Write};
#[cfg(target_os = "linux")]
use std::net::SocketAddr;

#[cfg(target_os = "linux")]
use latent_core::PlatformErrorCode;
use serde::Serialize;

#[cfg(target_os = "linux")]
use super::Failure;

#[cfg(target_os = "linux")]
const SCHEMA: &str = "latent.standalone.status.v1";
const MAXIMUM_LINE_BYTES: usize = 16 * 1024;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
#[cfg(target_os = "linux")]
struct Started<'a> {
    schema_version: &'static str,
    event: &'static str,
    node_id: &'a str,
    endpoint: SocketAddr,
    ready: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
#[cfg(target_os = "linux")]
struct Stopped<'a, T> {
    schema_version: &'static str,
    event: &'static str,
    clean: bool,
    report: &'a T,
}

#[cfg(target_os = "linux")]
pub(super) fn started(node_id: &str, endpoint: SocketAddr, ready: bool) -> Result<(), Failure> {
    output(&Started {
        schema_version: SCHEMA,
        event: if ready { "ready" } else { "started" },
        node_id,
        endpoint,
        ready,
    })
}

#[cfg(target_os = "linux")]
pub(super) fn stopped<T: Serialize>(report: &T) -> Result<(), Failure> {
    output(&Stopped {
        schema_version: SCHEMA,
        event: "stopped",
        clean: true,
        report,
    })
}

#[cfg(target_os = "linux")]
fn output(record: &impl Serialize) -> Result<(), Failure> {
    let line = encode(record).map_err(|_| Failure::new("output", PlatformErrorCode::Internal))?;
    let mut stdout = io::stdout().lock();
    stdout
        .write_all(&line)
        .and_then(|()| stdout.flush())
        .map_err(|_| Failure::new("output", PlatformErrorCode::Unavailable))
}

pub(super) fn encode(record: &impl Serialize) -> Result<Vec<u8>, serde_json::Error> {
    let mut writer = LineWriter(Vec::new());
    serde_json::to_writer(&mut writer, record)?;
    writer.0.push(b'\n');
    Ok(writer.0)
}

struct LineWriter(Vec<u8>);

impl Write for LineWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > (MAXIMUM_LINE_BYTES - 1).saturating_sub(self.0.len()) {
            return Err(io::Error::other("standalone status record exceeds bound"));
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
