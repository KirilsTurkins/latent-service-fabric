use super::TriggerBinding;
use crate::{
    network::{self, Connection, Scope},
    protocol, EventError, Result,
};

pub(super) struct Frame {
    pub subject: String,
    pub reply: Option<String>,
    pub bytes: Vec<u8>,
    pub headers: usize,
}
impl Frame {
    pub fn payload(&self) -> &[u8] {
        &self.bytes[self.headers..]
    }
    pub fn status(&self) -> Result<Option<u16>> {
        if self.headers == 0 {
            return Ok(None);
        }
        let header = &self.bytes[..self.headers];
        if !header.ends_with(b"\r\n\r\n") {
            return Err(EventError::Unavailable);
        }
        let line = header.split(|&b| b == b'\n').next().unwrap_or_default();
        if line == b"NATS/1.0\r" {
            return Ok(None);
        }
        let code = line
            .strip_prefix(b"NATS/1.0 ")
            .ok_or(EventError::Unavailable)?;
        if code.len() < 4
            || !code[..3].iter().all(u8::is_ascii_digit)
            || !matches!(code[3], b' ' | b'\r')
            || !self.payload().is_empty()
            || self.reply.is_some()
        {
            return Err(EventError::Unavailable);
        }
        let code = std::str::from_utf8(&code[..3])
            .map_err(|_| EventError::Unavailable)?
            .parse()
            .map_err(|_| EventError::Unavailable)?;
        Ok(Some(code))
    }
}

pub(super) async fn receive(
    connection: &mut Connection,
    call: Scope<'_>,
    subjects: &[&str],
    maximum_payload: usize,
) -> Result<Frame> {
    for _ in 0..8 {
        let line = network::line(connection, call).await?;
        match line.as_slice() {
            b"PING" => {
                network::write(connection, call, b"PONG\r\n").await?;
                continue;
            }
            _ if line.starts_with(b"INFO ") => {
                connection.max_payload = protocol::info(&line)?;
                continue;
            }
            _ if line.starts_with(b"-ERR ") => return Err(EventError::PermissionDenied),
            _ => {}
        }
        let raw = std::str::from_utf8(&line).map_err(|_| EventError::Unavailable)?;
        let mut words = raw.split(' ');
        let kind = words.next().ok_or(EventError::Unavailable)?;
        let subject = words.next().ok_or(EventError::Unavailable)?;
        if !subjects.contains(&subject) || words.next() != Some("1") {
            return Err(EventError::Unavailable);
        }
        let mut fields = [""; 3];
        let mut count = 0;
        for field in words {
            if count == fields.len() || field.is_empty() {
                return Err(EventError::Unavailable);
            }
            fields[count] = field;
            count += 1;
        }
        let (reply, header, total) = match (kind, count) {
            ("MSG", 1) => (None, 0, number(fields[0])?),
            ("MSG", 2) => (Some(fields[0]), 0, number(fields[1])?),
            ("HMSG", 2) => (None, number(fields[0])?, number(fields[1])?),
            ("HMSG", 3) => (Some(fields[0]), number(fields[1])?, number(fields[2])?),
            _ => return Err(EventError::Unavailable),
        };
        if (kind == "HMSG" && header == 0)
            || header > 8192
            || header > total
            || total - header > maximum_payload
            || reply
                .is_some_and(|r| r.len() > 512 || !r.bytes().all(|b| (0x21..=0x7e).contains(&b)))
        {
            return Err(EventError::Unavailable);
        }
        let bytes = network::body_limit(connection, call, total, maximum_payload + 8192).await?;
        return Ok(Frame {
            subject: subject.to_owned(),
            reply: reply.map(str::to_owned),
            bytes,
            headers: header,
        });
    }
    Err(EventError::Unavailable)
}
fn number(value: &str) -> Result<usize> {
    if value.is_empty() || value.len() > 5 || !value.bytes().all(|b| b.is_ascii_digit()) {
        return Err(EventError::Unavailable);
    }
    value.parse().map_err(|_| EventError::Unavailable)
}

pub(super) async fn send(
    connection: &mut Connection,
    call: Scope<'_>,
    subject: &str,
    inbox: &str,
    body: &[u8],
) -> Result<()> {
    // Only closed, validated subjects constructed by the trusted trigger reach here.
    if subject.len() > 512 || inbox.len() > 256 || body.len() > 2048 {
        return Err(EventError::InvalidEvent);
    }
    let command = format!("PUB {subject} {inbox} {}\r\n", body.len());
    for bytes in [command.as_bytes(), body, b"\r\n"] {
        network::write(connection, call, bytes).await?;
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) struct DeliveryIdentity {
    pub delivery: u32,
    pub sequence: u64,
}
pub(super) fn identity(reply: &str, binding: &TriggerBinding) -> Result<DeliveryIdentity> {
    if reply.len() > 512 {
        return Err(EventError::Unavailable);
    }
    let mut parts = [""; 11];
    let mut count = 0;
    for part in reply.split('.') {
        if count == parts.len() || part.is_empty() {
            return Err(EventError::Unavailable);
        }
        parts[count] = part;
        count += 1;
    }
    if parts[0] != "$JS" || parts[1] != "ACK" {
        return Err(EventError::Unavailable);
    }
    let offset = match count {
        9 => 2,
        11 if parts[2] == "_"
            && parts[3].len() <= 64
            && parts[3].bytes().all(|b| b.is_ascii_alphanumeric()) =>
        {
            4
        }
        _ => return Err(EventError::Unavailable),
    };
    if parts[offset] != binding.stream || parts[offset + 1] != binding.consumer {
        return Err(EventError::PermissionDenied);
    }
    let mut numbers = [0u64; 5];
    for (i, value) in parts[offset + 2..offset + 7].iter().enumerate() {
        if value.len() > 20 || !value.bytes().all(|b| b.is_ascii_digit()) {
            return Err(EventError::Unavailable);
        }
        numbers[i] = value.parse().map_err(|_| EventError::Unavailable)?;
        if i < 4 && numbers[i] == 0 {
            return Err(EventError::Unavailable);
        }
    }
    Ok(DeliveryIdentity {
        delivery: u32::try_from(numbers[0]).map_err(|_| EventError::Unavailable)?,
        sequence: numbers[1],
    })
}
