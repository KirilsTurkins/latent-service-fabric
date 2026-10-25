//! Affine owner for the actual qualification factory descriptor. The original
//! node backing and maintenance connection survive every possible kernel entry.
//! Neither descriptor close nor a successful constructor is final retirement.
use crate::{error, StreamError, StreamErrorCode};
use latent_capabilities::broker::pools::{
    ConnectionReservation, InstalledProvider, PooledConnection, ProviderPools, StreamKernelBacking,
    StreamKernelCloseJob, StreamKernelCloseObservation,
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

struct Resource {
    descriptor: Option<File>,
    bootstrap: Option<ReadyExpiry>,
    retirement: Option<retirement::Owner>,
    _backing: StreamKernelBacking,
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
    let backing = pools.reserve_stream_kernel_backing()?;
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
    if let Some(retirement) = resource.retirement.as_mut() {
        if observation == StreamKernelCloseObservation::RequestAccepted
            && retirement.observe_after_original_close()
        {
            // This fixed observation still cannot release ANY native owner.
            return StreamKernelCloseObservation::KernelRootReturned;
        }
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
    start_real(pools, installed, deadline, None).await
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
    start_real(pools, installed, deadline, Some(observation)).await
}

#[cfg(target_os = "linux")]
async fn start_real(
    pools: Arc<ProviderPools>,
    installed: &InstalledProvider,
    deadline: Instant,
    retirement: Option<retirement::Owner>,
) -> Result<NativeOwner, StreamError> {
    let observing = retirement.is_some();
    start_initialized_with(
        pools,
        installed,
        deadline,
        retirement,
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

#[cfg(test)]
mod tests;
