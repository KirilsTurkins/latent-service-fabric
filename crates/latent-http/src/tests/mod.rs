mod audit;
mod dns;
mod fixture;
mod http;
mod ownership;
mod redirects;
mod responses;
mod tls;
mod validation;
use crate::*;
use fixture::*;
use latent_capabilities::broker::http::{
    HttpError, HttpHeader, HttpMethod, HttpRequest, OutboundHttpInvoker,
};
use latent_policy::capability::HttpOrigin;
use std::{
    sync::{atomic::Ordering, Arc},
    time::Duration,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};
pub(crate) fn config(port: u16) -> HttpProviderConfig {
    HttpProviderConfig {
        format_version: 1,
        limits: HttpLimits::default(),
        extra_roots: Vec::new(),
        public_roots: false,
        destinations: vec![HttpDestination {
            origin: HttpOrigin {
                scheme: "http".into(),
                host: "localhost".into(),
                port,
            },
            addresses: HttpAddressPolicy {
                networks: vec!["127.0.0.0/8".parse().unwrap()],
                special_addresses: vec!["127.0.0.1".parse().unwrap()],
            },
            resolution: HttpResolution::Static {
                addresses: vec!["127.0.0.1".parse().unwrap()],
            },
            allowed_request_headers: vec!["x-test".into()],
            redirect_destinations: vec![0],
        }],
    }
}
fn request(port: u16, method: HttpMethod) -> HttpRequest {
    HttpRequest {
        method,
        url: format!("http://localhost:{port}/allowed"),
        headers: Vec::new(),
        body: None,
        body_media_type: None,
        idempotency_key: None,
        timeout_millis: None,
    }
}
async fn read_request(stream: &mut (impl tokio::io::AsyncRead + Unpin)) -> Vec<u8> {
    let mut bytes = Vec::new();
    let mut byte = [0];
    while !bytes.ends_with(b"\r\n\r\n") {
        assert!(bytes.len() < 16384);
        assert_eq!(stream.read(&mut byte).await.unwrap(), 1);
        bytes.push(byte[0]);
    }
    let text = std::str::from_utf8(&bytes).unwrap();
    let length = text
        .lines()
        .find_map(|l| l.strip_prefix("content-length: "))
        .unwrap_or("0")
        .parse::<usize>()
        .unwrap();
    assert!(length < 65536);
    let start = bytes.len();
    bytes.resize(start + length, 0);
    stream.read_exact(&mut bytes[start..]).await.unwrap();
    bytes
}
