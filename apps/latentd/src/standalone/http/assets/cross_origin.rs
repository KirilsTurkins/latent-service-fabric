//! Publication-scoped static CORS on the existing bounded HTTP/asset owners.
//! No request handled here can reach activation, prerender or HTML fallback.
mod metadata;
mod response;
mod selection;
#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;

pub(in crate::standalone::http) use metadata::{admit, Candidate};
pub(in crate::standalone::http) use response::VARY;

use super::{Prepared, Request};
use crate::config::http::CrossOriginCredentials;
use crate::standalone::http::{head::Head, millis, Shared};
use latent_artifacts::PublicationRef;
use latent_core::IncomingDeadline;
use response::Policy;
use selection::Selection;
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt},
    time::{timeout_at, Instant},
};
use zeroize::Zeroize;

struct Plan {
    selection: Selection,
    policy: Policy,
    work: Work,
}
enum Work {
    Preflight,
    Asset(Request),
    Error(u16),
}

pub(in crate::standalone::http) async fn exchange<S: AsyncRead + AsyncWrite + Unpin>(
    socket: &mut S,
    shared: &Shared,
    head: Head,
    raw: &mut [u8],
    deadline: IncomingDeadline,
    close: bool,
) -> Result<bool, u16> {
    let plan = plan(shared, &head, raw);
    raw.zeroize();
    let result = match plan {
        Ok(plan) => execute(socket, shared, plan, deadline, close).await,
        Err(code) => Err(code),
    };
    let result = match result {
        Ok(close) => Ok(close),
        Err(0) => Err(0),
        Err(code) => {
            let until = write_deadline(shared, deadline);
            let _ = timeout_at(
                until,
                response::empty(socket, code, shared.settings.scheme, true, None, None),
            )
            .await;
            let _ = timeout_at(until, socket.shutdown()).await;
            Ok(true)
        }
    };
    // Keep the original exchange reservation until output/shutdown is retired.
    drop(head);
    result
}

fn plan(shared: &Shared, head: &Head, raw: &[u8]) -> Result<Plan, u16> {
    if !shared.handle.accepting() {
        return Err(503);
    }
    if head.content_length != 0 {
        return Err(400);
    }
    let candidate = head.cross_origin.as_ref().ok_or(403u16)?;
    let selection = Selection::capture(shared, head, candidate, raw)?;
    let reference = selection.reference();
    let tenant = reference.scope.tenant().ok_or(403u16)?;
    let grant = candidate.grant(
        &shared.settings.cross_origin_assets,
        head.collector.target().authority(),
        &tenant.0,
        reference.id.as_str(),
    )?;
    selection.current()?;
    let policy = Policy {
        origin: grant
            .caller(
                head.collector.target().authority(),
                &tenant.0,
                &candidate.origin,
            )
            .ok_or(403u16)?
            .to_owned(),
        credentials: grant.credentials == CrossOriginCredentials::Include,
        preflight: candidate.preflight.clone(),
    };
    let work = match selection.asset_path() {
        Ok(path) if candidate.preflight.is_some() => {
            drop(path);
            Work::Preflight
        }
        Ok(path) => match selection.request(raw, path) {
            Ok(request) => Work::Asset(request),
            Err(code) => Work::Error(code),
        },
        // A miss inside an authorized publication is a scoped, empty 404. An
        // HTML/document target is a denial, not a CORS-readable error document.
        Err(404) => Work::Error(404),
        Err(code) => return Err(code),
    };
    Ok(Plan {
        selection,
        policy,
        work,
    })
}

async fn execute<S: AsyncRead + AsyncWrite + Unpin>(
    socket: &mut S,
    shared: &Shared,
    plan: Plan,
    deadline: IncomingDeadline,
    close: bool,
) -> Result<bool, u16> {
    let Plan {
        selection,
        policy,
        work,
    } = plan;
    match work {
        Work::Asset(request) => {
            let request = selection.retain(request);
            serve(socket, shared, request, &policy, deadline, close).await
        }
        Work::Preflight | Work::Error(_) => {
            let code = match work {
                Work::Preflight => 204,
                Work::Error(code) => code,
                Work::Asset(_) => unreachable!("asset handled above"),
            };
            selection.current()?;
            let close = close || code >= 400 || !shared.handle.accepting();
            let until = write_deadline(shared, deadline);
            let result = timeout_at(
                until,
                response::empty(
                    socket,
                    code,
                    shared.settings.scheme,
                    close,
                    Some(&policy),
                    Some(selection.web()),
                ),
            )
            .await;
            if close || !matches!(&result, Ok(Ok(()))) {
                let _ = timeout_at(until, socket.shutdown()).await;
            }
            // Selected route/read authority is retained through actual output.
            drop(selection);
            result.map_err(|_| 0u16)?.map_err(|_| 0u16)?;
            Ok(close)
        }
    }
}

async fn serve<S: AsyncRead + AsyncWrite + Unpin>(
    socket: &mut S,
    shared: &Shared,
    request: Request,
    policy: &Policy,
    deadline: IncomingDeadline,
    close: bool,
) -> Result<bool, u16> {
    let reference = request.reference.clone();
    let prepared = match read(socket, shared, request, deadline).await {
        Ok(prepared) => prepared,
        Err(0) => return Err(0),
        Err(code) => {
            return scoped_error(socket, shared, &reference, policy, deadline, code).await;
        }
    };
    let tenant = reference.scope.tenant().ok_or(403u16)?;
    prepared.accept(tenant)?;
    if prepared.request.redirect.is_some()
        || matches!(
            prepared.media.as_str(),
            "text/html" | "application/xhtml+xml"
        )
    {
        return Err(403);
    }
    let close = close || !shared.handle.accepting();
    let until = write_deadline(shared, deadline);
    let result = timeout_at(
        until,
        response::asset(socket, &prepared, policy, close, shared.settings.scheme),
    )
    .await;
    if close || !matches!(&result, Ok(Ok(()))) {
        let _ = timeout_at(until, socket.shutdown()).await;
    }
    drop(prepared);
    result.map_err(|_| 0u16)?.map_err(|_| 0u16)?;
    Ok(close)
}

async fn read<S: AsyncRead + Unpin>(
    socket: &mut S,
    shared: &Shared,
    request: Request,
    deadline: IncomingDeadline,
) -> Result<Prepared, u16> {
    let store = shared.handle.0.assets.get().ok_or(503u16)?;
    if !shared.handle.accepting() {
        return Err(503);
    }
    let mut work = store.begin(request)?;
    let mut unexpected = [0u8; 1];
    tokio::select! {
        biased;
        () = tokio::time::sleep_until(deadline.monotonic().into()) => Err(0),
        // Dropping the join handle does not release a blocking reader's permit.
        _ = socket.read(&mut unexpected) => Err(0),
        result = &mut work => result.map_err(|_| 503u16)?,
    }
}

async fn scoped_error<W: AsyncWrite + Unpin>(
    socket: &mut W,
    shared: &Shared,
    reference: &PublicationRef,
    policy: &Policy,
    deadline: IncomingDeadline,
    code: u16,
) -> Result<bool, u16> {
    if matches!(code, 401 | 403) {
        return Err(403);
    }
    // A failed read has already dropped its selected owner. Reacquire only the
    // same immutable publication, never a new route or a fallback. This lets a
    // current authorized client read bounded 412/502/503 errors without treating
    // a failed/cached read as authority. Admission failure stays a generic denial.
    let store = shared.handle.0.assets.get().ok_or(503u16)?;
    let selection = store
        .repository
        .select_web_publication(reference)
        .map_err(|error| {
            let code = super::status(&error);
            if matches!(code, 400 | 401 | 403 | 404) {
                403
            } else {
                code
            }
        })?;
    selection
        .with_current(reference.scope.tenant().ok_or(403u16)?, &mut |current| {
            current.check()
        })
        .map_err(|error| super::status(&error))?;
    let until = write_deadline(shared, deadline);
    let result = timeout_at(
        until,
        response::empty(
            socket,
            code,
            shared.settings.scheme,
            true,
            Some(policy),
            Some(&selection),
        ),
    )
    .await;
    let _ = timeout_at(until, socket.shutdown()).await;
    drop(selection);
    result.map_err(|_| 0u16)?.map_err(|_| 0u16)?;
    Ok(true)
}

fn write_deadline(shared: &Shared, deadline: IncomingDeadline) -> Instant {
    Instant::from_std(deadline.monotonic())
        .min(Instant::now() + millis(shared.settings.limits.write_timeout_millis))
}
