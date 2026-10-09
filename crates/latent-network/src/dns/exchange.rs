use super::decode;
use crate::NetworkError;
use socket2::{Domain, Protocol, SockAddr, Socket, Type};
use std::net::SocketAddr;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpSocket, UdpSocket},
};

const MAXIMUM_SOCKET_BUFFER_BYTES: u32 = 24 * 1024;

pub(super) async fn run(
    server: SocketAddr,
    packet: &[u8],
    allocated: &mut (dyn FnMut() + Send),
) -> Result<Vec<u8>, NetworkError> {
    if !(12..=512).contains(&packet.len()) {
        return Err(NetworkError::DnsFailed);
    }
    let (domain, bind): (_, SocketAddr) = if server.is_ipv4() {
        (
            Domain::IPV4,
            "0.0.0.0:0".parse().expect("literal IPv4 bind"),
        )
    } else {
        (Domain::IPV6, "[::]:0".parse().expect("literal IPv6 bind"))
    };
    // Configure and inspect the bounded buffers before bind can receive data.
    let socket = Socket::new(domain, Type::DGRAM, Some(Protocol::UDP))
        .map_err(|_| NetworkError::DnsFailed)?;
    allocated();
    socket
        .set_send_buffer_size(4096)
        .map_err(|_| NetworkError::DnsFailed)?;
    socket
        .set_recv_buffer_size(8192)
        .map_err(|_| NetworkError::DnsFailed)?;
    let actual = socket
        .send_buffer_size()
        .and_then(|send| {
            socket
                .recv_buffer_size()
                .map(|receive| send.saturating_add(receive))
        })
        .map_err(|_| NetworkError::DnsFailed)?;
    if actual > MAXIMUM_SOCKET_BUFFER_BYTES as usize {
        return Err(NetworkError::ResourceExhausted);
    }
    socket
        .set_nonblocking(true)
        .map_err(|_| NetworkError::DnsFailed)?;
    socket
        .bind(&SockAddr::from(bind))
        .map_err(|_| NetworkError::DnsFailed)?;
    let socket = UdpSocket::from_std(socket.into()).map_err(|_| NetworkError::DnsFailed)?;
    socket
        .connect(server)
        .await
        .map_err(|_| NetworkError::DnsFailed)?;
    if socket.peer_addr().map_err(|_| NetworkError::DnsFailed)? != server
        || socket
            .send(packet)
            .await
            .map_err(|_| NetworkError::DnsFailed)?
            != packet.len()
    {
        return Err(NetworkError::DnsFailed);
    }
    let mut buffer = vec![0; 4097];
    let length = socket
        .recv(&mut buffer)
        .await
        .map_err(|_| NetworkError::DnsFailed)?;
    buffer.truncate(length);
    decode::preflight(&buffer)?;
    if buffer[..2] != packet[..2] || buffer[2] & 0xf8 != 0x80 {
        return Err(NetworkError::DnsFailed);
    }
    if buffer[2] & 2 == 0 {
        return Ok(buffer);
    }
    drop(socket);
    drop(buffer);
    tcp(server, packet, allocated).await
}

async fn tcp(
    server: SocketAddr,
    packet: &[u8],
    allocated: &mut (dyn FnMut() + Send),
) -> Result<Vec<u8>, NetworkError> {
    let socket = if server.is_ipv4() {
        TcpSocket::new_v4()
    } else {
        TcpSocket::new_v6()
    }
    .map_err(|_| NetworkError::DnsFailed)?;
    allocated();
    socket
        .set_send_buffer_size(4096)
        .map_err(|_| NetworkError::DnsFailed)?;
    socket
        .set_recv_buffer_size(8192)
        .map_err(|_| NetworkError::DnsFailed)?;
    let actual = socket
        .send_buffer_size()
        .and_then(|send| {
            socket
                .recv_buffer_size()
                .map(|receive| send.saturating_add(receive))
        })
        .map_err(|_| NetworkError::DnsFailed)?;
    if actual > MAXIMUM_SOCKET_BUFFER_BYTES {
        return Err(NetworkError::ResourceExhausted);
    }
    let mut stream = socket
        .connect(server)
        .await
        .map_err(|_| NetworkError::DnsFailed)?;
    if stream.peer_addr().map_err(|_| NetworkError::DnsFailed)? != server {
        return Err(NetworkError::DnsFailed);
    }
    let prefix = u16::try_from(packet.len())
        .map_err(|_| NetworkError::DnsFailed)?
        .to_be_bytes();
    stream
        .write_all(&prefix)
        .await
        .map_err(|_| NetworkError::DnsFailed)?;
    stream
        .write_all(packet)
        .await
        .map_err(|_| NetworkError::DnsFailed)?;
    let mut prefix = [0; 2];
    stream
        .read_exact(&mut prefix)
        .await
        .map_err(|_| NetworkError::DnsFailed)?;
    let length = usize::from(u16::from_be_bytes(prefix));
    if !(12..=4096).contains(&length) {
        return Err(NetworkError::DnsFailed);
    }
    let mut buffer = vec![0; length];
    stream
        .read_exact(&mut buffer)
        .await
        .map_err(|_| NetworkError::DnsFailed)?;
    Ok(buffer)
}
