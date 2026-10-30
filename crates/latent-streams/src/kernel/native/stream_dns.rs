//! DNS packets on the SAME original paid protected context. No ambient socket,
//! resolver, new task, timer, FD, destination or retry after uncertain effects.
use super::stream_socket::Socket;
use crate::{StreamError, StreamErrorCode};
use latent_network::{
    dns::{decode, PacketExchange},
    NetworkError,
};
use std::{future::poll_fn, net::SocketAddr, sync::Arc, task::Poll};

pub(crate) struct Exchange {
    socket: Arc<Socket>,
    server: SocketAddr,
    tcp: bool,
    fault: Option<StreamError>,
    protocol_progress: bool,
}
impl Exchange {
    pub fn new(socket: Arc<Socket>, server: SocketAddr) -> Self {
        Self {
            socket,
            server,
            tcp: false,
            fault: None,
            protocol_progress: false,
        }
    }
    /// Private typed cause for the outer original connection. DNS protocol/
    /// framing byte prefixes never become application plaintext acceptance.
    pub fn take_failure(&mut self) -> Option<StreamError> {
        self.fault.take()
    }
    pub fn may_have_applied(&self) -> bool {
        self.protocol_progress
            || self
                .fault
                .is_some_and(|fault| fault.may_have_applied || fault.accepted_prefix_bytes != 0)
    }
    fn failed(&mut self, fault: StreamError) -> NetworkError {
        if self.fault.is_none() {
            self.fault = Some(fault);
        }
        match fault.code {
            StreamErrorCode::Timeout => NetworkError::DeadlineExceeded,
            StreamErrorCode::Denied => NetworkError::PermissionDenied,
            StreamErrorCode::Revoked | StreamErrorCode::Cancelled => NetworkError::Closed,
            StreamErrorCode::Exhausted => NetworkError::ResourceExhausted,
            _ => NetworkError::DnsFailed,
        }
    }
    async fn send(&mut self, bytes: &[u8], datagram: bool) -> Result<(), NetworkError> {
        let mut accepted = 0;
        while accepted < bytes.len() {
            let count = poll_fn(|_| match self.socket.try_write(&bytes[accepted..]) {
                Ok(Some(n)) => Poll::Ready(Ok(n)),
                Ok(None) => Poll::Pending,
                Err(fault) => Poll::Ready(Err(self.failed(fault))),
            })
            .await?;
            self.protocol_progress |= count != 0;
            if count == 0 || count > bytes.len() - accepted || (datagram && count != bytes.len()) {
                return Err(NetworkError::DnsFailed);
            }
            // TCP resumes only the confirmed original suffix. An uncertain
            // native result is Err above, never a replay of its prefix.
            accepted += count;
        }
        Ok(())
    }
    async fn receive(&mut self, output: &mut [u8]) -> Result<usize, NetworkError> {
        poll_fn(|_| match self.socket.try_read(output) {
            Ok(Some(n)) if n <= output.len() => Poll::Ready(Ok(n)),
            Ok(Some(_)) => Poll::Ready(Err(NetworkError::DnsFailed)),
            Ok(None) => Poll::Pending,
            Err(fault) => Poll::Ready(Err(self.failed(fault))),
        })
        .await
    }
    async fn exact(&mut self, output: &mut [u8]) -> Result<(), NetworkError> {
        let mut filled = 0;
        while filled < output.len() {
            let count = self.receive(&mut output[filled..]).await?;
            if count == 0 {
                return Err(NetworkError::DnsFailed);
            }
            filled += count;
        }
        Ok(())
    }
    async fn tcp_packet(&mut self, packet: &[u8]) -> Result<Vec<u8>, NetworkError> {
        let connected = self.socket.connect(self.server).await;
        connected.map_err(|fault| self.failed(fault))?;
        self.send(&(packet.len() as u16).to_be_bytes(), false)
            .await?;
        self.send(packet, false).await?;
        let mut prefix = [0; 2];
        self.exact(&mut prefix).await?;
        let count = usize::from(u16::from_be_bytes(prefix));
        if !(12..=4096).contains(&count) {
            return Err(NetworkError::DnsFailed);
        }
        let mut bytes = vec![0; count];
        self.exact(&mut bytes).await?;
        Ok(bytes)
    }
}
impl PacketExchange for Exchange {
    async fn exchange<'a>(
        &'a mut self,
        server: SocketAddr,
        packet: &'a [u8],
        _allocated: &'a mut (dyn FnMut() + Send),
    ) -> Result<Vec<u8>, NetworkError> {
        if server != self.server || !(12..=512).contains(&packet.len()) {
            return Err(NetworkError::DnsFailed);
        }
        let connected = self.socket.connect(self.server).await;
        connected.map_err(|fault| self.failed(fault))?;
        if self.tcp {
            return self.tcp_packet(packet).await;
        }
        self.send(packet, true).await?;
        // One extra byte detects an oversized datagram without accepting a
        // silently truncated DNS reply as the original bounded message.
        let mut bytes = vec![0; 4097];
        let count = self.receive(&mut bytes).await?;
        bytes.truncate(count);
        decode::preflight(&bytes)?;
        if bytes[..2] != packet[..2] || bytes[2] & 0xf8 != 0x80 {
            return Err(NetworkError::DnsFailed);
        }
        if bytes[2] & 2 == 0 {
            return Ok(bytes);
        }
        drop(bytes); // Same funded scratch, no simultaneous response buffers.
        poll_fn(|_| match self.socket.dns_tcp_fallback() {
            Ok(true) => Poll::Ready(Ok(())),
            Ok(false) => Poll::Pending,
            Err(fault) => Poll::Ready(Err(self.failed(fault))),
        })
        .await?;
        self.tcp = true;
        self.tcp_packet(packet).await
    }
}
