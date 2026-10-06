//! Own the original call through the actual canonical result-lowering boundary.
//!
//! This is deliberately restricted to the four resource-free runtime result
//! shapes. Strings, lists, resources and detached native work keep their own
//! existing physical owners; they cannot use this completion wrapper.
use super::wit;
use latent_capabilities::broker::ProviderCall;
use std::mem::MaybeUninit;
use wasmtime::component::{
    __internal::{CanonicalAbiInfo, InstanceType, InterfaceType, LowerContext},
    ComponentType, Lower,
};

pub(super) trait FixedValue: Lower {}
macro_rules! fixed_values {
    ($($value:ty),+ $(,)?) => {
        $(
            impl FixedValue for Result<$value, wit::Error> {}
            // This explicit list belongs to the frozen, resource-free WIT.
            // Reject a changed binding that requires guest allocation before
            // it can use this reviewed completion boundary.
            const _: () = assert!(
                !<Result<$value, wit::Error> as ComponentType>::MAY_REQUIRE_REALLOC
            );
        )+
    };
}
fixed_values!((), u64, wit::Token, wit::Observation);

pub(super) struct Completion<R: FixedValue> {
    value: R,
    // Wasmtime owns this return value by value while it checks the result
    // destination and lowers it. Callback return does not drop this guard.
    // The value drops first; the affine call allowance returns last, including
    // when lowering fails or the host future is discarded during cancellation.
    _call: Option<ProviderCall>,
}
impl<R: FixedValue> Completion<R> {
    pub(super) const fn new(value: R, call: Option<ProviderCall>) -> Self {
        Self { value, _call: call }
    }
}

#[allow(
    unsafe_code,
    reason = "private fixed-result wrapper forwards the exact pinned generated canonical ABI without raw memory access"
)]
// SAFETY: the lowered storage, canonical size/alignment, allocation property and
// type check are precisely R's existing ComponentType implementation. The native
// ProviderCall is not encoded and does not alter the guest representation. No
// custom layout, conversion, pointer access or Send/Sync assertion is introduced.
unsafe impl<R: FixedValue> ComponentType for Completion<R> {
    type Lower = R::Lower;
    const ABI: CanonicalAbiInfo = R::ABI;
    const IS_RUST_UNIT_TYPE: bool = R::IS_RUST_UNIT_TYPE;
    const MAY_REQUIRE_REALLOC: bool = R::MAY_REQUIRE_REALLOC;

    fn typecheck(ty: &InterfaceType, types: &InstanceType<'_>) -> wasmtime::Result<()> {
        R::typecheck(ty, types)
    }
}

#[allow(
    unsafe_code,
    reason = "private fixed-result wrapper delegates both actual lowering operations unchanged and retains the affine call until its return value drops"
)]
// SAFETY: both entry points delegate to R's established Lower implementation
// with the identical context, type and destination. That implementation alone
// initializes the lowered storage and validates guest-memory access. Wasmtime
// 48.0.3's StaticHostFn::lower_result consumes the returned tuple by value, so
// this call remains charged through success, destination rejection and unwind.
unsafe impl<R: FixedValue> Lower for Completion<R> {
    fn linear_lower_to_flat<T>(
        &self,
        cx: &mut LowerContext<'_, T>,
        ty: InterfaceType,
        dst: &mut MaybeUninit<Self::Lower>,
    ) -> wasmtime::Result<()> {
        self.value.linear_lower_to_flat(cx, ty, dst)
    }

    fn linear_lower_to_memory<T>(
        &self,
        cx: &mut LowerContext<'_, T>,
        ty: InterfaceType,
        offset: usize,
    ) -> wasmtime::Result<()> {
        self.value.linear_lower_to_memory(cx, ty, offset)
    }
}
