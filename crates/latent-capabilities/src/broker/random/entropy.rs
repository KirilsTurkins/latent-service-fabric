use super::{RandomError, RANDOM_PROFILE};

#[cfg(feature = "test-support")]
pub trait TestEntropy: Send + Sync {
    /// Trusted test code must return promptly. Partial writes on failure are wiped.
    fn fill(&self, bytes: &mut [u8]) -> Result<(), RandomError>;
}
pub(super) enum Source {
    System,
    #[cfg(feature = "test-support")]
    Test(std::sync::Arc<dyn TestEntropy>),
}
impl Source {
    pub(super) fn profile(&self) -> &'static str {
        match self {
            Self::System => RANDOM_PROFILE,
            #[cfg(feature = "test-support")]
            Self::Test(_) => "test-random-v1",
        }
    }
    pub(super) fn fill(&self, bytes: &mut [u8]) -> Result<(), RandomError> {
        if bytes.is_empty() {
            return Ok(());
        }
        match self {
            Self::System => system(bytes),
            #[cfg(feature = "test-support")]
            Self::Test(source) => source.fill(bytes).map_err(|_| RandomError::Unavailable),
        }
    }
}

#[cfg(target_os = "linux")]
fn system(bytes: &mut [u8]) -> Result<(), RandomError> {
    // No entropy readiness wait, retries, /dev/urandom fd or insecure flag.
    // <=256 bytes avoids large-read signal/interruption semantics. An unexpected
    // short read or syscall error fails the entire operation, never a partial result.
    for chunk in bytes.chunks_mut(256) {
        let expected = chunk.len();
        let actual = rustix::rand::getrandom(chunk, rustix::rand::GetRandomFlags::NONBLOCK)
            .map_err(|_| RandomError::Unavailable)?;
        if actual != expected {
            return Err(RandomError::Unavailable);
        }
    }
    Ok(())
}
#[cfg(not(target_os = "linux"))]
fn system(bytes: &mut [u8]) -> Result<(), RandomError> {
    getrandom::fill(bytes).map_err(|_| RandomError::Unavailable)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn real_system_source_accepts_empty_small_and_maximum_buffers() {
        for length in [0, 8, 256, 4096] {
            let mut bytes = zeroize::Zeroizing::new(vec![0; length]);
            assert_eq!(Source::System.fill(&mut bytes), Ok(()));
        }
        // Deliberately no statistical randomness-quality assertion.
    }
}
