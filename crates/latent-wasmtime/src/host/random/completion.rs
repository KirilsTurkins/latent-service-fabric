//! Exact random-byte result ownership through canonical allocation and copy.
use super::wit;
use latent_capabilities::broker::ProviderCall;
use std::mem::MaybeUninit;
use wasmtime::component::{
    __internal::{CanonicalAbiInfo, InstanceType, InterfaceType, LowerContext},
    ComponentType, Lower,
};
use zeroize::Zeroize;

type Value = Result<Vec<u8>, wit::RandomError>;
const _: () = assert!(<Value as ComponentType>::MAY_REQUIRE_REALLOC);

// This concrete type is deliberately separate from the nonallocating runtime
// completion wrapper. It cannot accept resources or arbitrary result types.
pub(super) struct Bytes {
    value: Value,
    // Fields drop in declaration order: wipe and free the actual output buffer
    // before returning the original affine call's buffer/handle allowance.
    _call: Option<ProviderCall>,
}

impl Bytes {
    pub(super) const fn new(value: Value, call: Option<ProviderCall>) -> Self {
        Self { value, _call: call }
    }
}

impl Drop for Bytes {
    fn drop(&mut self) {
        if let Ok(bytes) = &mut self.value {
            bytes.zeroize();
        }
    }
}

#[allow(
    unsafe_code,
    reason = "concrete byte-result owner forwards the pinned generated ABI without raw memory access"
)]
// SAFETY: canonical representation, type checking and allocation behavior are
// exactly Value's generated implementations. The ProviderCall is never encoded.
unsafe impl ComponentType for Bytes {
    type Lower = <Value as ComponentType>::Lower;
    const ABI: CanonicalAbiInfo = <Value as ComponentType>::ABI;
    const IS_RUST_UNIT_TYPE: bool = <Value as ComponentType>::IS_RUST_UNIT_TYPE;
    const MAY_REQUIRE_REALLOC: bool = <Value as ComponentType>::MAY_REQUIRE_REALLOC;

    fn typecheck(ty: &InterfaceType, types: &InstanceType<'_>) -> wasmtime::Result<()> {
        <Value as ComponentType>::typecheck(ty, types)
    }
}

#[allow(
    unsafe_code,
    reason = "retain exact byte allocation and affine call until both generated canonical lowering paths finish or unwind"
)]
// SAFETY: Wasmtime 48.0.6 StaticHostFn::lower_result owns the returned tuple by
// value while it invokes these methods. Both delegate unchanged to Value's
// Lower, including guest realloc and bounds/alignment checks. The host buffer
// and call therefore survive realloc, nested failure and either lowering path.
// Generated list lowering copies into guest-owned memory; no host pointer or
// resource is transferred. Only after success/error unwinds through the owned
// return value do we wipe/free the host buffer and return its original charge.
unsafe impl Lower for Bytes {
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
