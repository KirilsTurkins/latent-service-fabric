//! Fixed one-job compiler protocol. All lengths are little-endian and checked
//! before allocating; a successful stream contains no trailing messages.

use std::{ffi::OsString, io::Read};

use latent_core::{PlatformError, PlatformErrorCode};

use super::{profile, sandbox};

pub(crate) const WORKER_ARGUMENT: &str = "--worker-v1";
pub(crate) const CLEAN_WORKER_ARGUMENT: &str = "--worker-clean-v1";
pub(crate) const MAX_BOOTSTRAP_BYTES: usize = profile::MAX_BOOTSTRAP_BYTES;
pub(crate) const MAX_INPUT_BYTES: usize = 64 * 1024 * 1024;
pub(crate) const MAX_OUTPUT_BYTES: usize = 512 * 1024 * 1024;
pub(crate) const LAUNCH_MAGIC: &[u8; 8] = b"LSFAOTL1";
pub(crate) const READY_BYTES: usize = 8 + 32 + 2 + sandbox::PROFILE_ID.len();
const READY_MAGIC: &[u8; 8] = b"LSFAOTR1";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct WorkerOptions {
    pub parent_pid: u32,
    pub sandbox: sandbox::SandboxLimits,
    pub maximum_input_bytes: usize,
    pub maximum_output_bytes: usize,
}

impl WorkerOptions {
    pub(crate) fn validate(self) -> Result<Self, PlatformError> {
        self.sandbox.validate()?;
        if self.parent_pid == 0
            || self.parent_pid > i32::MAX as u32
            || !(1..=MAX_INPUT_BYTES).contains(&self.maximum_input_bytes)
            || !(1..=MAX_OUTPUT_BYTES).contains(&self.maximum_output_bytes)
        {
            return Err(invalid());
        }
        Ok(self)
    }

    pub(crate) fn arguments(self) -> Result<[String; 8], PlatformError> {
        self.validate()?;
        Ok([
            WORKER_ARGUMENT.to_owned(),
            self.parent_pid.to_string(),
            self.sandbox.address_space_bytes.to_string(),
            self.sandbox.cpu_seconds.to_string(),
            self.sandbox.stack_bytes.to_string(),
            self.sandbox.maximum_fds.to_string(),
            self.maximum_input_bytes.to_string(),
            self.maximum_output_bytes.to_string(),
        ])
    }

    pub(crate) fn parse(
        arguments: impl IntoIterator<Item = OsString>,
    ) -> Result<(Self, bool), PlatformError> {
        let mut arguments = arguments.into_iter();
        let clean = match arguments
            .next()
            .as_deref()
            .and_then(std::ffi::OsStr::to_str)
        {
            Some(WORKER_ARGUMENT) => false,
            Some(CLEAN_WORKER_ARGUMENT) => true,
            _ => return Err(invalid()),
        };
        let mut values = [0_u64; 7];
        for value in &mut values {
            let argument = arguments.next().ok_or_else(invalid)?;
            let text = argument.to_str().ok_or_else(invalid)?;
            if text.is_empty()
                || text.len() > 20
                || text.starts_with('0')
                || !text.bytes().all(|byte| byte.is_ascii_digit())
            {
                return Err(invalid());
            }
            *value = text.parse().map_err(|_| invalid())?;
        }
        if arguments.next().is_some() {
            return Err(invalid());
        }
        Self {
            parent_pid: u32::try_from(values[0]).map_err(|_| invalid())?,
            sandbox: sandbox::SandboxLimits {
                address_space_bytes: values[1],
                cpu_seconds: values[2],
                stack_bytes: values[3],
                maximum_fds: values[4],
            },
            maximum_input_bytes: usize::try_from(values[5]).map_err(|_| invalid())?,
            maximum_output_bytes: usize::try_from(values[6]).map_err(|_| invalid())?,
        }
        .validate()
        .map(|options| (options, clean))
    }
}

#[must_use]
pub(crate) fn readiness(engine: &[u8; 32]) -> [u8; READY_BYTES] {
    let mut output = [0_u8; READY_BYTES];
    output[..8].copy_from_slice(READY_MAGIC);
    output[8..40].copy_from_slice(engine);
    let length = u16::try_from(sandbox::PROFILE_ID.len()).expect("fixed sandbox profile length");
    output[40..42].copy_from_slice(&length.to_le_bytes());
    output[42..].copy_from_slice(sandbox::PROFILE_ID.as_bytes());
    output
}

pub(crate) fn bootstrap_length(reader: &mut impl Read) -> Result<usize, PlatformError> {
    let mut prefix = [0_u8; 4];
    reader.read_exact(&mut prefix).map_err(|_| invalid())?;
    let length = usize::try_from(u32::from_le_bytes(prefix)).map_err(|_| invalid())?;
    if !(1..=MAX_BOOTSTRAP_BYTES).contains(&length) {
        return Err(invalid());
    }
    Ok(length)
}

pub(crate) fn input_length(reader: &mut impl Read, maximum: usize) -> Result<usize, PlatformError> {
    if !(1..=MAX_INPUT_BYTES).contains(&maximum) {
        return Err(invalid());
    }
    let mut prefix = [0_u8; 8];
    reader.read_exact(&mut prefix).map_err(|_| invalid())?;
    let length = usize::try_from(u64::from_le_bytes(prefix)).map_err(|_| invalid())?;
    if length == 0 || length > maximum {
        return Err(invalid());
    }
    Ok(length)
}

pub(crate) fn body(reader: &mut impl Read, length: usize) -> Result<Vec<u8>, PlatformError> {
    if length == 0 || length > MAX_INPUT_BYTES {
        return Err(invalid());
    }
    let mut bytes = Vec::new();
    bytes.try_reserve_exact(length).map_err(|_| {
        super::error(
            PlatformErrorCode::ResourceExhausted,
            "aot-worker-buffer-limit",
        )
    })?;
    bytes.resize(length, 0);
    reader.read_exact(&mut bytes).map_err(|_| invalid())?;
    Ok(bytes)
}

pub(crate) fn end_of_input(reader: &mut impl Read) -> Result<(), PlatformError> {
    let mut extra = [0_u8; 1];
    loop {
        match reader.read(&mut extra) {
            Ok(0) => return Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => {}
            Ok(_) | Err(_) => return Err(invalid()),
        }
    }
}

fn invalid() -> PlatformError {
    super::error(
        PlatformErrorCode::InvalidArgument,
        "invalid-aot-worker-protocol",
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn options() -> WorkerOptions {
        WorkerOptions {
            parent_pid: 123,
            sandbox: sandbox::SandboxLimits::default(),
            maximum_input_bytes: 1024,
            maximum_output_bytes: 2048,
        }
    }

    #[test]
    fn arguments_are_exact_bounded_canonical_numbers() {
        let original = options();
        let arguments = original.arguments().unwrap().map(OsString::from);
        assert_eq!(
            WorkerOptions::parse(arguments.clone()).unwrap(),
            (original, false)
        );
        let mut clean = arguments.clone();
        clean[0] = CLEAN_WORKER_ARGUMENT.into();
        assert_eq!(WorkerOptions::parse(clean).unwrap(), (original, true));
        for replacement in ["", "-1", "+1", "01", "0", "18446744073709551616"] {
            let mut malformed = arguments.clone();
            malformed[1] = replacement.into();
            assert!(WorkerOptions::parse(malformed).is_err());
        }
        assert!(WorkerOptions::parse(arguments[..7].iter().cloned()).is_err());
        let mut extra = arguments.to_vec();
        extra.push("extra".into());
        assert!(WorkerOptions::parse(extra).is_err());
        assert!(WorkerOptions {
            maximum_input_bytes: MAX_INPUT_BYTES + 1,
            ..original
        }
        .validate()
        .is_err());
        assert!(WorkerOptions {
            maximum_output_bytes: MAX_OUTPUT_BYTES + 1,
            ..original
        }
        .validate()
        .is_err());
    }

    #[test]
    fn readiness_binds_actual_engine_and_exact_sandbox_profile() {
        let ready = readiness(&[7; 32]);
        assert_eq!(&ready[..8], b"LSFAOTR1");
        assert_eq!(&ready[8..40], &[7; 32]);
        assert_eq!(
            usize::from(u16::from_le_bytes(ready[40..42].try_into().unwrap())),
            sandbox::PROFILE_ID.len()
        );
        assert_eq!(&ready[42..], sandbox::PROFILE_ID.as_bytes());
        assert_ne!(ready, readiness(&[8; 32]));
    }

    #[test]
    fn frame_limits_reject_before_body_allocation_and_require_one_complete_job() {
        for length in [
            0_u32,
            u32::try_from(MAX_BOOTSTRAP_BYTES).unwrap() + 1,
            u32::MAX,
        ] {
            assert!(bootstrap_length(&mut length.to_le_bytes().as_slice()).is_err());
        }
        for length in [0_u64, 5, u64::MAX] {
            assert!(input_length(&mut length.to_le_bytes().as_slice(), 4).is_err());
        }
        assert_eq!(
            input_length(&mut 4_u64.to_le_bytes().as_slice(), 4).unwrap(),
            4
        );
        assert!(body(&mut b"abc".as_slice(), 4).is_err());
        assert_eq!(body(&mut b"abcd".as_slice(), 4).unwrap(), b"abcd");
        assert!(end_of_input(&mut b"extra".as_slice()).is_err());
        assert!(end_of_input(&mut [].as_slice()).is_ok());
    }
}
