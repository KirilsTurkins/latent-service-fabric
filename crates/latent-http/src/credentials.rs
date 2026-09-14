//! Secrets enter only from explicit trusted configuration, never guest headers.
use crate::{headers, HttpError};
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

pub struct HttpCredential<'a> {
    pub destination: usize,
    pub name: &'a str,
    pub value: &'a str,
}
pub(crate) fn encode(
    input: &[HttpCredential<'_>],
    destinations: usize,
) -> Result<Zeroizing<Vec<u8>>, HttpError> {
    if input.len() > 16 {
        return Err(HttpError::InvalidRequest);
    }
    let mut length = 0usize;
    for (i, entry) in input.iter().enumerate() {
        if entry.destination >= destinations
            || !headers::valid_name(entry.name)
            || headers::hop(entry.name)
            || [
                "host",
                "content-length",
                "content-type",
                "content-encoding",
                "accept-encoding",
                "expect",
                "idempotency-key",
            ]
            .iter()
            .any(|h| entry.name.eq_ignore_ascii_case(h))
            || entry.value.is_empty()
            || entry.value.len() > 4096
            || !headers::valid_value(entry.value)
            || input[..i].iter().any(|e| {
                e.destination == entry.destination && e.name.eq_ignore_ascii_case(entry.name)
            })
        {
            return Err(HttpError::InvalidRequest);
        }
        length = length
            .checked_add(entry.name.len() + entry.value.len() + 6)
            .ok_or(HttpError::InvalidRequest)?;
        if length > 8192 {
            return Err(HttpError::InvalidRequest);
        }
    }
    let mut bytes = Zeroizing::new(Vec::with_capacity(length));
    for entry in input {
        for n in [entry.destination, entry.name.len(), entry.value.len()] {
            bytes.extend_from_slice(
                &u16::try_from(n)
                    .map_err(|_| HttpError::InvalidRequest)?
                    .to_be_bytes(),
            );
        }
        bytes.extend_from_slice(entry.name.as_bytes());
        bytes.extend_from_slice(entry.value.as_bytes());
    }
    Ok(bytes)
}
pub(crate) fn entries(mut bytes: &[u8]) -> impl Iterator<Item = (usize, &str, &str)> {
    std::iter::from_fn(move || {
        if bytes.is_empty() {
            return None;
        }
        let n = |i| usize::from(u16::from_be_bytes([bytes[i], bytes[i + 1]]));
        let (origin, name, value) = (n(0), n(2), n(4));
        let header = std::str::from_utf8(&bytes[6..6 + name]).expect("validated credential name");
        let value_text = std::str::from_utf8(&bytes[6 + name..6 + name + value])
            .expect("validated credential value");
        bytes = &bytes[6 + name + value..];
        Some((origin, header, value_text))
    })
}
pub(crate) struct HashWriter(pub Sha256);
impl std::io::Write for HashWriter {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.0.update(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
