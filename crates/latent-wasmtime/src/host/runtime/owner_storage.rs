//! Exact requested layout for a prepaid runtime-owner backing.
use latent_core::activation_runtime::RuntimeOwner;

/// The caller must retain the original reservation for the complete returned
/// Vec backing before calling this, until that backing is physically dropped.
#[allow(
    unsafe_code,
    reason = "the original reservation prepays this exact global owner backing"
)]
pub(super) fn allocate(capacity: usize) -> Result<Vec<RuntimeOwner>, ()> {
    let layout = std::alloc::Layout::array::<RuntimeOwner>(capacity)
        .ok()
        .filter(|layout| layout.size() != 0)
        .ok_or(())?;
    // SAFETY: the checked layout is nonzero and valid for the global
    // allocator. Allocation failure returns null instead of aborting.
    let pointer = unsafe { std::alloc::alloc(layout) }.cast::<RuntimeOwner>();
    if pointer.is_null() {
        return Err(());
    }
    // SAFETY: the pointer came from the global allocator with exactly the
    // array layout for this capacity and contains no initialized elements.
    // The resulting Vec owns that same layout and drops initialized owners
    // before releasing the backing. No operation between allocation and this
    // ownership transfer can unwind.
    Ok(unsafe { Vec::from_raw_parts(pointer, 0, capacity) })
}
