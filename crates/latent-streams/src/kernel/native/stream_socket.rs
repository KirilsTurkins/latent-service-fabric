//! Original context loan over the one protected factory file. No socket FD.
//! The affine Scope/Request/IoLease stays in this physical transport owner.
use super::{
    stream_exchange::{Bank, Failure, Payload},
    stream_protocol as p,
};
use crate::{error, StreamError, StreamErrorCode};
use latent_capabilities::broker::pools::{ProviderMetadata, StreamKernelOwnership};
use std::{
    future::{poll_fn, Future},
    io,
    net::SocketAddr,
    sync::{Arc, Mutex},
    task::Poll,
    time::Instant,
};
use tokio::{io::Interest, sync::Notify};

struct State {
    original: StreamKernelOwnership,
    identity: Option<p::Identity>,
    sequence: u64,
    connected: bool,
    connect_started: bool,
    purpose: p::Purpose,
    closing: bool,
    close_accepted: bool,
    retired: bool,
    uncertain: bool,
    interests: u32,
}
pub(crate) struct Socket {
    state: Mutex<State>,
    changed: Notify,
    family: p::Family,
    peer: SocketAddr,
    scope: p::Scope,
    expiry: u64,
    bank: Arc<Bank>,
    _metadata: ProviderMetadata,
}
fn uncertain() -> StreamError {
    error(StreamErrorCode::Uncertain).uncertain(true)
}
fn failure(response: &p::Response, code: StreamErrorCode) -> StreamError {
    let mut result = error(code).uncertain(response.may_have_applied);
    result.accepted_prefix_bytes = response.count;
    result
}
fn boundary(state: &mut State, _fault: Failure) -> StreamError {
    state.uncertain = true;
    uncertain() // Original private errno/framing text never becomes a public proof.
}
impl Socket {
    pub fn prepare(
        bank: Arc<Bank>,
        original: StreamKernelOwnership,
        peer: SocketAddr,
        deadline: Instant,
    ) -> Result<Arc<Self>, StreamError> {
        Self::prepare_for(bank, original, peer, deadline, p::Purpose::Tcp, 96 * 1024)
    }
    pub fn prepare_dns(
        bank: Arc<Bank>,
        original: StreamKernelOwnership,
        peer: SocketAddr,
        deadline: Instant,
    ) -> Result<Arc<Self>, StreamError> {
        Self::prepare_for(
            bank,
            original,
            peer,
            deadline,
            p::Purpose::DnsUdp,
            64 * 1024,
        )
    }
    fn prepare_for(
        bank: Arc<Bank>,
        original: StreamKernelOwnership,
        peer: SocketAddr,
        deadline: Instant,
        purpose: p::Purpose,
        bytes: u64,
    ) -> Result<Arc<Self>, StreamError> {
        original.checkpoint()?;
        if original.maximum_bytes() != bytes {
            return Err(error(StreamErrorCode::Denied));
        }
        let family = if peer.is_ipv4() {
            p::Family::Ipv4
        } else {
            p::Family::Ipv6
        };
        let scope = p::Scope(*original.kernel_binding_words());
        // Bootstrap READY has completed; each original operation has its OWN
        // immutable monotonic deadline. No bootstrap timeout is renewed here.
        let now = rustix::time::clock_gettime(rustix::time::ClockId::Monotonic);
        let remaining = original
            .deadline()
            .min(deadline)
            .checked_duration_since(Instant::now())
            .ok_or_else(|| error(StreamErrorCode::Timeout))?;
        let base = u64::try_from(now.tv_sec)
            .ok()
            .and_then(|v| v.checked_mul(1_000_000_000))
            .and_then(|v| v.checked_add(u64::try_from(now.tv_nsec).ok()?))
            .ok_or_else(|| error(StreamErrorCode::InvalidState))?;
        let expiry = u64::try_from(remaining.as_nanos())
            .ok()
            .and_then(|v| base.checked_add(v))
            .ok_or_else(|| error(StreamErrorCode::InvalidState))?;
        let metadata = bank.reserve_metadata(crate::connection_registry::arc_bytes::<Self>())?;
        Ok(Arc::new(Self {
            state: Mutex::new(State {
                original,
                identity: None,
                sequence: 1,
                connected: false,
                connect_started: false,
                purpose,
                closing: false,
                close_accepted: false,
                retired: false,
                uncertain: false,
                interests: 0,
            }),
            changed: Notify::new(),
            family,
            peer,
            scope,
            expiry,
            bank,
            _metadata: metadata,
        }))
    }
    fn query(
        &self,
        state: &mut State,
        operation: p::Operation,
        payload: Payload<'_>,
        address: [u8; 16],
        port: u32,
        interest: u32,
        payload_bytes: u32,
    ) -> Result<Option<p::Response>, StreamError> {
        let cleanup = matches!(operation, p::Operation::Close | p::Operation::Retired);
        if state.uncertain && !cleanup {
            return Err(uncertain());
        }
        if !cleanup {
            state.original.checkpoint()?;
        }
        let identity = state
            .identity
            .ok_or_else(|| error(StreamErrorCode::InvalidState))?;
        let sequence = state.sequence.checked_add(1).ok_or_else(uncertain)?;
        let request = p::Request {
            operation,
            family: self.family,
            identity,
            sequence,
            expiry_nanos: self.expiry,
            scope: &self.scope,
            payload_bytes,
            address,
            port,
            purpose: if operation == p::Operation::DnsTcpFallback {
                p::Purpose::DnsTcp
            } else {
                state.purpose
            },
            interest,
        };
        match self.bank.exchange(&request, payload) {
            Ok(Some(response)) => {
                state.sequence = sequence;
                Ok(Some(response))
            }
            Ok(None) => Ok(None), // Never entered; same sequence may wait.
            Err(fault) => Err(boundary(state, fault)),
        }
    }
    pub fn connect_step(&self, peer: SocketAddr) -> Result<bool, StreamError> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if peer != self.peer || state.closing || state.uncertain {
            return Err(uncertain());
        }
        state.original.checkpoint()?;
        if state.identity.is_none() {
            // The caller has already attached this SAME Arc to its original
            // SocketOwner before possible birth; cancellation cannot refund it.
            state.original.confirm();
            let result = self
                .bank
                .create(self.family, &self.scope, self.expiry, state.purpose);
            match result {
                Ok(Some(response)) => {
                    if response.identity.slot < 4 {
                        state.identity = Some(response.identity);
                    }
                    if response.status != p::Status::Complete {
                        return Err(failure(&response, StreamErrorCode::ConnectFailed));
                    }
                }
                Ok(None) => return Ok(false),
                Err(fault) => return Err(boundary(&mut state, fault)),
            }
        }
        if state.connected {
            return Ok(true);
        }
        state.interests |= 2;
        // CONNECT is issued exactly once; later polls inspect the SAME attempt.
        let first = !state.connect_started;
        let mut address = [0; 16];
        if first {
            match peer.ip() {
                std::net::IpAddr::V4(ip) => address[..4].copy_from_slice(&ip.octets()),
                std::net::IpAddr::V6(ip) => address.copy_from_slice(&ip.octets()),
            }
        }
        let operation = if first {
            p::Operation::Connect
        } else {
            p::Operation::FinishConnect
        };
        let Some(response) = self.query(
            &mut state,
            operation,
            Payload::None,
            address,
            if first { u32::from(peer.port()) } else { 0 },
            0,
            0,
        )?
        else {
            return Ok(false);
        };
        state.connect_started = true;
        match response.status {
            p::Status::Complete => {
                state.connected = true;
                Ok(true)
            }
            p::Status::Pending => Ok(false),
            _ => Err(failure(&response, StreamErrorCode::ConnectFailed)),
        }
    }
    pub async fn connect(&self, peer: SocketAddr) -> Result<(), StreamError> {
        let notified = self.changed.notified();
        tokio::pin!(notified);
        notified.as_mut().enable();
        // No new timer/task: the original accepted IoCall's existing bounded
        // wait_current authority wake polls this SAME future during dialing.
        // Once registered, the one provider maintenance turn also drives READY.
        poll_fn(|cx| {
            match self.connect_step(peer) {
                Ok(true) => return Poll::Ready(Ok(())),
                Err(fault) => return Poll::Ready(Err(fault)),
                Ok(false) => {}
            }
            if notified.as_mut().poll(cx).is_ready() {
                notified.set(self.changed.notified());
                notified.as_mut().enable();
                cx.waker().wake_by_ref();
            }
            Poll::Pending
        })
        .await
    }
    /// One same-server transition in the SAME prepaid DNS context. The kernel
    /// keeps the original UDP physical tail paid while allocating TCP. The
    /// existing fixed-context allocator must refuse if that overlap cannot fit.
    pub fn dns_tcp_fallback(&self) -> Result<bool, StreamError> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.purpose != p::Purpose::DnsUdp || !state.connected || state.closing {
            return Err(error(StreamErrorCode::InvalidState));
        }
        let Some(response) = self.query(
            &mut state,
            p::Operation::DnsTcpFallback,
            Payload::None,
            [0; 16],
            0,
            0,
            0,
        )?
        else {
            return Ok(false);
        };
        if response.status != p::Status::Complete {
            // A failed constructor may still have born physical objects. Do
            // not resume UDP, retry TCP birth, refund or lose original custody.
            state.uncertain = true;
            return Err(failure(&response, StreamErrorCode::Uncertain));
        }
        state.purpose = p::Purpose::DnsTcp;
        state.connected = false;
        state.connect_started = false;
        Ok(true)
    }
    pub fn physically_retired(&self) -> bool {
        self.state
            .lock()
            .map(|state| state.retired)
            .unwrap_or(false)
    }
    pub fn try_read(&self, output: &mut [u8]) -> Result<Option<usize>, StreamError> {
        if output.is_empty() {
            return Ok(Some(0));
        }
        let maximum = output
            .len()
            .min(latent_capabilities::broker::network::MAXIMUM_CHUNK_BYTES);
        let output = &mut output[..maximum]; // Same caller buffer; no copy/allocation.
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if !state.connected || state.closing {
            return Err(error(StreamErrorCode::InvalidState));
        }
        let len = u32::try_from(output.len()).map_err(|_| error(StreamErrorCode::InvalidInput))?;
        let Some(response) = self.query(
            &mut state,
            p::Operation::Read,
            Payload::Read(output),
            [0; 16],
            0,
            0,
            len,
        )?
        else {
            return Ok(None);
        };
        match response.status {
            p::Status::Complete => Ok(Some(response.count as usize)),
            p::Status::Eof => Ok(Some(0)),
            p::Status::Pending => Ok(None),
            p::Status::Failed => Err(failure(&response, StreamErrorCode::IoFailed)),
        }
    }
    pub fn try_write(&self, input: &[u8]) -> Result<Option<usize>, StreamError> {
        if input.is_empty() {
            return Ok(Some(0));
        }
        let input = &input[..input
            .len()
            .min(latent_capabilities::broker::network::MAXIMUM_CHUNK_BYTES)];
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if !state.connected || state.closing {
            return Err(error(StreamErrorCode::InvalidState));
        }
        let len = u32::try_from(input.len()).map_err(|_| error(StreamErrorCode::InvalidInput))?;
        let Some(response) = self.query(
            &mut state,
            p::Operation::Write,
            Payload::Write(input),
            [0; 16],
            0,
            0,
            len,
        )?
        else {
            return Ok(None);
        };
        match response.status {
            p::Status::Complete => Ok(Some(response.count as usize)),
            p::Status::Pending if !response.may_have_applied => Ok(None),
            p::Status::Pending => {
                state.uncertain = true;
                Err(failure(&response, StreamErrorCode::Uncertain))
            }
            _ => Err(failure(&response, StreamErrorCode::IoFailed)),
        }
    }
    pub fn shutdown_send(&self) -> Result<Option<()>, StreamError> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let Some(response) = self.query(
            &mut state,
            p::Operation::ShutdownSend,
            Payload::None,
            [0; 16],
            0,
            0,
            0,
        )?
        else {
            return Ok(None); // Original bank busy; no syscall/sequence consumed.
        };
        if response.status != p::Status::Complete {
            return Err(failure(&response, StreamErrorCode::IoFailed));
        }
        Ok(Some(()))
    }
    pub fn readiness(&self, interest: Interest) -> Result<Option<u32>, StreamError> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let bits = u32::from(interest.is_readable()) | (u32::from(interest.is_writable()) << 1);
        state.interests |= bits;
        let Some(response) = self.query(
            &mut state,
            p::Operation::Ready,
            Payload::None,
            [0; 16],
            0,
            bits,
            0,
        )?
        else {
            return Ok(None);
        };
        match response.status {
            p::Status::Complete => Ok(Some(response.ready)),
            p::Status::Pending => Ok(None),
            _ => Err(failure(&response, StreamErrorCode::IoFailed)),
        }
    }
    pub async fn ready(&self, interest: Interest) -> io::Result<u32> {
        let notified = self.changed.notified();
        tokio::pin!(notified);
        notified.as_mut().enable();
        poll_fn(|cx| {
            match self.readiness(interest) {
                Ok(Some(bits)) => return Poll::Ready(Ok(bits)),
                Err(_) => return Poll::Ready(Err(io::ErrorKind::Other.into())),
                Ok(None) => {}
            }
            if notified.as_mut().poll(cx).is_ready() {
                notified.set(self.changed.notified());
                notified.as_mut().enable();
                cx.waker().wake_by_ref();
            }
            Poll::Pending
        })
        .await
    }
    pub fn retire_step(&self) -> bool {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.closing = true;
        if state.retired {
            return true;
        }
        if state.identity.is_none() {
            if state.uncertain {
                return false;
            } // Unknown birth is not never-born.
            state.retired = true;
            return true;
        } // Never born.
        if !state.close_accepted {
            match self.query(
                &mut state,
                p::Operation::Close,
                Payload::None,
                [0; 16],
                0,
                0,
                0,
            ) {
                Ok(Some(response)) if response.status == p::Status::Complete => {
                    state.close_accepted = true
                }
                _ => return false,
            }
        }
        match self.query(
            &mut state,
            p::Operation::Retired,
            Payload::None,
            [0; 16],
            0,
            0,
            0,
        ) {
            Ok(Some(response)) if response.status == p::Status::Complete => {
                state.retired = true;
                true
            }
            _ => false,
        }
    }
    pub fn maintenance(&self) {
        let (closing, interests) = {
            let state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            (state.closing, state.interests)
        };
        if closing {
            if self.retire_step() {
                self.changed.notify_waiters();
            }
        } else if interests != 0 {
            let interest = if interests == 1 {
                Interest::READABLE
            } else if interests == 2 {
                Interest::WRITABLE
            } else {
                Interest::READABLE | Interest::WRITABLE
            };
            if !matches!(self.readiness(interest), Ok(None)) {
                self.changed.notify_waiters();
            }
        }
    }
}
