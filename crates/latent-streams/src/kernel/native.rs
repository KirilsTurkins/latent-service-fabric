//! Affine owner for the actual qualification factory descriptor. The original
//! node backing and maintenance connection survive every possible kernel entry.
//! Neither descriptor close nor a successful constructor is final retirement.
use crate::{error, StreamError, StreamErrorCode};
use latent_capabilities::broker::pools::{
    ConnectionReservation, InstalledProvider, PooledConnection, ProviderPools, StreamKernelBacking,
    StreamKernelBankCharge, StreamKernelCloseJob, StreamKernelCloseObservation,
};
use std::{fs::File, sync::Arc, time::Instant};

const MAGIC: u32 = 0x4c53_4646;
const VERSION: u32 = 2;
const BEGIN: u32 = 1;
const WAIT: u32 = 2;
const CLOSE: u32 = 3;
const READY: u32 = 2;
const CLOSED: u32 = 4;
const FRAME_BYTES: usize = 24;

mod retirement;
mod stream_dns;
mod stream_exchange;
mod stream_protocol;
mod stream_socket;
pub(crate) use stream_dns::Exchange as StreamDnsExchange;
pub(crate) use stream_exchange::Bank as StreamBank;
pub(crate) use stream_socket::Socket as StreamSocket;

struct Resource {
    descriptor: Option<File>,
    bootstrap: Option<ReadyExpiry>,
    retirement: Option<retirement::Owner>,
    bank: Option<StreamKernelBankCharge>,
    _backing: StreamKernelBacking,
}

#[derive(Clone, Copy)]
enum BankReturn {
    RetainWhole,
    ReclaimFixedBank,
}

/// Created only after the actual BEGIN/WAIT reply validated bootstrap READY.
/// This is immutable protocol identity, never a physical-retirement proof.
#[derive(Clone, Copy)]
struct ReadyExpiry(u64);

/// Must never expose a bare PooledConnection: its ordinary Drop refunds quota.
pub(crate) struct NativeOwner {
    connection: Option<PooledConnection<Resource>>,
    pools: Arc<ProviderPools>,
}
impl Drop for NativeOwner {
    fn drop(&mut self) {
        // Abandoning the observation never cancels its admitted physical work.
        // It still closes/quarantines on the original finite blocking table.
        if self.connection.is_some() {
            drop(self.begin_close());
        }
    }
}
impl NativeOwner {
    pub(crate) fn close(mut self) -> Result<StreamKernelCloseJob, StreamError> {
        self.begin_close()
    }

    pub(crate) fn close_before(
        mut self,
        deadline: Instant,
    ) -> Result<StreamKernelCloseJob, StreamError> {
        if let Some(connection) = self.connection.as_mut() {
            if let Some(observation) = connection.resource().retirement.as_mut() {
                observation.narrow_deadline(deadline);
            }
        }
        self.close()
    }

    fn begin_close(&mut self) -> Result<StreamKernelCloseJob, StreamError> {
        let connection = self
            .connection
            .take()
            .ok_or_else(|| error(StreamErrorCode::Unsupported))?;
        match self
            .pools
            .cleanup_stream_kernel_blocking_quarantined(connection, close_resource)
        {
            Ok(job) => Ok(job),
            Err((failure, connection)) => {
                // No inline close if cleanup cannot be admitted. SAME owner.
                connection.quarantine();
                Err(failure.into())
            }
        }
    }
}

struct Attempt {
    reservation: Option<ConnectionReservation<Resource>>,
    resource: Option<Resource>,
    entered: bool,
}
impl Drop for Attempt {
    fn drop(&mut self) {
        if self.entered {
            // This guard lives in the physical blocking job once entered. A
            // panic, error, deadline or lost result cannot drop its quota. An
            // unsuccessful open can itself have entered the kernel constructor.
            let mut resource = self.resource.take().expect("prepaid original backing");
            drop(resource.descriptor.take());
            if let Some(observation) = resource.retirement.as_mut() {
                observation.abandon();
            }
            self.reservation
                .take()
                .expect("original connection reservation")
                .quarantine(resource);
        }
    }
}

fn deadline_error() -> StreamError {
    error(StreamErrorCode::Timeout)
}

/// The closures are private deterministic seams for real-descriptor ownership
/// controls. The Linux caller below supplies only the fixed protected path and
/// protocol; no caller can supply a retirement assertion or alternate device.
async fn start_initialized_with<O, I>(
    pools: Arc<ProviderPools>,
    installed: &InstalledProvider,
    deadline: Instant,
    retirement: Option<retirement::Owner>,
    bank_return: BankReturn,
    open: O,
    initialize: I,
) -> Result<NativeOwner, StreamError>
where
    O: FnOnce() -> Result<File, StreamError> + Send + 'static,
    I: FnOnce(&mut Resource, Instant) -> Result<Option<ReadyExpiry>, StreamError> + Send + 'static,
{
    if Instant::now() >= deadline {
        return Err(deadline_error());
    }
    // SAME node metadata quota, before the protected open or its worker. This
    // is not an activation HostMemoryReservation or a new bootstrap ledger.
    let mut backing = pools.reserve_stream_kernel_backing()?;
    let bank = match bank_return {
        BankReturn::RetainWhole => None,
        BankReturn::ReclaimFixedBank => Some(backing.partition_original_bank()?),
    };
    let client = pools.client::<Resource>(installed, u16::MAX)?;
    let maintenance = pools.maintenance(&client, deadline, 1)?;
    let request = maintenance.begin_request()?;
    let reservation = client.reserve_maintenance_connection(&request)?;
    let mut attempt = Attempt {
        reservation: Some(reservation),
        resource: Some(Resource {
            descriptor: None,
            bootstrap: None,
            retirement,
            bank,
            _backing: backing,
        }),
        entered: false,
    };
    let physical_pools = Arc::clone(&pools);
    let job = pools
        .control_blocking_before(deadline, move || {
            request.checkpoint()?;
            if Instant::now() >= deadline {
                return Err(deadline_error());
            }
            // Arm BEFORE open, including the failing-open path.
            attempt.entered = true;
            let resource = attempt.resource.as_mut().expect("prepaid owner");
            resource.descriptor = Some(open()?);
            let bootstrap = initialize(resource, deadline)?;
            resource.bootstrap = bootstrap;
            request.checkpoint()?;
            let resource = attempt.resource.take().expect("original resource");
            let reservation = attempt.reservation.take().expect("original reservation");
            attempt.entered = false; // Both original owners move together below.
            drop(attempt); // Explicit affine handoff; no captured guard fields remain.
            let connection = match reservation.connected_retaining_on_error(resource) {
                Ok(connection) => connection,
                Err((failure, reservation, mut resource)) => {
                    drop(resource.descriptor.take());
                    reservation.quarantine(resource);
                    return Err(failure.into());
                }
            };
            Ok(NativeOwner {
                connection: Some(connection),
                pools: physical_pools,
            })
        })
        .await?;
    // Abandoning this waiter leaves the real admitted closure charged. A late
    // returned NativeOwner closes/quarantines through its affine Drop above.
    tokio::select! {
        biased;
        () = tokio::time::sleep_until(deadline.into()) => Err(deadline_error()),
        result = job.wait() => {
            let owner = result??;
            if Instant::now() >= deadline {
                drop(owner);
                Err(deadline_error())
            } else {
                Ok(owner)
            }
        }
    }
}

// Original real-descriptor ownership controls do not pretend their files spoke
// the kernel bootstrap protocol. Only Linux initialize can stamp real READY.
#[cfg(test)]
async fn start_with<O, I>(
    pools: Arc<ProviderPools>,
    installed: &InstalledProvider,
    deadline: Instant,
    open: O,
    initialize: I,
) -> Result<NativeOwner, StreamError>
where
    O: FnOnce() -> Result<File, StreamError> + Send + 'static,
    I: FnOnce(&mut File, Instant) -> Result<(), StreamError> + Send + 'static,
{
    start_initialized_with(
        pools,
        installed,
        deadline,
        None,
        BankReturn::RetainWhole,
        open,
        move |resource, deadline| {
            initialize(
                resource.descriptor.as_mut().expect("actual descriptor"),
                deadline,
            )
            .map(|()| None)
        },
    )
    .await
}

fn frame(operation: u32, expiry: u64) -> [u8; FRAME_BYTES] {
    let mut result = [0; FRAME_BYTES];
    result[0..4].copy_from_slice(&MAGIC.to_le_bytes());
    result[4..8].copy_from_slice(&VERSION.to_le_bytes());
    result[8..12].copy_from_slice(&operation.to_le_bytes());
    result[16..24].copy_from_slice(&expiry.to_le_bytes());
    result
}

fn status_phase(bytes: &[u8; FRAME_BYTES], expiry: u64) -> Result<u32, StreamError> {
    let word =
        |offset| u32::from_le_bytes(bytes[offset..offset + 4].try_into().expect("fixed frame"));
    if word(0) != MAGIC
        || word(4) != VERSION
        || word(12) != 0
        || u64::from_le_bytes(bytes[16..24].try_into().expect("fixed expiry")) != expiry
    {
        return Err(error(StreamErrorCode::Unsupported));
    }
    Ok(word(8))
}

fn status(bytes: &[u8; FRAME_BYTES], expiry: u64) -> Result<u32, StreamError> {
    match status_phase(bytes, expiry)? {
        state @ (1 | READY) => Ok(state),
        _ => Err(error(StreamErrorCode::Unsupported)),
    }
}

fn close_status(
    bytes: &[u8; FRAME_BYTES],
    expiry: ReadyExpiry,
) -> Result<StreamKernelCloseObservation, StreamError> {
    match status_phase(bytes, expiry.0)? {
        CLOSED => Ok(StreamKernelCloseObservation::RequestAccepted),
        _ => Err(error(StreamErrorCode::Unsupported)),
    }
}

fn close_request(file: &mut File, expiry: ReadyExpiry) -> StreamKernelCloseObservation {
    use std::io::{Read, Write};
    // Exactly one operation, no retry after a short/uncertain transfer. CLOSE
    // conserves the original expiry; the kernel permits cleanup after expiry.
    if !matches!(file.write(&frame(CLOSE, expiry.0)), Ok(FRAME_BYTES)) {
        return StreamKernelCloseObservation::Uncertain;
    }
    let mut reply = [0; FRAME_BYTES];
    if !matches!(file.read(&mut reply), Ok(FRAME_BYTES)) {
        return StreamKernelCloseObservation::Uncertain;
    }
    close_status(&reply, expiry).unwrap_or(StreamKernelCloseObservation::Uncertain)
}

fn close_resource(resource: &mut Resource) -> StreamKernelCloseObservation {
    let observation = match (resource.descriptor.as_mut(), resource.bootstrap) {
        (Some(file), Some(expiry)) => close_request(file, expiry),
        _ => StreamKernelCloseObservation::NotAttempted,
    };
    drop(resource.descriptor.take());
    if observation == StreamKernelCloseObservation::RequestAccepted
        && retirement::observe_after_original_close(resource)
    {
        // Only the new fixed partition can return its same bank charge.
        // The connection, remainder and observation owner stay quarantined.
        return StreamKernelCloseObservation::KernelRootReturned;
    }
    if let Some(retirement) = resource.retirement.as_mut() {
        retirement.abandon();
    }
    // CLOSED4 is request acceptance only. The original caller ALWAYS moves
    // this resource/connection/backing into quarantine after returning.
    observation
}

#[cfg(target_os = "linux")]
fn initialize(file: &mut File, deadline: Instant) -> Result<ReadyExpiry, StreamError> {
    use std::io::{Read, Write};
    // Sample MONOTONIC first. The subsequently measured Instant remaining time
    // makes this conversion conservative; no scheduling delay extends expiry.
    let native_now = rustix::time::clock_gettime(rustix::time::ClockId::Monotonic);
    let remaining = deadline
        .checked_duration_since(Instant::now())
        .ok_or_else(deadline_error)?;
    let base = u64::try_from(native_now.tv_sec)
        .ok()
        .and_then(|seconds| seconds.checked_mul(1_000_000_000))
        .and_then(|value| value.checked_add(u64::try_from(native_now.tv_nsec).ok()?))
        .ok_or_else(|| error(StreamErrorCode::Unsupported))?;
    let expiry = u64::try_from(remaining.as_nanos())
        .ok()
        .and_then(|value| base.checked_add(value))
        .ok_or_else(|| error(StreamErrorCode::Unsupported))?;
    let transfer = |file: &mut File, operation| {
        // One syscall per exact fixed frame: a short transfer is uncertainty,
        // never retried as a second operation or treated as successful READY.
        if file
            .write(&frame(operation, expiry))
            .map_err(|_| error(StreamErrorCode::Unsupported))?
            != FRAME_BYTES
        {
            return Err(error(StreamErrorCode::Unsupported));
        }
        let mut reply = [0; FRAME_BYTES];
        if file
            .read(&mut reply)
            .map_err(|_| error(StreamErrorCode::Unsupported))?
            != FRAME_BYTES
        {
            return Err(error(StreamErrorCode::Unsupported));
        }
        status(&reply, expiry)
    };
    let phase = transfer(file, BEGIN)?;
    if phase != READY && transfer(file, WAIT)? != READY {
        return Err(error(StreamErrorCode::Unsupported));
    }
    if Instant::now() >= deadline {
        return Err(deadline_error());
    }
    Ok(ReadyExpiry(expiry))
}

#[cfg(target_os = "linux")]
pub(crate) async fn start(
    pools: Arc<ProviderPools>,
    installed: &InstalledProvider,
    deadline: Instant,
) -> Result<NativeOwner, StreamError> {
    start_real(pools, installed, deadline, None, BankReturn::RetainWhole).await
}

/// Explicit qualification consumer for a NEW source-matched observation ABI.
/// The old constructor path above never tries this ioctl or changes its image.
#[cfg(target_os = "linux")]
pub(crate) async fn start_with_retirement_observation(
    pools: Arc<ProviderPools>,
    installed: &InstalledProvider,
    deadline: Instant,
) -> Result<NativeOwner, StreamError> {
    if Instant::now() >= deadline {
        return Err(deadline_error());
    }
    let observation = retirement::Owner::reserve(&pools, deadline).map_err(|failure| {
        eprintln!("LSFRETURNDIAG stage=reserve code={:?}", failure.code);
        failure
    })?;
    start_real(
        pools,
        installed,
        deadline,
        Some(observation),
        BankReturn::RetainWhole,
    )
    .await
}

/// Only the exact bank portion can return; no other native owner is refunded.
#[cfg(target_os = "linux")]
pub(crate) async fn start_with_bank_reclamation(
    pools: Arc<ProviderPools>,
    installed: &InstalledProvider,
    deadline: Instant,
) -> Result<NativeOwner, StreamError> {
    if Instant::now() >= deadline {
        return Err(deadline_error());
    }
    let observation = retirement::Owner::reserve(&pools, deadline)?;
    start_real(
        pools,
        installed,
        deadline,
        Some(observation),
        BankReturn::ReclaimFixedBank,
    )
    .await
}

/// Unselected normal-bank preparation. It uses the SAME protected factory,
/// original finite constructor, precharged observer and fixed bank partition.
/// No provider installation calls it until all platform gates qualify.
#[cfg(target_os = "linux")]
pub(super) async fn start_node_bank(
    pools: Arc<ProviderPools>,
    installed: &InstalledProvider,
    bootstrap_deadline: Instant,
) -> Result<NativeOwner, StreamError> {
    if Instant::now() >= bootstrap_deadline {
        return Err(deadline_error());
    }
    let observation = retirement::Owner::reserve_node(&pools, bootstrap_deadline)?;
    start_real(
        pools,
        installed,
        bootstrap_deadline,
        Some(observation),
        BankReturn::ReclaimFixedBank,
    )
    .await
}

#[cfg(target_os = "linux")]
async fn start_real(
    pools: Arc<ProviderPools>,
    installed: &InstalledProvider,
    deadline: Instant,
    retirement: Option<retirement::Owner>,
    bank_return: BankReturn,
) -> Result<NativeOwner, StreamError> {
    let observing = retirement.is_some();
    start_initialized_with(
        pools,
        installed,
        deadline,
        retirement,
        bank_return,
        move || {
            rustix::fs::open(
                c"/dev/lsf-stream-factory",
                rustix::fs::OFlags::RDWR
                    | rustix::fs::OFlags::CLOEXEC
                    | rustix::fs::OFlags::NOFOLLOW
                    | rustix::fs::OFlags::NONBLOCK,
                rustix::fs::Mode::empty(),
            )
            .map(File::from)
            .map_err(|failure| {
                if observing {
                    eprintln!("LSFRETURNDIAG stage=open errno={}", failure.raw_os_error());
                }
                error(StreamErrorCode::Unsupported)
            })
        },
        move |resource, deadline| {
            let file = resource
                .descriptor
                .as_mut()
                .expect("actual opened descriptor");
            let expiry = initialize(file, deadline).map_err(|failure| {
                if observing {
                    eprintln!("LSFRETURNDIAG stage=initialize code={:?}", failure.code);
                }
                failure
            })?;
            if let Some(observation) = resource.retirement.as_mut() {
                observation.mint(file, expiry)?;
            }
            Ok(Some(expiry))
        },
    )
    .await
}

/// Additive, uninstalled node-bootstrap ABI. The old factory path above is
/// unchanged. There is deliberately no production issuer for InstalledProfile:
/// trusted exact running-image/source/configuration authentication is still
/// required BEFORE a caller can reach this separate compiled native entry.
pub(crate) mod node_bootstrap {
    use super::{deadline_error, error, File, Instant, StreamError, StreamErrorCode};
    use latent_capabilities::broker::pools::{
        ConnectionReservation, InstalledProvider, PooledConnection, ProviderPools,
        StreamKernelCloseJob, StreamKernelCloseObservation, StreamKernelNodeBacking,
    };
    use std::{
        io::{Read, Write},
        sync::Arc,
    };

    const MAGIC: u32 = 0x4c53_4e42;
    const VERSION: u32 = 1;
    const ATTACH: u32 = 1;
    const CLOSE_RETAIN: u32 = 2;
    const REQUEST_BYTES: usize = 32;
    const REPLY_BYTES: usize = 64;
    const ABI: &str = "lsf-q35-node-bootstrap-v1";

    /// Sealed installed-image evidence, NOT an operator profile/string/boolean.
    /// No production constructor exists in this source slice, and an InstalledProvider
    /// alone cannot create it. A future trusted image loader must bind the
    /// actual running image, source/configuration and new compiled fops first.
    pub(crate) struct InstalledProfile {
        abi: &'static str,
        image: [u8; 32],
        source: [u8; 32],
        configuration: [u8; 32],
    }

    impl InstalledProfile {
        fn check(&self) -> Result<(), StreamError> {
            if self.abi != ABI
                || self.image == [0; 32]
                || self.source == [0; 32]
                || self.configuration == [0; 32]
            {
                return Err(error(StreamErrorCode::Unsupported));
            }
            Ok(())
        }
    }

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    enum Phase {
        Entering,
        AttachedUnqualified,
        ClosedRetained,
        Retained,
    }

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    struct Attachment {
        expiry: u64,
        generation: u64,
        // Exact initial native header facts, NOT the full IRQ/node geometry.
        native_bytes: u64,
        alignment: u64,
        view_bytes: u64,
    }

    fn frame(operation: u32, expiry: u64, generation: u64) -> [u8; REQUEST_BYTES] {
        let mut wire = [0; REQUEST_BYTES];
        for (offset, value) in [(0, MAGIC), (4, VERSION), (8, operation)] {
            wire[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        wire[16..24].copy_from_slice(&expiry.to_le_bytes());
        wire[24..32].copy_from_slice(&generation.to_le_bytes());
        wire
    }

    fn reply(
        bytes: &[u8],
        expiry: u64,
        expected: Option<Attachment>,
    ) -> Result<(Phase, Attachment), StreamError> {
        let refused = || error(StreamErrorCode::Unsupported);
        if bytes.len() != REPLY_BYTES {
            return Err(refused());
        }
        let word = |at| u32::from_le_bytes(bytes[at..at + 4].try_into().expect("fixed word"));
        let wide = |at| u64::from_le_bytes(bytes[at..at + 8].try_into().expect("fixed scalar"));
        let phase = match word(8) {
            2 if expected.is_none() => Phase::AttachedUnqualified,
            3 if expected.is_some() => Phase::ClosedRetained,
            4 if expected.is_some() => Phase::Retained,
            _ => return Err(refused()),
        };
        let attached = Attachment {
            expiry: wide(16),
            generation: wide(24),
            native_bytes: wide(32),
            alignment: wide(40),
            view_bytes: wide(48),
        };
        if word(0) != MAGIC || word(4) != VERSION || word(12) != 0
            || attached.expiry != expiry || attached.generation == 0
            || attached.native_bytes == 0 || attached.native_bytes > 196_608
            || !attached.alignment.is_power_of_two() || attached.alignment > 64
            || attached.view_bytes != attached.native_bytes.checked_add(63)
                .map(|n| n & !63).ok_or_else(refused)?
            || attached.view_bytes > 196_608
            || wide(56) != 0 // No funding/fit/retirement approval bit is defined.
            || expected.is_some_and(|original| original != attached)
        {
            return Err(refused());
        }
        Ok((phase, attached))
    }

    fn expiry(deadline: Instant) -> Result<u64, StreamError> {
        let now = rustix::time::clock_gettime(rustix::time::ClockId::Monotonic);
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .ok_or_else(deadline_error)?;
        u64::try_from(now.tv_sec)
            .ok()
            .and_then(|n| n.checked_mul(1_000_000_000))
            .and_then(|n| n.checked_add(u64::try_from(now.tv_nsec).ok()?))
            .and_then(|n| n.checked_add(u64::try_from(remaining.as_nanos()).ok()?))
            .ok_or_else(|| error(StreamErrorCode::Unsupported))
    }

    fn attach(file: &mut File, deadline: Instant) -> Result<Attachment, StreamError> {
        let expiry = expiry(deadline)?;
        // No retry, fallback to constructor-v2, write_all or renewed deadline.
        if file
            .write(&frame(ATTACH, expiry, 0))
            .map_err(|_| error(StreamErrorCode::Unsupported))?
            != REQUEST_BYTES
        {
            return Err(error(StreamErrorCode::Unsupported));
        }
        let mut bytes = [0; REPLY_BYTES];
        if file
            .read(&mut bytes)
            .map_err(|_| error(StreamErrorCode::Unsupported))?
            != REPLY_BYTES
        {
            return Err(error(StreamErrorCode::Unsupported));
        }
        let (_, attachment) = reply(&bytes, expiry, None)?;
        if Instant::now() >= deadline {
            return Err(deadline_error());
        }
        Ok(attachment)
    }

    struct NodeResource {
        // Descriptor cleanup precedes the actual escrow and original epoch.
        descriptor: Option<File>,
        attachment: Option<Attachment>,
        phase: Phase,
        backing: StreamKernelNodeBacking,
        installed: InstalledProvider,
        _profile: InstalledProfile,
    }

    struct Attempt {
        reservation: Option<ConnectionReservation<NodeResource>>,
        resource: Option<NodeResource>,
        entered: bool,
    }

    impl Drop for Attempt {
        fn drop(&mut self) {
            if self.entered {
                let mut value = self.resource.take().expect("original node custody");
                value.phase = Phase::Retained;
                drop(value.descriptor.take());
                self.reservation
                    .take()
                    .expect("original reservation")
                    .quarantine(value);
            }
        }
    }

    /// No bare resource or independently refundable factory share is exposed.
    /// All factory access is a call-local borrow inside this physical custody.
    pub(crate) struct Owner {
        connection: Option<PooledConnection<NodeResource>>,
        pools: Arc<ProviderPools>,
    }

    impl Owner {
        fn begin_close(&mut self) -> Result<StreamKernelCloseJob, StreamError> {
            let connection = self
                .connection
                .take()
                .ok_or_else(|| error(StreamErrorCode::Unsupported))?;
            match self
                .pools
                .cleanup_stream_kernel_blocking_quarantined(connection, close_retained)
            {
                Ok(job) => Ok(job),
                Err((failure, connection)) => {
                    connection.quarantine();
                    Err(failure.into())
                }
            }
        }
    }

    impl Drop for Owner {
        fn drop(&mut self) {
            if self.connection.is_some() {
                drop(self.begin_close());
            }
        }
    }

    fn close_retained(value: &mut NodeResource) -> StreamKernelCloseObservation {
        let mut observed = StreamKernelCloseObservation::Uncertain;
        if let (Some(file), Some(original)) = (value.descriptor.as_mut(), value.attachment) {
            if matches!(
                file.write(&frame(CLOSE_RETAIN, original.expiry, original.generation)),
                Ok(REQUEST_BYTES)
            ) {
                let mut bytes = [0; REPLY_BYTES];
                if matches!(file.read(&mut bytes), Ok(REPLY_BYTES))
                    && reply(&bytes, original.expiry, Some(original)).is_ok()
                {
                    observed = StreamKernelCloseObservation::RequestAccepted;
                }
            }
        }
        value.phase = Phase::Retained;
        drop(value.descriptor.take());
        // NEVER KernelRootReturned. The complete escrow and actual original
        // epoch stay in the existing bounded quarantine after even a valid ACK.
        observed
    }

    async fn enter_with<O, I>(
        pools: Arc<ProviderPools>,
        installed: InstalledProvider,
        backing: StreamKernelNodeBacking,
        profile: InstalledProfile,
        deadline: Instant,
        open: O,
        initialize: I,
    ) -> Result<Owner, StreamError>
    where
        O: FnOnce() -> Result<File, StreamError> + Send + 'static,
        I: FnOnce(&mut File, Instant) -> Result<Attachment, StreamError> + Send + 'static,
    {
        profile.check()?;
        backing.checkpoint(&pools, &installed)?;
        if Instant::now() >= deadline {
            return Err(deadline_error());
        }
        // The caller's SINGLE original escrow moves here; no old start helper
        // and no second one-MiB acquisition occurs.
        let client = pools.client::<NodeResource>(&installed, u16::MAX)?;
        let maintenance = pools.maintenance(&client, deadline, 1)?;
        let request = maintenance.begin_request()?;
        let reservation = client.reserve_maintenance_connection(&request)?;
        let mut attempt = Attempt {
            reservation: Some(reservation),
            resource: Some(NodeResource {
                descriptor: None,
                attachment: None,
                phase: Phase::Entering,
                backing,
                installed,
                _profile: profile,
            }),
            entered: false,
        };
        let physical_pools = Arc::clone(&pools);
        let job = pools
            .control_blocking_before(deadline, move || {
                request.checkpoint()?;
                if Instant::now() >= deadline {
                    return Err(deadline_error());
                }
                let value = attempt.resource.as_mut().expect("original node resource");
                value
                    .backing
                    .checkpoint(&physical_pools, &value.installed)?;
                attempt.entered = true; // BEFORE open, including failed open/panic.
                value.descriptor = Some(open()?);
                value.attachment = Some(initialize(
                    value.descriptor.as_mut().expect("actual fd"),
                    deadline,
                )?);
                value.phase = Phase::AttachedUnqualified;
                request.checkpoint()?;
                value
                    .backing
                    .checkpoint(&physical_pools, &value.installed)?;
                let value = attempt.resource.take().expect("original node resource");
                let reservation = attempt.reservation.take().expect("original reservation");
                attempt.entered = false;
                drop(attempt);
                let connection = match reservation.connected_retaining_on_error(value) {
                    Ok(connection) => connection,
                    Err((failure, reservation, mut value)) => {
                        value.phase = Phase::Retained;
                        drop(value.descriptor.take());
                        reservation.quarantine(value);
                        return Err(failure.into());
                    }
                };
                Ok(Owner {
                    connection: Some(connection),
                    pools: physical_pools,
                })
            })
            .await?;
        tokio::select! {
            biased;
            () = tokio::time::sleep_until(deadline.into()) => Err(deadline_error()),
            result = job.wait() => {
                let owner = result??;
                if Instant::now() >= deadline {
                    drop(owner);
                    Err(deadline_error())
                } else { Ok(owner) }
            }
        }
    }

    /// A valid installed-image permit is required BEFORE reserving/entering.
    /// No production caller can obtain one yet, and no running-image check is
    /// inferred from ABI strings or a reply obtained after open.
    #[expect(
        dead_code,
        reason = "dormant uninstalled Node ABI has no production profile issuer"
    )]
    pub(crate) async fn start(
        pools: Arc<ProviderPools>,
        installed: &InstalledProvider,
        profile: InstalledProfile,
        deadline: Instant,
    ) -> Result<Owner, StreamError> {
        profile.check()?;
        let backing = pools.reserve_stream_kernel_node_backing(installed)?;
        enter_with(
            pools,
            installed.clone(),
            backing,
            profile,
            deadline,
            || {
                rustix::fs::open(
                    c"/dev/lsf-stream-factory",
                    rustix::fs::OFlags::RDWR
                        | rustix::fs::OFlags::CLOEXEC
                        | rustix::fs::OFlags::NOFOLLOW
                        | rustix::fs::OFlags::NONBLOCK,
                    rustix::fs::Mode::empty(),
                )
                .map(File::from)
                .map_err(|_| error(StreamErrorCode::Unsupported))
            },
            attach,
        )
        .await
    }

    #[cfg(test)]
    mod controls {
        use super::*;
        use crate::tests::{config, fixture::Fixture};
        use std::time::Duration;

        fn instrument_profile() -> InstalledProfile {
            // Test-only custody framing; never installed-image qualification.
            InstalledProfile {
                abi: ABI,
                image: [1; 32],
                source: [2; 32],
                configuration: [3; 32],
            }
        }

        fn observed(state: u32) -> [u8; REPLY_BYTES] {
            let mut bytes = [0; REPLY_BYTES];
            for (at, value) in [(0, MAGIC), (4, VERSION), (8, state)] {
                bytes[at..at + 4].copy_from_slice(&value.to_le_bytes());
            }
            // Synthetic framing geometry only; no native-layout/fit credit.
            for (at, value) in [(16, 123u64), (24, 7), (32, 80), (40, 8), (48, 128)] {
                bytes[at..at + 8].copy_from_slice(&value.to_le_bytes());
            }
            bytes
        }

        #[test]
        fn node_wire_refuses_old_ack_foreign_generation_and_funding_bits() {
            let good = observed(2);
            let (phase, original) = reply(&good, 123, None).unwrap();
            assert_eq!(phase, Phase::AttachedUnqualified);
            assert!(reply(&super::super::frame(super::super::CLOSED, 123), 123, None).is_err());
            assert!(reply(&observed(3), 123, None).is_err());
            assert_eq!(
                reply(&observed(3), 123, Some(original)).unwrap().0,
                Phase::ClosedRetained
            );
            assert!(reply(&observed(2), 123, Some(original)).is_err());
            for at in [0, 4, 12, 16, 24, 32, 40, 48, 56] {
                let mut changed = observed(3);
                changed[at] ^= 1;
                assert!(reply(&changed, 123, Some(original)).is_err(), "offset {at}");
            }
            let mut funded = good;
            funded[56] = 1;
            assert!(reply(&funded, 123, None).is_err());
            assert!(reply(&good[..REPLY_BYTES - 1], 123, None).is_err());
        }

        async fn snapshot(
            pools: &ProviderPools,
        ) -> latent_capabilities::broker::pools::ProviderPoolSnapshot {
            tokio::time::timeout(Duration::from_secs(5), async {
                loop {
                    if let Ok(value) = pools.snapshot() {
                        return value;
                    }
                    tokio::task::yield_now().await;
                }
            })
            .await
            .expect("original bounded provider snapshot")
        }

        async fn retained(
            pools: &ProviderPools,
        ) -> latent_capabilities::broker::pools::ProviderPoolSnapshot {
            tokio::time::timeout(Duration::from_secs(5), async {
                loop {
                    let value = snapshot(pools).await;
                    if value.failed_cleanup != 0 {
                        return value;
                    }
                    tokio::task::yield_now().await;
                }
            })
            .await
            .expect("actual owner returned to original bounded quarantine")
        }

        #[tokio::test]
        async fn node_postopen_refusal_retains_original_whole_escrow() {
            let fixture = Fixture::new(config());
            let before = snapshot(&fixture.pools).await;
            let prepared = fixture
                .pools
                .reserve_stream_kernel_node_backing(&fixture.provider.inner.installed)
                .unwrap();
            let directory = tempfile::tempdir().unwrap();
            let path = directory.path().join("node-refusal");
            let result = enter_with(
                Arc::clone(&fixture.pools),
                fixture.provider.inner.installed.clone(),
                prepared,
                instrument_profile(),
                Instant::now() + Duration::from_secs(5),
                move || File::create(path).map_err(|_| error(StreamErrorCode::IoFailed)),
                |_, _| Err(error(StreamErrorCode::Unsupported)),
            )
            .await;
            assert!(result.is_err());
            let held = retained(&fixture.pools).await;
            assert!(held.metadata_bytes >= before.metadata_bytes + 1024 * 1024);
            assert_eq!(held.connections, before.connections + 1);
        }

        #[tokio::test]
        async fn node_abandoned_waiter_keeps_custody_after_real_worker_returns() {
            let fixture = Fixture::new(config());
            let before = snapshot(&fixture.pools).await;
            let prepared = fixture
                .pools
                .reserve_stream_kernel_node_backing(&fixture.provider.inner.installed)
                .unwrap();
            let directory = tempfile::tempdir().unwrap();
            let path = directory.path().join("node-cancelled-observer");
            let (entered_send, entered_receive) = tokio::sync::oneshot::channel();
            let (release_send, release_receive) = std::sync::mpsc::channel();
            let pools = Arc::clone(&fixture.pools);
            let installed = fixture.provider.inner.installed.clone();
            let observer = tokio::spawn(async move {
                enter_with(
                    pools,
                    installed,
                    prepared,
                    instrument_profile(),
                    Instant::now() + Duration::from_secs(5),
                    move || {
                        let file =
                            File::create(path).map_err(|_| error(StreamErrorCode::IoFailed))?;
                        entered_send.send(()).unwrap();
                        release_receive
                            .recv_timeout(Duration::from_secs(5))
                            .unwrap();
                        Ok(file)
                    },
                    |_, _| {
                        // Instrument the custody handoff, not native readiness.
                        Ok(reply(&observed(2), 123, None).unwrap().1)
                    },
                )
                .await
            });
            tokio::time::timeout(Duration::from_secs(5), entered_receive)
                .await
                .unwrap()
                .unwrap();
            observer.abort();
            assert!(matches!(observer.await, Err(failure) if failure.is_cancelled()));
            release_send.send(()).unwrap();
            let held = retained(&fixture.pools).await;
            assert!(held.metadata_bytes >= before.metadata_bytes + 1024 * 1024);
            assert_eq!(held.connections, before.connections + 1);
        }
    }

    // No NodeFunding or NodeRetired type/constructor exists in this module.
}
#[cfg(test)]
mod tests;
