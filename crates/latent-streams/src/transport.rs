//! One physical TCP/TLS owner. Locks never span an external readiness await.
use crate::{error, StreamError, StreamErrorCode};
use std::{
    io::{self, Read, Write},
    sync::{Arc, Mutex},
};
use tokio::{io::Interest, net::TcpStream};

pub(crate) struct Transport {
    wire: Wire,
    tls: Option<Mutex<TlsState>>,
    _tls_configuration: Option<Arc<crate::tls::InstalledTls>>,
}

pub(crate) struct Readiness {
    readable: bool,
    writable: bool,
    read_closed: bool,
    write_closed: bool,
}
impl Readiness {
    pub fn is_readable(&self) -> bool {
        self.readable
    }
    pub fn is_writable(&self) -> bool {
        self.writable
    }
    pub fn is_read_closed(&self) -> bool {
        self.read_closed
    }
    pub fn is_write_closed(&self) -> bool {
        self.write_closed
    }
}
enum Wire {
    Tcp(Arc<TcpStream>),
    #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
    Protected(Arc<crate::kernel::native::StreamSocket>),
}
impl Wire {
    fn read(&self, bytes: &mut [u8]) -> Result<Option<usize>, StreamError> {
        match self {
            Self::Tcp(tcp) => match tcp.try_read(bytes) {
                Ok(count) => Ok(Some(count)),
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => Ok(None),
                Err(_) => Err(error(StreamErrorCode::IoFailed)),
            },
            #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
            Self::Protected(socket) => socket.try_read(bytes),
        }
    }
    fn write(&self, bytes: &[u8]) -> Result<Option<usize>, StreamError> {
        match self {
            Self::Tcp(tcp) => match tcp.try_write(bytes) {
                Ok(count) => Ok(Some(count)),
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => Ok(None),
                Err(_) => Err(error(StreamErrorCode::IoFailed)),
            },
            #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
            Self::Protected(socket) => socket.try_write(bytes),
        }
    }
    fn io_result(
        &self,
        result: Result<Option<usize>, StreamError>,
        original: &mut Option<StreamError>,
    ) -> io::Result<usize> {
        match result {
            Ok(Some(count)) => Ok(count),
            Ok(None) => Err(io::ErrorKind::WouldBlock.into()),
            Err(fault) => {
                // Private stack carrier: rustls still sees the SAME std::io
                // error, but actual protected uncertainty must not disappear.
                // Historical host TCP errors retain their original translation.
                let _ = (&original, &fault);
                #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
                if matches!(self, Self::Protected(_)) && original.is_none() {
                    *original = Some(fault);
                }
                Err(io::ErrorKind::Other.into())
            }
        }
    }
    fn try_read(&self, bytes: &mut [u8], original: &mut Option<StreamError>) -> io::Result<usize> {
        self.io_result(self.read(bytes), original)
    }
    fn try_write(&self, bytes: &[u8], original: &mut Option<StreamError>) -> io::Result<usize> {
        self.io_result(self.write(bytes), original)
    }
}

struct TlsState {
    connection: rustls::ClientConnection,
    handshake_read: usize,
    handshake_write: usize,
}
struct SocketIo<'a> {
    tcp: &'a Wire,
    original: &'a mut Option<StreamError>,
}
struct LimitedRead<'a> {
    tcp: &'a Wire,
    remaining: usize,
    original: &'a mut Option<StreamError>,
}
struct LimitedWrite<'a> {
    tcp: &'a Wire,
    remaining: usize,
    original: &'a mut Option<StreamError>,
}
impl Write for LimitedWrite<'_> {
    fn write(&mut self, input: &[u8]) -> io::Result<usize> {
        if self.remaining == 0 {
            return Err(io::Error::from(io::ErrorKind::WriteZero));
        }
        let count = self
            .tcp
            .try_write(&input[..input.len().min(self.remaining)], self.original)?;
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
        let count = self.tcp.try_read(&mut output[..maximum], self.original)?;
        self.remaining -= count;
        Ok(count)
    }
}
impl Read for SocketIo<'_> {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        self.tcp.try_read(bytes, self.original)
    }
}
impl Write for SocketIo<'_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.tcp.try_write(bytes, self.original)
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn failure() -> StreamError {
    error(StreamErrorCode::TlsFailed)
}
fn reject_original_fault(
    original: Option<StreamError>,
    fallback: StreamError,
) -> Result<(), StreamError> {
    if original.is_some() {
        Err(original_failure(original, fallback))
    } else {
        Ok(())
    }
}
fn original_failure(original: Option<StreamError>, fallback: StreamError) -> StreamError {
    original.map_or(fallback, |mut native| {
        // Native prefix is encrypted wire bytes. Preserve uncertainty/code,
        // never misreport those units as accepted application plaintext.
        native.may_have_applied |= native.accepted_prefix_bytes != 0;
        native.accepted_prefix_bytes = 0;
        native
    })
}
impl Transport {
    pub fn tcp(tcp: TcpStream) -> Self {
        Self {
            wire: Wire::Tcp(Arc::new(tcp)),
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
            wire: Wire::Tcp(Arc::new(tcp)),
            tls: Some(Mutex::new(TlsState {
                connection,
                handshake_read: 0,
                handshake_write: 0,
            })),
            _tls_configuration: Some(config),
        })
    }
    #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
    pub fn protected(
        socket: Arc<crate::kernel::native::StreamSocket>,
        config: Option<Arc<crate::tls::InstalledTls>>,
        name: String,
    ) -> Result<Self, StreamError> {
        let tls = match &config {
            Some(config) => {
                let name = rustls::pki_types::ServerName::try_from(name).map_err(|_| failure())?;
                let mut connection =
                    rustls::ClientConnection::new(Arc::clone(&config.config), name)
                        .map_err(|_| failure())?;
                connection.set_buffer_limit(Some(crate::tls::WRITE_BUFFER_BYTES));
                Some(Mutex::new(TlsState {
                    connection,
                    handshake_read: 0,
                    handshake_write: 0,
                }))
            }
            None => None,
        };
        Ok(Self {
            wire: Wire::Protected(socket),
            tls,
            _tls_configuration: config,
        })
    }
    pub async fn ready(&self, interest: Interest) -> io::Result<Readiness> {
        match &self.wire {
            Wire::Tcp(tcp) => {
                let ready = tcp.ready(interest).await?;
                Ok(Readiness {
                    readable: ready.is_readable(),
                    writable: ready.is_writable(),
                    read_closed: ready.is_read_closed(),
                    write_closed: ready.is_write_closed(),
                })
            }
            #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
            Wire::Protected(socket) => {
                let bits = socket.ready(interest).await?;
                Ok(Readiness {
                    readable: bits & 1 != 0,
                    writable: bits & 2 != 0,
                    read_closed: bits & 4 != 0,
                    write_closed: bits & 8 != 0,
                })
            }
        }
    }
    pub async fn readable(&self) -> io::Result<()> {
        self.ready(Interest::READABLE).await.map(|_| ())
    }
    pub async fn writable(&self) -> io::Result<()> {
        self.ready(Interest::WRITABLE).await.map(|_| ())
    }
    pub fn shutdown_send(&self) -> Result<Option<()>, StreamError> {
        match &self.wire {
            Wire::Tcp(tcp) => socket2::SockRef::from(tcp.as_ref())
                .shutdown(std::net::Shutdown::Write)
                .map(|()| Some(()))
                .map_err(|_| error(StreamErrorCode::IoFailed)),
            #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
            Wire::Protected(socket) => socket.shutdown_send(),
        }
    }
    pub fn protected_owner(&self) -> bool {
        match &self.wire {
            Wire::Tcp(_) => false,
            #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
            Wire::Protected(_) => true,
        }
    }
    pub fn protected_retired(&self) -> bool {
        match &self.wire {
            Wire::Tcp(_) => false,
            #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
            Wire::Protected(socket) => socket.physically_retired(),
        }
    }
    pub fn retire_step(&self) -> bool {
        match &self.wire {
            Wire::Tcp(_) => true, // Historical host Drop only, NOT kernel final-free proof.
            #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
            Wire::Protected(socket) => socket.retire_step(),
        }
    }
    pub fn maintenance(&self) {
        #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
        if let Wire::Protected(socket) = &self.wire {
            socket.maintenance();
        }
    }
    #[cfg(test)]
    pub fn host_tcp(&self) -> Option<&Arc<TcpStream>> {
        match &self.wire {
            Wire::Tcp(tcp) => Some(tcp),
            #[cfg(target_os = "linux")]
            Wire::Protected(_) => None,
        }
    }
    pub fn host_tls(&self) -> bool {
        self.tls.is_some()
    }

    // Flush only already accepted ciphertext. WouldBlock yields to this same
    // original socket; it never restarts a plaintext write or handshake.
    fn flush(connection: &mut rustls::ClientConnection, tcp: &Wire) -> Result<(), StreamError> {
        while connection.wants_write() {
            let mut original = None;
            let written = connection.write_tls(&mut SocketIo {
                tcp,
                original: &mut original,
            });
            reject_original_fault(original, error(StreamErrorCode::IoFailed))?;
            match written {
                Ok(0) => return Err(error(StreamErrorCode::IoFailed)),
                Ok(_) => {}
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => break,
                Err(_) => return Err(original_failure(original, error(StreamErrorCode::IoFailed))),
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
            let mut original = None;
            let written = connection.write_tls(&mut LimitedWrite {
                tcp: &self.wire,
                remaining: 32 * 1024 - *handshake_write,
                original: &mut original,
            });
            reject_original_fault(original, failure())?;
            match written {
                Ok(0) => return Err(failure()),
                Ok(count) => {
                    *handshake_write += count;
                    if *handshake_write > 32 * 1024 {
                        return Err(error(StreamErrorCode::Exhausted));
                    }
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => break,
                Err(_) => return Err(original_failure(original, failure())),
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
        let mut original = None;
        let read = {
            let mut input = LimitedRead {
                tcp: &self.wire,
                remaining: 32 * 1024 - *handshake_read,
                original: &mut original,
            };
            connection.read_tls(&mut input)
        };
        reject_original_fault(original, failure())?;
        match read {
            Ok(0) => return Err(failure()),
            Ok(count) => {
                *handshake_read += count;
                connection.process_new_packets().map_err(|_| failure())?;
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                return Ok(Some(Interest::READABLE))
            }
            Err(_) => return Err(original_failure(original, failure())),
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
            return self.wire.read(output);
        };
        let mut state = tls.lock().map_err(|_| failure())?;
        let connection = &mut state.connection;
        match connection.reader().read(output) {
            Ok(count) => return Ok(Some(count)),
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {}
            Err(_) => return Err(failure()),
        }
        let mut original = None;
        let read = connection.read_tls(&mut SocketIo {
            tcp: &self.wire,
            original: &mut original,
        });
        reject_original_fault(original, failure())?;
        match read {
            Ok(_) => {
                connection.process_new_packets().map_err(|_| failure())?;
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => return Ok(None),
            Err(_) => return Err(original_failure(original, failure())),
        }
        Self::flush(connection, &self.wire)?;
        match connection.reader().read(output) {
            Ok(count) => Ok(Some(count)),
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => Ok(None),
            Err(_) => Err(failure()),
        }
    }

    pub fn try_write(&self, input: &[u8]) -> Result<Option<usize>, StreamError> {
        let Some(tls) = &self.tls else {
            return self.wire.write(input);
        };
        let mut state = tls.lock().map_err(|_| failure())?;
        let connection = &mut state.connection;
        Self::flush(connection, &self.wire)?;
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
        if let Err(mut error) = Self::flush(connection, &self.wire) {
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
        Self::flush(&mut state.connection, &self.wire)?;
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

#[cfg(test)]
mod tests {
    use super::{original_failure, reject_original_fault, LimitedRead, Wire};

    #[test]
    fn private_wire_fault_keeps_uncertainty_without_ciphertext_as_plaintext_prefix() {
        let fallback = crate::error(crate::StreamErrorCode::TlsFailed);
        let mut native = crate::error(crate::StreamErrorCode::IoFailed);
        native.accepted_prefix_bytes = 7; // Actual raw wire units, not plaintext.
        let projected = original_failure(Some(native), fallback);
        assert_eq!(projected.code, native.code);
        assert!(projected.may_have_applied);
        assert_eq!(projected.accepted_prefix_bytes, 0);
        let unknown = crate::error(crate::StreamErrorCode::Uncertain).uncertain(true);
        assert_eq!(original_failure(Some(unknown), fallback), unknown);
        assert_eq!(original_failure(None, fallback), fallback); // Historical host path.
                                                                // Even if the std::io consumer reports progress after observing a
                                                                // private native failure, that call must refuse before matching Ok.
        let masked: std::io::Result<usize> = Ok(7);
        assert!(reject_original_fault(Some(native), fallback)
            .map(|()| masked)
            .is_err());
        assert!(reject_original_fault(None, fallback).is_ok());
    }
    use std::io::Read;
    use tokio::{io::AsyncWriteExt, net::TcpListener};

    #[tokio::test]
    async fn repeated_handshake_reads_share_one_original_encrypted_input_ceiling() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let (client, (mut peer, _)) = tokio::try_join!(
            tokio::net::TcpStream::connect(listener.local_addr().unwrap()),
            listener.accept()
        )
        .unwrap();
        peer.write_all(b"ABCDEFGH").await.unwrap();
        client.readable().await.unwrap();
        let wire = Wire::Tcp(std::sync::Arc::new(client));
        let mut original = None;
        let mut limited = LimitedRead {
            tcp: &wire,
            remaining: 4,

            original: &mut original,
        };
        let mut first = [0; 2];
        assert_eq!(limited.read(&mut first).unwrap(), 2);
        assert_eq!(&first, b"AB");
        let mut second = [0; 4];
        assert_eq!(limited.read(&mut second).unwrap(), 2);
        assert_eq!(&second[..2], b"CD");
        assert_eq!(limited.remaining, 0);
        assert_eq!(limited.read(&mut second).unwrap(), 0);
        assert_eq!(wire.try_read(&mut second, &mut None).unwrap(), 4);
        assert_eq!(&second, b"EFGH");
    }
}
