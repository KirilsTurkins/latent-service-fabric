//! Restricted bounded NATS framing and verified `JetStream` publish receipts.
use crate::{
    network::{self, Connection},
    request, EventError, Result, TopicMapping,
};
use latent_capabilities::broker::{
    events::{Event, PublishReceipt},
    pools::PoolCall,
};
use serde::Deserialize;

#[derive(Deserialize)]
struct Info {
    headers: bool,
    max_payload: usize,
    #[serde(default)]
    tls_required: bool,
}
pub(crate) fn info(line: &[u8]) -> Result<usize> {
    let bytes = line.strip_prefix(b"INFO ").ok_or(EventError::Unavailable)?;
    guard(bytes)?;
    let info: Info = serde_json::from_slice(bytes).map_err(|_| EventError::Unavailable)?;
    if !info.headers
        || !info.tls_required
        || info.max_payload == 0
        || info.max_payload > 64 * 1024 * 1024
    {
        return Err(EventError::Unavailable);
    }
    Ok(info.max_payload)
}
/// Reject deep containers before serde visits ignored extension fields. Borrowed
/// strings and fixed structures keep server-selected allocations finite.
fn guard(bytes: &[u8]) -> Result<()> {
    if bytes.len() > 8192 {
        return Err(EventError::Unavailable);
    }
    let (mut depth, mut quoted, mut escape) = (0_u8, false, false);
    for &b in bytes {
        if quoted {
            if escape {
                escape = false;
            } else if b == b'\\' {
                escape = true;
            } else if b == b'"' {
                quoted = false;
            }
        } else {
            match b {
                b'"' => quoted = true,
                b'{' | b'[' => {
                    depth += 1;
                    if depth > 8 {
                        return Err(EventError::Unavailable);
                    }
                }
                b'}' | b']' => depth = depth.checked_sub(1).ok_or(EventError::Unavailable)?,
                _ => (),
            }
        }
    }
    if quoted || depth != 0 {
        return Err(EventError::Unavailable);
    }
    Ok(())
}
pub(crate) async fn barrier(connection: &mut Connection, call: &PoolCall) -> Result<()> {
    network::write(connection, call, b"PING\r\n").await?;
    pong(connection, call).await
}
pub(crate) async fn pong(connection: &mut Connection, call: &PoolCall) -> Result<()> {
    for _ in 0..8 {
        let line = network::line(connection, call).await?;
        match line.as_slice() {
            b"PONG" => return Ok(()),
            b"PING" => network::write(connection, call, b"PONG\r\n").await?,
            _ if line.starts_with(b"INFO ") => connection.max_payload = info(&line)?,
            _ if line.starts_with(b"-ERR ") => return Err(EventError::PermissionDenied),
            _ => return Err(EventError::Unavailable),
        }
    }
    Err(EventError::Unavailable)
}
#[derive(Deserialize)]
struct Ack<'a> {
    #[serde(default, borrow)]
    stream: Option<&'a str>,
    #[serde(default)]
    seq: Option<u64>,
    #[serde(default)]
    duplicate: bool,
    #[serde(borrow)]
    error: Option<BrokerError<'a>>,
}
#[derive(Deserialize)]
struct BrokerError<'a> {
    code: u16,
    err_code: u32,
    #[serde(borrow)]
    description: Option<&'a str>,
}
fn ack(bytes: &[u8], expected: &str) -> Result<(u64, bool)> {
    guard(bytes).map_err(|_| EventError::Uncertain)?;
    let reply: Ack<'_> = serde_json::from_slice(bytes).map_err(|_| EventError::Uncertain)?;
    if let Some(error) = reply.error {
        if reply.seq.is_some_and(|s| s > 0) || reply.stream.is_some_and(|s| s != expected) {
            return Err(EventError::Uncertain);
        }
        if !(10000..=19999).contains(&error.err_code)
            || error.description.is_some_and(|s| s.len() > 1024)
        {
            return Err(EventError::Uncertain);
        }
        return Err(match error.code {
            400 => EventError::InvalidEvent,
            403 => EventError::PermissionDenied,
            404 => EventError::Unavailable,
            429 => EventError::BudgetExhausted,
            // A storage/internal error is not proof that the effect was absent.
            _ => EventError::Uncertain,
        });
    }
    match (reply.stream, reply.seq) {
        (Some(stream), Some(sequence)) if stream == expected && sequence > 0 => {
            Ok((sequence, reply.duplicate))
        }
        _ => Err(EventError::Uncertain),
    }
}
fn frame(line: &[u8], inbox: &str) -> Result<(usize, usize)> {
    let line = std::str::from_utf8(line).map_err(|_| EventError::Uncertain)?;
    let mut words = line.split(' ');
    let kind = words.next().ok_or(EventError::Uncertain)?;
    if words.next() != Some(inbox) || words.next() != Some("1") {
        return Err(EventError::Uncertain);
    }
    let number = |s: Option<&str>| -> Result<usize> {
        let s = s.ok_or(EventError::Uncertain)?;
        if s.is_empty() || s.len() > 5 || !s.bytes().all(|b| b.is_ascii_digit()) {
            return Err(EventError::Uncertain);
        }
        s.parse().map_err(|_| EventError::Uncertain)
    };
    let first = number(words.next())?;
    let (headers, total) = match kind {
        "MSG" => (0, first),
        "HMSG" => (first, number(words.next())?),
        _ => return Err(EventError::Uncertain),
    };
    if words.next().is_some() || total > 4096 || headers > total {
        return Err(EventError::Uncertain);
    }
    Ok((headers, total))
}
pub(crate) async fn subscribe(
    connection: &mut Connection,
    call: &PoolCall,
    inbox: &str,
) -> Result<()> {
    let subscription = format!("SUB {inbox} 1\r\nUNSUB 1 1\r\nPING\r\n");
    network::write(connection, call, subscription.as_bytes()).await?;
    pong(connection, call).await?;
    Ok(())
}
pub(crate) async fn publish(
    connection: &mut Connection,
    call: &PoolCall,
    event: &Event,
    mapping: &TopicMapping,
    inbox: &str,
    id: &str,
    wrote: &mut bool,
) -> Result<PublishReceipt> {
    let headers = request::headers(event, &mapping.stream, id);
    if headers.len() + event.payload.len() > connection.max_payload {
        return Err(EventError::InvalidEvent);
    }
    let command = format!(
        "HPUB {} {inbox} {} {}\r\n",
        mapping.subject,
        headers.len(),
        headers.len() + event.payload.len()
    );
    call.io().checkpoint()?;
    // From this first possible publication write onward, cancellation/EOF and
    // malformed replies are uncertain. Nothing resends the mutation.
    *wrote = true;
    for bytes in [
        command.as_bytes(),
        headers.as_bytes(),
        event.payload.as_slice(),
        b"\r\n",
    ] {
        network::write(connection, call, bytes)
            .await
            .map_err(|_| EventError::Uncertain)?;
    }
    for _ in 0..8 {
        let line = network::line(connection, call)
            .await
            .map_err(|_| EventError::Uncertain)?;
        if line == b"PING" {
            network::write(connection, call, b"PONG\r\n")
                .await
                .map_err(|_| EventError::Uncertain)?;
            continue;
        }
        if line.starts_with(b"INFO ") {
            connection.max_payload = info(&line).map_err(|_| EventError::Uncertain)?;
            continue;
        }
        let denied = format!(
            "-ERR 'Permissions Violation for Publish to \"{}\"'",
            mapping.subject
        );
        if line == denied.as_bytes() {
            return Err(EventError::PermissionDenied);
        }
        let (header_bytes, total) = frame(&line, inbox)?;
        let body = network::body(connection, call, total)
            .await
            .map_err(|_| EventError::Uncertain)?;
        if header_bytes > 0 {
            let status = body[..header_bytes]
                .split(|&b| b == b'\n')
                .next()
                .unwrap_or_default();
            if matches!(status, b"NATS/1.0 503\r" | b"NATS/1.0 503 No Responders\r")
                && header_bytes == total
                && body.ends_with(b"\r\n\r\n")
            {
                return Err(EventError::Unavailable);
            }
            // No other header-bearing receipt is part of this initial profile.
            return Err(EventError::Uncertain);
        }
        let (sequence, duplicate) = ack(&body, &mapping.stream)?;
        return Ok(PublishReceipt {
            event_id: format!("{}:{sequence}", mapping.stream),
            accepted_at_unix_millis: latent_core::ClockSample::system_now().unix_millis(),
            stream_name: mapping.stream.clone(),
            sequence,
            duplicate,
        });
    }
    Err(EventError::Uncertain)
}
#[cfg(test)]
mod tests;
