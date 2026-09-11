use std::io::{self, Write};

use sha2::{Digest, Sha256};

/// Hashes only bytes accepted by the bounded destination, including short writes.
pub(super) struct Hashing<W> {
    inner: W,
    hash: Sha256,
    bytes: usize,
    limit: usize,
}

impl<W: Write> Hashing<W> {
    pub(super) fn new(inner: W, limit: usize) -> Self {
        Self {
            inner,
            hash: Sha256::new(),
            bytes: 0,
            limit,
        }
    }

    pub(super) fn finish(self) -> [u8; 64] {
        const HEX: &[u8; 16] = b"0123456789abcdef";
        let mut encoded = [0; 64];
        for (byte, pair) in self.hash.finalize().iter().zip(encoded.chunks_exact_mut(2)) {
            pair[0] = HEX[usize::from(byte >> 4)];
            pair[1] = HEX[usize::from(byte & 15)];
        }
        encoded
    }
}

impl<W: Write> Write for Hashing<W> {
    fn write(&mut self, input: &[u8]) -> io::Result<usize> {
        let next = self
            .bytes
            .checked_add(input.len())
            .filter(|next| *next <= self.limit)
            .ok_or_else(|| io::Error::other("catalog-state-byte-limit"))?;
        let written = self.inner.write(input)?;
        // Every production destination obeys Write; never slice using an unchecked count.
        let accepted = input
            .get(..written)
            .ok_or_else(|| io::Error::other("invalid catalog writer count"))?;
        self.hash.update(accepted);
        self.bytes = next - (input.len() - written);
        Ok(written)
    }

    fn flush(&mut self) -> io::Result<()> {
        self.inner.flush()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_artifacts::content_digest;

    struct ShortWriter(Vec<u8>);
    impl Write for ShortWriter {
        fn write(&mut self, input: &[u8]) -> io::Result<usize> {
            let count = input.len().min(2);
            self.0.extend_from_slice(&input[..count]);
            Ok(count)
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    #[test]
    fn short_writes_hash_exactly_once_and_over_limit_input_never_reaches_destination() {
        let mut destination = ShortWriter(Vec::new());
        let mut output = Hashing::new(&mut destination, 5);
        output.write_all(b"abcde").unwrap();
        assert_eq!(output.bytes, 5);
        assert!(output.write(b"f").is_err());
        let hash = output.finish();
        assert_eq!(destination.0, b"abcde");
        assert_eq!(
            content_digest(&destination.0)
                .0
                .as_bytes()
                .strip_prefix(b"sha256:"),
            Some(hash.as_slice())
        );
    }

    #[test]
    fn zero_limit_and_checked_count_overflow_reject_without_updating_hash() {
        let mut output = Hashing::new(io::sink(), 0);
        assert_eq!(output.write(b"").unwrap(), 0);
        assert!(output.write(b"a").is_err());
        let empty_hash = output.finish();
        assert_eq!(
            content_digest(b"").0.as_bytes().strip_prefix(b"sha256:"),
            Some(empty_hash.as_slice())
        );
        let mut output = Hashing::new(io::sink(), usize::MAX);
        output.bytes = usize::MAX;
        assert!(output.write(b"a").is_err());
        assert_eq!(output.finish(), empty_hash);
    }
}
