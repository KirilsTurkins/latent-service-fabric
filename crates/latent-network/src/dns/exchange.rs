use super::decode;
use crate::NetworkError;
use std::net::SocketAddr;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpSocket, UdpSocket},
};

pub(super) async fn run(server: SocketAddr, packet: &[u8]) -> Result<Vec<u8>, NetworkError> {
    if !(12..=512).contains(&packet.len()) {
        return Err(NetworkError::DnsFailed);
    }
    let bind = if server.is_ipv4() {
        "0.0.0.0:0"
    } else {
        "[::]:0"
    };
    let socket = UdpSocket::bind(bind)
        .await
        .map_err(|_| NetworkError::DnsFailed)?;
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
    tcp(server, packet).await
}

async fn tcp(server: SocketAddr, packet: &[u8]) -> Result<Vec<u8>, NetworkError> {
    let socket = if server.is_ipv4() {
        TcpSocket::new_v4()
    } else {
        TcpSocket::new_v6()
    }
    .map_err(|_| NetworkError::DnsFailed)?;
    socket
        .set_send_buffer_size(4096)
        .map_err(|_| NetworkError::DnsFailed)?;
    socket
        .set_recv_buffer_size(8192)
        .map_err(|_| NetworkError::DnsFailed)?;
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
