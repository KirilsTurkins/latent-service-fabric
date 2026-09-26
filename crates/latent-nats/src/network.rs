//! The pooled value owns the actual socket; no separately spawned protocol driver.
use crate::{
    protocol,
    provider::{Inner, NatsCredential},
    EventError, Result,
};
use latent_capabilities::broker::{
    pools::{PoolCall, PooledConnection, ProviderClient, ProviderMetadata},
    secrets::SecretError,
};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::sync::Arc;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt, BufReader},
    net::{TcpSocket, TcpStream},
};
use tokio_rustls::{client::TlsStream, TlsConnector};
use zeroize::Zeroizing;
mod scope;
pub(crate) use scope::Scope;

pub(crate) struct Connection {
    pub stream: BufReader<TlsStream<TcpStream>>,
    pub stamp: Zeroizing<[u8; 32]>,
    pub max_payload: usize,
    pub _metadata: ProviderMetadata,
}
pub(crate) struct Auth {
    pub encoded: Zeroizing<Vec<u8>>,
    pub stamp: Zeroizing<[u8; 32]>,
}
#[derive(Serialize)]
#[expect(
    clippy::struct_excessive_bools,
    reason = "literal NATS CONNECT wire flags, never mutable application state"
)]
struct Connect<'a> {
    verbose: bool,
    pedantic: bool,
    tls_required: bool,
    headers: bool,
    no_responders: bool,
    protocol: u8,
    lang: &'static str,
    version: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    auth_token: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    user: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pass: Option<&'a str>,
}
pub(crate) fn current(credential: &NatsCredential) -> Result<Auth> {
    let mut encoded = Zeroizing::new(Vec::with_capacity(16384));
    let mut stamp = Zeroizing::new([0; 32]);
    credential
        .secret
        .with_current_value(&mut |value| {
            let value = validate_secret(value)?;
            *stamp = Sha256::digest(value.as_bytes()).into();
            encoded.extend_from_slice(b"CONNECT ");
            serde_json::to_writer(
                &mut *encoded,
                &Connect {
                    verbose: false,
                    pedantic: true,
                    tls_required: true,
                    headers: true,
                    no_responders: true,
                    protocol: 1,
                    lang: "lsf",
                    version: env!("CARGO_PKG_VERSION"),
                    auth_token: credential.username.is_none().then_some(value),
                    user: credential.username.as_deref(),
                    pass: credential.username.as_ref().map(|_| value),
                },
            )
            .map_err(|_| SecretError::Unavailable)?;
            encoded.extend_from_slice(b"\r\nPING\r\n");
            Ok(())
        })
        .map_err(|_| EventError::PermissionDenied)?;
    Ok(Auth { encoded, stamp })
}
fn validate_secret(value: &[u8]) -> std::result::Result<&str, SecretError> {
    if value.is_empty() || value.len() > 4096 || !value.iter().all(|b| (0x21..=0x7e).contains(b)) {
        return Err(SecretError::PermissionDenied);
    }
    std::str::from_utf8(value).map_err(|_| SecretError::PermissionDenied)
}
pub(crate) fn check_current(credential: &NatsCredential, stamp: &[u8; 32]) -> Result<()> {
    credential
        .secret
        .with_current_value(&mut |value| {
            validate_secret(value)?;
            let digest: [u8; 32] = Sha256::digest(value).into();
            if &digest != stamp {
                return Err(SecretError::PermissionDenied);
            }
            Ok(())
        })
        .map_err(|_| EventError::PermissionDenied)
}
pub(crate) fn tls(config: &crate::NatsConfig) -> Result<Arc<rustls::ClientConfig>> {
    tls_for(config.public_roots, &config.extra_roots)
}
pub(crate) fn tls_for(
    public_roots: bool,
    extra_roots: &[Vec<u8>],
) -> Result<Arc<rustls::ClientConfig>> {
    let mut roots = rustls::RootCertStore::empty();
    if public_roots {
        roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
    }
    for cert in extra_roots {
        roots
            .add(rustls::pki_types::CertificateDer::from(cert.clone()))
            .map_err(|_| EventError::InvalidEvent)?;
    }
    let mut tls = rustls::ClientConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_safe_default_protocol_versions()
    .map_err(|_| EventError::InvalidEvent)?
    .with_root_certificates(roots)
    .with_no_client_auth();
    tls.resumption = rustls::client::Resumption::disabled();
    tls.enable_early_data = false;
    tls.cert_decompressors.clear();
    tls.key_log = Arc::new(rustls::NoKeyLog);
    Ok(Arc::new(tls))
}
pub(crate) async fn connect(
    inner: &Inner,
    client: &Arc<ProviderClient<Connection>>,
    call: &PoolCall,
    auth: &Auth,
) -> Result<PooledConnection<Connection>> {
    connect_to(
        Dial {
            pools: &inner.pools,
            endpoint: &inner.config.endpoint,
            tls: &inner.tls,
            attempts: &inner.connection_attempts,
            reuses: &inner.connection_reuses,
        },
        client,
        call.into(),
        auth,
    )
    .await
}
pub(crate) struct Dial<'a> {
    pub pools: &'a latent_capabilities::broker::pools::ProviderPools,
    pub endpoint: &'a crate::NatsEndpoint,
    pub tls: &'a Arc<rustls::ClientConfig>,
    pub attempts: &'a std::sync::atomic::AtomicU64,
    pub reuses: &'a std::sync::atomic::AtomicU64,
}
pub(crate) async fn connect_to(
    dial: Dial<'_>,
    client: &Arc<ProviderClient<Connection>>,
    call: Scope<'_>,
    auth: &Auth,
) -> Result<PooledConnection<Connection>> {
    if let Some(mut connection) = call.checkout(client)? {
        if connection.resource().stamp.as_ref() == auth.stamp.as_ref() {
            protocol::barrier(connection.resource(), call).await?;
            crate::provider::tick(dial.reuses);
            return Ok(connection);
        }
        drop(connection);
    }
    let reservation = call.reserve(client)?;
    let metadata = dial.pools.reserve_protocol_metadata(256 * 1024)?;
    crate::provider::tick(dial.attempts);
    let socket = TcpSocket::new_v4().map_err(|_| EventError::Unavailable)?;
    socket
        .set_send_buffer_size(16384)
        .map_err(|_| EventError::Unavailable)?;
    socket
        .set_recv_buffer_size(16384)
        .map_err(|_| EventError::Unavailable)?;
    let stream = call
        .wait_for(socket.connect(dial.endpoint.peer))
        .await?
        .map_err(|_| EventError::Unavailable)?;
    if stream.peer_addr().map_err(|_| EventError::Unavailable)? != dial.endpoint.peer {
        return Err(EventError::PermissionDenied);
    }
    stream
        .set_nodelay(true)
        .map_err(|_| EventError::Unavailable)?;
    let server = rustls::pki_types::ServerName::try_from(dial.endpoint.server_name.clone())
        .map_err(|_| EventError::InvalidEvent)?;
    let stream = call
        .wait_for(
            TlsConnector::from(dial.tls.clone())
                .connect_with(server, stream, |tls| tls.set_buffer_limit(Some(16384))),
        )
        .await?
        .map_err(|_| EventError::Unavailable)?;
    let mut connection = Connection {
        stream: BufReader::with_capacity(8192, stream),
        stamp: auth.stamp.clone(),
        max_payload: 0,
        _metadata: metadata,
    };
    // This profile requires server tls.handshake_first=true. INFO is inside TLS.
    let info = line(&mut connection, call).await?;
    connection.max_payload = protocol::info(&info)?;
    write(&mut connection, call, &auth.encoded).await?;
    protocol::pong(&mut connection, call).await?;
    reservation.connected(connection).map_err(Into::into)
}
pub(crate) async fn line<'a>(
    connection: &mut Connection,
    call: impl Into<Scope<'a>>,
) -> Result<Vec<u8>> {
    let call = call.into();
    let mut bytes = Vec::with_capacity(8192);
    for _ in 0..8192 {
        let byte = call
            .wait_for(connection.stream.read_u8())
            .await?
            .map_err(|_| EventError::Unavailable)?;
        bytes.push(byte);
        if byte == b'\n' {
            if !bytes.ends_with(b"\r\n") {
                return Err(EventError::Unavailable);
            }
            bytes.truncate(bytes.len() - 2);
            return Ok(bytes);
        }
    }
    Err(EventError::Unavailable)
}
pub(crate) async fn write<'a>(
    connection: &mut Connection,
    call: impl Into<Scope<'a>>,
    bytes: &[u8],
) -> Result<()> {
    let call = call.into();
    call.wait_for(connection.stream.get_mut().write_all(bytes))
        .await?
        .map_err(|_| EventError::Unavailable)?;
    call.wait_for(connection.stream.get_mut().flush())
        .await?
        .map_err(|_| EventError::Unavailable)
}
pub(crate) async fn body<'a>(
    connection: &mut Connection,
    call: impl Into<Scope<'a>>,
    length: usize,
) -> Result<Vec<u8>> {
    body_limit(connection, call.into(), length, 4096).await
}
pub(crate) async fn body_limit(
    connection: &mut Connection,
    call: Scope<'_>,
    length: usize,
    maximum: usize,
) -> Result<Vec<u8>> {
    if length > maximum || maximum > 65536 {
        return Err(EventError::Unavailable);
    }
    let mut bytes = vec![0; length + 2];
    call.wait_for(connection.stream.read_exact(&mut bytes))
        .await?
        .map_err(|_| EventError::Unavailable)?;
    if &bytes[length..] != b"\r\n" {
        return Err(EventError::Unavailable);
    }
    bytes.truncate(length);
    Ok(bytes)
}
