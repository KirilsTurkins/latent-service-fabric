/// Retire the original host panic payload before refunding its owned slot.
/// This matches compiler-worker containment: a second destructor panic aborts
/// rather than recursively leaking payloads or stranding native ownership.
pub(super) fn catch<T>(operation: impl FnOnce() -> T) -> Result<T, ()> {
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(operation)) {
        Ok(value) => Ok(value),
        Err(payload) => {
            if let Err(_secondary) =
                std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(payload)))
            {
                std::process::abort();
            }
            Err(())
        }
    }
}
