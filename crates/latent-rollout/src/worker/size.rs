use crate::Result;
use serde::Serialize;
use std::io::Write;

struct Counter {
    bytes: usize,
    maximum: usize,
}
impl Write for Counter {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if bytes.len() > self.maximum - self.bytes {
            return Err(std::io::ErrorKind::FileTooLarge.into());
        }
        self.bytes += bytes.len();
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
pub(crate) fn check<T: Serialize>(value: &T, maximum: usize) -> Result<()> {
    serde_json::to_writer(&mut Counter { bytes: 0, maximum }, value)
        .map_err(|_| crate::capacity("rollout-response-budget"))
}
