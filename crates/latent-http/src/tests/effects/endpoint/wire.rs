use super::*;
use latent_core::digest::HexDigest;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

pub(in crate::tests::effects) struct Request {
    pub method: String,
    pub path: String,
    pub headers: BTreeMap<String, String>,
    pub body: Vec<u8>,
}
impl Request {
    pub fn header(&self, name: &str) -> Option<&str> {
        self.headers.get(name).map(String::as_str)
    }
}

pub(in crate::tests::effects) async fn read_wire(
    socket: &mut (impl tokio::io::AsyncRead + Unpin),
) -> Option<Request> {
    let mut bytes = Vec::with_capacity(4096);
    while !bytes.ends_with(b"\r\n\r\n") {
        let mut byte = [0];
        if bytes.len() >= 16_384 || socket.read(&mut byte).await.ok()? == 0 {
            return None;
        }
        bytes.push(byte[0]);
    }
    parse(bytes, socket).await
}

async fn parse(
    bytes: Vec<u8>,
    socket: &mut (impl tokio::io::AsyncRead + Unpin),
) -> Option<Request> {
    let text = std::str::from_utf8(&bytes).ok()?;
    let mut lines = text.split("\r\n");
    let mut start = lines.next()?.split(' ');
    let method = start.next()?.to_owned();
    let path = start.next()?.to_owned();
    if start.next()? != "HTTP/1.1" || start.next().is_some() {
        return None;
    }
    let mut headers = BTreeMap::new();
    for line in lines.filter(|line| !line.is_empty()) {
        let (name, value) = line.split_once(':')?;
        if headers
            .insert(name.to_ascii_lowercase(), value.trim().to_owned())
            .is_some()
        {
            return None;
        }
    }
    let length = headers.get("content-length")?.parse::<usize>().ok()?;
    if length > 65_536 {
        return None;
    }
    let mut body = vec![0; length];
    socket.read_exact(&mut body).await.ok()?;
    Some(Request {
        method,
        path,
        headers,
        body,
    })
}

pub(super) fn reply(status: u16, bytes: &[u8], extra_headers: &str) -> Vec<u8> {
    let head = format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nContent-Length: {}\r\nConnection: close\r\n{extra_headers}\r\n", bytes.len());
    let mut reply = head.into_bytes();
    reply.extend_from_slice(bytes);
    reply
}

pub(super) fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", HexDigest(Sha256::digest(bytes)))
}
