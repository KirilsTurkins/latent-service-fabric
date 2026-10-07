//! One physical TCP/TLS owner. Locks never span an external readiness await.
use crate::{error, StreamError, StreamErrorCode};
use std::{
    io::{self, Read, Write},
    sync::{Arc, Mutex},
};
use tokio::{io::Interest, net::TcpStream};

pub(crate) struct Transport {
    pub tcp: Arc<TcpStream>,
    tls: Option<Mutex<TlsState>>,
    _tls_configuration: Option<Arc<crate::tls::InstalledTls>>,
}
struct TlsState {
    connection: rustls::ClientConnection,
    handshake_read: usize,
    handshake_write: usize,
}
struct SocketIo<'a>(&'a TcpStream);
struct LimitedRead<'a> {
    tcp: &'a TcpStream,
    remaining: usize,
}
struct LimitedWrite<'a> {
    tcp: &'a TcpStream,
    remaining: usize,
}
impl Write for LimitedWrite<'_> {
    fn write(&mut self, input: &[u8]) -> io::Result<usize> {
        if self.remaining == 0 {
            return Err(io::Error::from(io::ErrorKind::WriteZero));
        }
        let count = self
            .tcp
            .try_write(&input[..input.len().min(self.remaining)])?;
        self.remaining -= count;
        Ok(count)
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
impl Read for LimitedRead<'_> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        let maximum = output.len().min(self.remaining);
        self.tcp.try_read(&mut output[..maximum])
    }
}
impl Read for SocketIo<'_> {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        self.0.try_read(bytes)
    }
}
impl Write for SocketIo<'_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.0.try_write(bytes)
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn failure() -> StreamError {
    error(StreamErrorCode::TlsFailed)
}
impl Transport {
    pub fn tcp(tcp: TcpStream) -> Self {
        Self {
            tcp: Arc::new(tcp),
            tls: None,
            _tls_configuration: None,
        }
    }
    pub fn tls(
        tcp: TcpStream,
        config: Arc<crate::tls::InstalledTls>,
        name: String,
    ) -> Result<Self, StreamError> {
        let name = rustls::pki_types::ServerName::try_from(name).map_err(|_| failure())?;
        let mut connection = rustls::ClientConnection::new(Arc::clone(&config.config), name)
            .map_err(|_| failure())?;
        connection.set_buffer_limit(Some(crate::tls::WRITE_BUFFER_BYTES));
        Ok(Self {
            tcp: Arc::new(tcp),
            tls: Some(Mutex::new(TlsState {
                connection,
                handshake_read: 0,
                handshake_write: 0,
            })),
            _tls_configuration: Some(config),
        })
    }
    pub fn host_tls(&self) -> bool {
        self.tls.is_some()
    }

    // Flush only already accepted ciphertext. WouldBlock yields to this same
    // original socket; it never restarts a plaintext write or handshake.
    fn flush(
        connection: &mut rustls::ClientConnection,
        tcp: &TcpStream,
    ) -> Result<(), StreamError> {
        while connection.wants_write() {
            match connection.write_tls(&mut SocketIo(tcp)) {
                Ok(0) => return Err(error(StreamErrorCode::IoFailed)),
                Ok(_) => {}
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => break,
                Err(_) => return Err(error(StreamErrorCode::IoFailed)),
            }
        }
        Ok(())
    }

    pub fn handshake_step(&self) -> Result<Option<Interest>, StreamError> {
        let Some(tls) = &self.tls else {
            return Ok(None);
        };
        let mut state = tls.lock().map_err(|_| failure())?;
        let TlsState {
            connection,
            handshake_read,
            handshake_write,
        } = &mut *state;
        // Limit encrypted handshake input before it reaches the TLS parser.
        // This is an explicit finite host profile, not a universal chain limit.
        while connection.wants_write() {
            if *handshake_write >= 32 * 1024 {
                return Err(error(StreamErrorCode::Exhausted));
            }
            match connection.write_tls(&mut LimitedWrite {
                tcp: &self.tcp,
                remaining: 32 * 1024 - *handshake_write,
            }) {
                Ok(0) => return Err(failure()),
                Ok(count) => {
                    *handshake_write += count;
                    if *handshake_write > 32 * 1024 {
                        return Err(error(StreamErrorCode::Exhausted));
                    }
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => break,
                Err(_) => return Err(failure()),
            }
        }
        if connection.wants_write() {
            return Ok(Some(Interest::WRITABLE));
        }
        if !connection.is_handshaking() {
            return Ok(None);
        }
        if *handshake_read >= 32 * 1024 {
            return Err(error(StreamErrorCode::Exhausted));
        }
        let mut input = LimitedRead {
            tcp: &self.tcp,
            remaining: 32 * 1024 - *handshake_read,
        };
        match connection.read_tls(&mut input) {
            Ok(0) => return Err(failure()),
            Ok(count) => {
                *handshake_read += count;
                connection.process_new_packets().map_err(|_| failure())?;
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                return Ok(Some(Interest::READABLE))
            }
            Err(_) => return Err(failure()),
        }
        // Final handshake records are flushed by the next step under the same
        // encrypted-output cap; no new connection or plaintext attempt begins.
        if connection.wants_write() {
            Ok(Some(Interest::WRITABLE))
        } else if connection.is_handshaking() {
            Ok(Some(Interest::READABLE))
        } else {
            Ok(None)
        }
    }

    pub fn try_read(&self, output: &mut [u8]) -> Result<Option<usize>, StreamError> {
        let Some(tls) = &self.tls else {
            return match self.tcp.try_read(output) {
                Ok(count) => Ok(Some(count)),
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => Ok(None),
                Err(_) => Err(error(StreamErrorCode::IoFailed)),
            };
        };
        let mut state = tls.lock().map_err(|_| failure())?;
        let connection = &mut state.connection;
        match connection.reader().read(output) {
            Ok(count) => return Ok(Some(count)),
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {}
            Err(_) => return Err(failure()),
        }
        match connection.read_tls(&mut SocketIo(&self.tcp)) {
            Ok(_) => {
                connection.process_new_packets().map_err(|_| failure())?;
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => return Ok(None),
            Err(_) => return Err(failure()),
        }
        Self::flush(connection, &self.tcp)?;
        match connection.reader().read(output) {
            Ok(count) => Ok(Some(count)),
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => Ok(None),
            Err(_) => Err(failure()),
        }
    }

    pub fn try_write(&self, input: &[u8]) -> Result<Option<usize>, StreamError> {
        let Some(tls) = &self.tls else {
            return match self.tcp.try_write(input) {
                Ok(count) => Ok(Some(count)),
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => Ok(None),
                Err(_) => Err(error(StreamErrorCode::IoFailed)),
            };
        };
        let mut state = tls.lock().map_err(|_| failure())?;
        let connection = &mut state.connection;
        Self::flush(connection, &self.tcp)?;
        if connection.wants_write() {
            return Ok(None);
        }
        let count = match connection.writer().write(input) {
            Ok(0) => return Ok(None),
            Ok(count) => count,
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => return Ok(None),
            Err(_) => return Err(failure()),
        };
        // Retain this accepted plaintext prefix even if ciphertext dispatch
        // subsequently fails. Returning acceptance is not remote completion.
        if let Err(mut error) = Self::flush(connection, &self.tcp) {
            error.accepted_prefix_bytes = u32::try_from(count).expect("bounded input");
            return Err(error.uncertain(true));
        }
        Ok(Some(count))
    }

    pub fn flush_pending(&self) -> Result<bool, StreamError> {
        let Some(tls) = &self.tls else {
            return Ok(true);
        };
        let mut state = tls.lock().map_err(|_| failure())?;
        Self::flush(&mut state.connection, &self.tcp)?;
        Ok(!state.connection.wants_write())
    }

    pub fn buffered_readable(&self) -> Result<bool, StreamError> {
        let Some(tls) = &self.tls else {
            return Ok(false);
        };
        let mut state = tls.lock().map_err(|_| failure())?;
        let observed = state
            .connection
            .process_new_packets()
            .map_err(|_| failure())?;
        Ok(observed.plaintext_bytes_to_read() != 0 || observed.peer_has_closed())
    }
}
