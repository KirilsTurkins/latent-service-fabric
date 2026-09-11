use std::hint::black_box;
use std::task::{Context, Poll};

use latent_control_store::{DeploymentApplyReceipt, DeploymentDeleteReceipt};
use latent_core::{BoxFuture, PlatformError};

use crate::standalone::start::Catalogs;

pub(super) type ApplyResult = std::result::Result<DeploymentApplyReceipt, PlatformError>;
pub(super) type DeleteResult = std::result::Result<DeploymentDeleteReceipt, PlatformError>;

// The same concrete symbol polls the actual public future and, after untimed
// validation/projection, destroys its returned owned Result. No JSON/oracle work
// occurs beneath these frames. Distinct constants prevent identical-code folding.
#[inline(never)]
pub(super) fn measured_unchanged_apply_and_drop(
    future: Option<&mut BoxFuture<'_, ApplyResult>>,
    cx: &mut Context<'_>,
    result: &mut Option<ApplyResult>,
) -> Poll<()> {
    black_box(101_u32);
    poll_or_drop(future, cx, result)
}
#[inline(never)]
pub(super) fn measured_weight_apply_and_drop(
    future: Option<&mut BoxFuture<'_, ApplyResult>>,
    cx: &mut Context<'_>,
    result: &mut Option<ApplyResult>,
) -> Poll<()> {
    black_box(102_u32);
    poll_or_drop(future, cx, result)
}
#[inline(never)]
pub(super) fn measured_delete_and_drop(
    future: Option<&mut BoxFuture<'_, DeleteResult>>,
    cx: &mut Context<'_>,
    result: &mut Option<DeleteResult>,
) -> Poll<()> {
    black_box(103_u32);
    poll_or_drop(future, cx, result)
}
#[inline(never)]
pub(super) fn measured_reapply_and_drop(
    future: Option<&mut BoxFuture<'_, ApplyResult>>,
    cx: &mut Context<'_>,
    result: &mut Option<ApplyResult>,
) -> Poll<()> {
    black_box(104_u32);
    poll_or_drop(future, cx, result)
}

#[allow(
    clippy::inline_always,
    reason = "keep the real public future poll and Result destruction inside each named allocation frame"
)]
#[inline(always)]
fn poll_or_drop<T>(
    future: Option<&mut BoxFuture<'_, T>>,
    cx: &mut Context<'_>,
    result: &mut Option<T>,
) -> Poll<()> {
    if let Some(future) = future {
        match future.as_mut().poll(cx) {
            Poll::Pending => Poll::Pending,
            Poll::Ready(value) => {
                *result = Some(value);
                Poll::Ready(())
            }
        }
    } else {
        drop(black_box(result.take()));
        Poll::Ready(())
    }
}

#[inline(never)]
pub(in crate::standalone::measurements::comparison) fn measured_catalog_reopen(
    future: &mut BoxFuture<'_, std::result::Result<Catalogs, PlatformError>>,
    cx: &mut Context<'_>,
) -> Poll<std::result::Result<Catalogs, PlatformError>> {
    black_box(105_u32);
    future.as_mut().poll(cx)
}
