//! One private factory-file exchange, with no payload copies or socket FDs.
//! The original admitted native constructor owner remains affine throughout.

use super::{stream_protocol as protocol, NativeOwner};
use crate::{error, StreamError, StreamErrorCode};
use latent_capabilities::broker::pools::{ProviderMetadata, StreamKernelCloseJob};
use std::{
    io::{self, IoSlice, IoSliceMut, Read, Write},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex, TryLockError,
    },
    time::Instant,
};

pub(super) enum Payload<'a> {
    None,
    Read(&'a mut [u8]),
    Write(&'a [u8]),
}

pub(super) enum Failure {
    Framing(protocol::Rejected),
    Stopped,
    Uncertain(io::Error),
}

struct State {
    owner: Option<NativeOwner>,
    // Issued only under the SAME serialized descriptor lock. Concurrent caller
    // scheduling cannot reorder CREATE leases or reuse a consumed number.
    next_lease: u64,
}

pub(crate) struct Bank {
    // Actual file/constructor/bank charges drop before this adapter's metadata.
    owner: Mutex<State>,
    stopped: AtomicBool,
    uncertain: AtomicBool,
    _metadata: ProviderMetadata,
}

impl Bank {
    /// A successful constructor alone is insufficient: the same original
    /// Resource must own its protected observation and original bank partition.
    /// This creates no platform qualification or caller retirement certificate.
    pub fn from_ready(mut owner: NativeOwner) -> Result<Arc<Self>, (StreamError, NativeOwner)> {
        let Some(connection) = owner.connection.as_mut() else {
            return Err((error(StreamErrorCode::Unsupported), owner));
        };
        let resource = connection.resource();
        if resource.descriptor.is_none()
            || resource.bootstrap.is_none()
            || !resource
                .retirement
                .as_ref()
                .is_some_and(|owner| owner.node_lifetime())
            || resource.bank.is_none()
        {
            return Err((error(StreamErrorCode::Unsupported), owner));
        }
        // Same original pool and quota, before constructing the Arc or mutex.
        // Include the Arc's two atomic counters and worst-case data alignment;
        // the caller cannot pass an unrelated or undersized metadata token.
        let bytes = crate::connection_registry::arc_bytes::<Self>();
        let metadata = match owner.pools.reserve_protocol_metadata(bytes) {
            Ok(metadata) => metadata,
            Err(failure) => return Err((failure.into(), owner)),
        };
        Ok(Arc::new(Self {
            owner: Mutex::new(State {
                owner: Some(owner),
                next_lease: 0,
            }),
            stopped: AtomicBool::new(false),
            uncertain: AtomicBool::new(false),
            _metadata: metadata,
        }))
    }

    /// None means this attempt NEVER entered the kernel and can await the
    /// existing maintenance notification. After entry every lost/short reply
    /// poisons the entire shared exchange; no other socket can consume it.
    /// There is no await, caller callback, write_all/read_exact or retry here.
    fn entered_allowed(&self, cleanup: bool) -> Result<(), Failure> {
        if (!cleanup && self.stopped.load(Ordering::Acquire))
            || self.uncertain.load(Ordering::Acquire)
        {
            Err(Failure::Stopped)
        } else {
            Ok(())
        }
    }

    pub(super) fn reserve_metadata(&self, bytes: usize) -> Result<ProviderMetadata, StreamError> {
        let state = self.owner.try_lock().map_err(crate::snapshot_lock_error)?;
        let owner = state
            .owner
            .as_ref()
            .ok_or_else(|| error(StreamErrorCode::Revoked))?;
        owner
            .pools
            .reserve_protocol_metadata(bytes)
            .map_err(Into::into)
    }

    pub(super) fn create(
        &self,
        family: protocol::Family,
        scope: &protocol::Scope,
        expiry_nanos: u64,
        purpose: protocol::Purpose,
    ) -> Result<Option<protocol::Response>, Failure> {
        self.entered_allowed(false)?;
        let mut state = match self.owner.try_lock() {
            Ok(state) => state,
            Err(TryLockError::WouldBlock) => return Ok(None),
            Err(TryLockError::Poisoned(_)) => {
                self.uncertain.store(true, Ordering::Release);
                return Err(Failure::Stopped);
            }
        };
        self.entered_allowed(false)?;
        let lease = state.next_lease.checked_add(1).ok_or(Failure::Stopped)?;
        state.next_lease = lease; // Never replay, including an uncertain entry.
        let request = protocol::Request {
            operation: protocol::Operation::Create,
            family,
            identity: protocol::Identity {
                slot: 4,
                generation: 0,
                lease,
            },
            sequence: 1,
            expiry_nanos,
            scope,
            payload_bytes: 0,
            address: [0; 16],
            port: 0,
            purpose,
            interest: 0,
        };
        let owner = state.owner.as_mut().ok_or(Failure::Stopped)?;
        self.exchange_owned(owner, &request, Payload::None)
            .map(Some)
    }

    pub fn exchange(
        &self,
        request: &protocol::Request<'_>,
        payload: Payload<'_>,
    ) -> Result<Option<protocol::Response>, Failure> {
        let cleanup = matches!(
            request.operation,
            protocol::Operation::Close | protocol::Operation::Retired
        );
        self.entered_allowed(cleanup)?;
        let mut state = match self.owner.try_lock() {
            Ok(state) => state,
            Err(TryLockError::WouldBlock) => return Ok(None),
            Err(TryLockError::Poisoned(_)) => {
                self.uncertain.store(true, Ordering::Release);
                return Err(Failure::Stopped);
            }
        };
        self.entered_allowed(cleanup)?;
        let owner = state.owner.as_mut().ok_or(Failure::Stopped)?;
        self.exchange_owned(owner, request, payload).map(Some)
    }

    fn exchange_owned(
        &self,
        owner: &mut NativeOwner,
        request: &protocol::Request<'_>,
        payload: Payload<'_>,
    ) -> Result<protocol::Response, Failure> {
        let wire = request.encode().map_err(Failure::Framing)?;
        let (input, mut output) = match payload {
            Payload::None if request.payload_bytes == 0 => (&[][..], None),
            Payload::Read(bytes)
                if request.operation == protocol::Operation::Read
                    && bytes.len() == request.payload_bytes as usize =>
            {
                (&[][..], Some(bytes))
            }
            Payload::Write(bytes)
                if request.operation == protocol::Operation::Write
                    && bytes.len() == request.payload_bytes as usize =>
            {
                (bytes, None)
            }
            _ => return Err(Failure::Framing(protocol::Rejected::Bound)),
        };
        let Some(connection) = owner.connection.as_mut() else {
            return Err(Failure::Stopped);
        };
        let Some(file) = connection.resource().descriptor.as_mut() else {
            return Err(Failure::Stopped);
        };
        let result = (|| {
            let offered = protocol::REQUEST_BYTES + input.len();
            let sent = file.write_vectored(&[IoSlice::new(&wire), IoSlice::new(input)])?;
            if sent != offered {
                return Err(io::ErrorKind::InvalidData.into());
            }
            let mut response = [0; protocol::RESPONSE_BYTES];
            let received = match output.as_deref_mut() {
                Some(bytes) => file
                    .read_vectored(&mut [IoSliceMut::new(&mut response), IoSliceMut::new(bytes)])?,
                // read(2) deliberately remains the original constructor-v2
                // protocol. Even a header-only stream exchange uses readv(2)
                // so it reaches only the separate stream read_iter entry.
                None => file.read_vectored(&mut [IoSliceMut::new(&mut response)])?,
            };
            if received < protocol::RESPONSE_BYTES {
                return Err(io::ErrorKind::InvalidData.into());
            }
            let observed = request
                .response(&response)
                .map_err(|_| io::Error::from(io::ErrorKind::InvalidData))?;
            let copied =
                if output.is_some() && matches!(observed.status, protocol::Status::Complete) {
                    observed.count as usize
                } else {
                    0
                };
            if received != protocol::RESPONSE_BYTES + copied {
                return Err(io::ErrorKind::InvalidData.into());
            }
            Ok(observed)
        })();
        match result {
            Ok(response) => Ok(response),
            Err(fault) => {
                // No inline destruction/refund. The same NativeOwner and all
                // original context borrowers remain alive after uncertainty.
                self.uncertain.store(true, Ordering::Release);
                Err(Failure::Uncertain(fault))
            }
        }
    }

    pub fn request_stop(&self) {
        self.stopped.store(true, Ordering::Release);
    }

    /// Existing maintenance drives this once, after original operation tails
    /// have retired or been quarantined. Busy retains custody for its next
    /// bounded turn. The original cleanup job/ACK/Root-return owner is reused.
    pub fn begin_stop(&self, deadline: Instant) -> Result<Option<StreamKernelCloseJob>, Failure> {
        self.request_stop();
        let mut slot = match self.owner.try_lock() {
            Ok(slot) => slot,
            Err(TryLockError::WouldBlock) => return Ok(None),
            Err(TryLockError::Poisoned(slot)) => slot.into_inner(),
        };
        let Some(owner) = slot.owner.take() else {
            return Err(Failure::Stopped);
        };
        drop(slot); // Original cleanup/admission/Drop occurs outside bank mutex.
        owner
            .close_before(deadline)
            .map(Some)
            .map_err(|_| Failure::Stopped)
    }
}
