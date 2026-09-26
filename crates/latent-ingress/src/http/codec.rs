use super::{
    headers,
    model::{RequestData, ResponseData},
    HttpError, Method, MAX_JSON_NODES, MAX_WIRE_BYTES,
};
use std::io::{self, Write};

pub(super) fn encode(request: &RequestData) -> Result<Vec<u8>, HttpError> {
    let mut output = Capped(Vec::new());
    serde_json::to_writer(&mut output, &[request]).map_err(|_| HttpError::AllocationFailed)?;
    Ok(output.0)
}

struct Capped(Vec<u8>);
impl Write for Capped {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        let next = self
            .0
            .len()
            .checked_add(bytes.len())
            .filter(|n| *n <= MAX_WIRE_BYTES)
            .ok_or_else(|| io::Error::other("HTTP value limit"))?;
        if next > self.0.capacity() {
            let capacity = self
                .0
                .capacity()
                .saturating_mul(2)
                .max(next)
                .min(MAX_WIRE_BYTES);
            self.0
                .try_reserve_exact(capacity - self.0.len())
                .map_err(|_| io::Error::other("HTTP allocation limit"))?;
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

pub(super) fn response(bytes: &[u8], method: Method) -> Result<ResponseData, HttpError> {
    preflight(bytes)?;
    let [response]: [ResponseData; 1] =
        serde_json::from_slice(bytes).map_err(|_| HttpError::InvalidResponse)?;
    headers::response(&response, method).map_err(|_| HttpError::InvalidResponse)?;
    Ok(response)
}

/// Allocation-free lexical bounds before serde scratch/recursion. Serde's closed
/// typed records then check grammar, duplicate/unknown keys, integer types, exact
/// arity and per-field/list bounds. No floating-point fields exist in this ABI.
fn preflight(bytes: &[u8]) -> Result<(), HttpError> {
    if bytes.len() > MAX_WIRE_BYTES || std::str::from_utf8(bytes).is_err() {
        return Err(HttpError::InvalidResponse);
    }
    let (mut index, mut depth, mut nodes) = (0, 0_usize, 0_usize);
    while index < bytes.len() {
        match bytes[index] {
            b' ' | b'\n' | b'\r' | b'\t' | b':' | b',' => index += 1,
            b'[' | b'{' => {
                depth += 1;
                nodes += 1;
                index += 1;
            }
            b']' | b'}' => {
                depth = depth.checked_sub(1).ok_or(HttpError::InvalidResponse)?;
                index += 1;
            }
            b'"' => {
                nodes += 1;
                index += 1;
                loop {
                    let byte = *bytes.get(index).ok_or(HttpError::InvalidResponse)?;
                    index += 1;
                    match byte {
                        b'"' => break,
                        b'\\' => {
                            index += 1;
                        }
                        0..=31 => return Err(HttpError::InvalidResponse),
                        _ => {}
                    }
                }
            }
            _ => {
                nodes += 1;
                let start = index;
                while index < bytes.len() && !b" \n\r\t,:[]{}\"".contains(&bytes[index]) {
                    index += 1;
                }
                if bytes[start..index]
                    .iter()
                    .any(|b| matches!(b, b'.' | b'e' | b'E'))
                {
                    return Err(HttpError::InvalidResponse);
                }
            }
        }
        if depth > 12 || nodes > MAX_JSON_NODES {
            return Err(HttpError::InvalidResponse);
        }
    }
    if depth != 0 {
        return Err(HttpError::InvalidResponse);
    }
    Ok(())
}
