//! One private precharged observation handle. Every result still quarantines.
use super::{error, ReadyExpiry, Resource, StreamError, StreamErrorCode};
use latent_capabilities::broker::pools::{ProviderMetadata, ProviderPools};
use rustix::event::{poll, PollFd, PollFlags, Timespec};
use std::{
    fs::File,
    io::Read,
    time::{Duration, Instant},
};

const MAGIC: u32 = 0x4c53_4652;
const VERSION: u32 = 1;
const RETURNED: u32 = 1;
pub(super) const WIRE_BYTES: usize = 48;
const METADATA_BYTES: usize = 4096;
const MAX_INTERRUPTS: usize = 16;
const MAX_WAIT: Duration = Duration::from_secs(20);

// No constructor or value escapes this module. A codec match alone cannot
// create this affine fact; only the actual protected observation read below.
struct RootReturned;

pub(super) fn observe_after_original_close(resource: &mut Resource) -> bool {
    if resource.descriptor.is_some() {
        return false;
    }
    let Some(observation) = resource.retirement.as_mut() else {
        return false;
    };
    let Some(_returned) = observation.read_original_return() else {
        return false;
    };
    // Both the protected observation and bank charge come from THIS Resource.
    // read_original_return destroyed its observer File before returning. The
    // proof and bank never leave this private flow or become caller authority.
    drop(resource.bank.take());
    true
}

pub(super) struct Owner {
    file: Option<File>,
    expiry: Option<ReadyExpiry>,
    deadline: Instant,
    // LAST: closing the file does NOT release this charge. The whole Owner
    // remains in the original quarantined Resource, including VFS uncertainty.
    _metadata: ProviderMetadata,
}
const _: () = assert!(
    std::mem::size_of::<Owner>()
        + WIRE_BYTES
        + std::mem::size_of::<PollFd<'static>>()
        + std::mem::size_of::<Timespec>()
        <= METADATA_BYTES
);

impl Owner {
    pub(super) fn reserve(pools: &ProviderPools, deadline: Instant) -> Result<Self, StreamError> {
        let metadata = pools.reserve_protocol_metadata(METADATA_BYTES)?;
        Ok(Self {
            file: None,
            expiry: None,
            deadline: deadline.min(Instant::now() + MAX_WAIT),
            _metadata: metadata,
        })
    }

    pub(super) fn mint(&mut self, original: &File, expiry: ReadyExpiry) -> Result<(), StreamError> {
        if self.file.is_some() || self.expiry.is_some() || Instant::now() >= self.deadline {
            return Err(error(StreamErrorCode::Unsupported));
        }
        // Mark the immutable identity before possible entry. This original
        // precharged owner remains in the constructor's physical Attempt.
        self.expiry = Some(expiry);
        let descriptor = latent_stream_factory_native::mint(original).map_err(|failure| {
            let kind = match failure.kind() {
                std::io::ErrorKind::PermissionDenied => "PermissionDenied",
                std::io::ErrorKind::Unsupported => "Unsupported",
                _ => "Other",
            };
            eprintln!(
                "LSFRETURNDIAG stage=mint errno={} kind={kind}",
                failure.raw_os_error().unwrap_or(0)
            );
            error(StreamErrorCode::Unsupported)
        })?;
        // Infallible ownership transfer BEFORE any later failure/checkpoint.
        self.file = Some(File::from(descriptor));
        if Instant::now() >= self.deadline {
            return Err(error(StreamErrorCode::Timeout));
        }
        Ok(())
    }

    pub(super) fn abandon(&mut self) {
        drop(self.file.take());
    }

    pub(super) fn narrow_deadline(&mut self, deadline: Instant) {
        self.deadline = self.deadline.min(deadline);
    }

    fn read_original_return(&mut self) -> Option<RootReturned> {
        // File becomes a local affine owner; even unwind closes this observer.
        // The prepaid metadata stays in self/the quarantined original Resource.
        let Some(mut file) = self.file.take() else {
            return None;
        };
        let Some(expiry) = self.expiry else {
            return None;
        };
        for _ in 0..MAX_INTERRUPTS {
            let Some(remaining) = self.deadline.checked_duration_since(Instant::now()) else {
                return None;
            };
            if remaining.is_zero() {
                return None;
            }
            let timeout = Timespec {
                tv_sec: i64::try_from(remaining.as_secs()).expect("bounded twenty seconds"),
                tv_nsec: i64::from(remaining.subsec_nanos()),
            };
            let mut descriptors = [PollFd::new(&file, PollFlags::IN)];
            match poll(&mut descriptors, Some(&timeout)) {
                Err(rustix::io::Errno::INTR) => continue,
                Ok(1) => {}
                _ => return None,
            }
            if Instant::now() >= self.deadline {
                return None;
            }
            let ready = descriptors[0].revents();
            if !ready.contains(PollFlags::IN)
                || ready.intersects(PollFlags::ERR | PollFlags::HUP | PollFlags::NVAL)
            {
                return None;
            }
            // Last descriptor use above ends its immutable borrow before read.
            let mut wire = [0; WIRE_BYTES];
            return if matches!(file.read(&mut wire), Ok(WIRE_BYTES))
                && Instant::now() < self.deadline
                && terminal(&wire, expiry)
            {
                Some(RootReturned)
            } else {
                None
            };
        }
        None
    }
}

pub(super) fn terminal(wire: &[u8; WIRE_BYTES], expiry: ReadyExpiry) -> bool {
    let word =
        |offset| u32::from_le_bytes(wire[offset..offset + 4].try_into().expect("fixed wire"));
    let wide =
        |offset| u64::from_le_bytes(wire[offset..offset + 8].try_into().expect("fixed wire"));
    // Closed one-birth constructor profile: existing owner63/gen1, Root1/gen2.
    // The private FD was minted from THIS original READY file; no string or
    // caller-supplied slot/cost can construct a refund owner from this record.
    word(0) == MAGIC
        && word(4) == VERSION
        && word(8) == RETURNED
        && word(12) == 0
        && word(16) == 63
        && word(20) == 1
        && wide(24) == 1
        && wide(32) == 2
        && wide(40) == expiry.0
}
