//! Keep the real stream copy through both canonical list-lowering entry points.
use latent_capabilities::broker::io::IoOutputCopy;
use std::mem::MaybeUninit;
use wasmtime::component::{
    __internal::{CanonicalAbiInfo, InstanceType, InterfaceType, LowerContext},
    ComponentType, Lower,
};

pub(super) struct ChunkBytes(pub(super) IoOutputCopy);

#[allow(
    unsafe_code,
    reason = "private immutable byte owner forwards the exact pinned list<u8> ABI without raw memory access"
)]
// SAFETY: the native owner changes no canonical representation. Every ABI
// property and the type check delegate to the existing byte-slice type. The
// reservation and transfer owners never enter guest memory.
unsafe impl ComponentType for ChunkBytes {
    type Lower = <[u8] as ComponentType>::Lower;
    const ABI: CanonicalAbiInfo = <[u8] as ComponentType>::ABI;
    const IS_RUST_UNIT_TYPE: bool = <[u8] as ComponentType>::IS_RUST_UNIT_TYPE;
    const MAY_REQUIRE_REALLOC: bool = <[u8] as ComponentType>::MAY_REQUIRE_REALLOC;

    fn typecheck(ty: &InterfaceType, types: &InstanceType<'_>) -> wasmtime::Result<()> {
        <[u8] as ComponentType>::typecheck(ty, types)
    }
}

#[allow(
    unsafe_code,
    reason = "both lowering entry points borrow the original paid bytes and delegate unchanged to the pinned byte-slice implementation"
)]
// SAFETY: the existing byte-slice Lower implementation performs all guest
// allocation and destination validation. No custom memory or pointer operation
// is introduced. StaticHostFn::lower_result owns the result tuple by value
// through typed_lower_result, so its IoOutputCopy and actual Vec remain live on
// success, invalid destinations, guest realloc failures, cancellation and unwind.
unsafe impl Lower for ChunkBytes {
    fn linear_lower_to_flat<T>(
        &self,
        cx: &mut LowerContext<'_, T>,
        ty: InterfaceType,
        dst: &mut MaybeUninit<Self::Lower>,
    ) -> wasmtime::Result<()> {
        self.0.as_ref().linear_lower_to_flat(cx, ty, dst)
    }

    fn linear_lower_to_memory<T>(
        &self,
        cx: &mut LowerContext<'_, T>,
        ty: InterfaceType,
        offset: usize,
    ) -> wasmtime::Result<()> {
        self.0.as_ref().linear_lower_to_memory(cx, ty, offset)
    }
}
