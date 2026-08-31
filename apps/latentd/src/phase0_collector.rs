//! Native collector identity shared by the Phase 0 evidence executables.

use std::env;
use std::fs::File;
use std::io::Read as _;

use serde::Serialize;
use sha2::{Digest as _, Sha256};

const COLLECTOR_SCHEMA: &str = "latent.phase0.native-collector.v1";
const BUILD_SCHEMA: &str = "latent.phase0.native-release-build.v2";

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct NativeCollectorIdentity {
    pub schema_version: &'static str,
    pub collector: String,
    pub executable_digest: String,
    pub executable_bytes: u64,
    pub build_configuration: NativeCollectorBuildConfiguration,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[allow(clippy::struct_excessive_bools)]
pub struct NativeCollectorBuildConfiguration {
    pub schema_version: &'static str,
    pub cargo_profile: &'static str,
    pub opt_level: &'static str,
    pub debug_info: u8,
    pub debug_assertions: bool,
    pub overflow_checks: bool,
    pub lto: bool,
    pub panic: &'static str,
    pub incremental: bool,
    pub codegen_units: u16,
    pub strip: &'static str,
    pub path_remap_policy: &'static str,
    pub linker_build_id: &'static str,
    pub promoted_local_symbols: &'static str,
}

/// Hash the executable that is actually collecting this raw evidence and bind
/// it to the one native release recipe accepted by the Phase 0 runners.
pub fn native_collector_identity(
    collector: impl Into<String>,
) -> Result<NativeCollectorIdentity, String> {
    let executable = env::current_exe()
        .map_err(|error| format!("cannot resolve the native collector executable: {error}"))?;
    let mut file = File::open(&executable).map_err(|error| {
        format!(
            "cannot open native collector executable {}: {error}",
            executable.display()
        )
    })?;
    let executable_bytes = file
        .metadata()
        .map_err(|error| {
            format!(
                "cannot inspect native collector executable {}: {error}",
                executable.display()
            )
        })?
        .len();
    if executable_bytes == 0 {
        return Err("native collector executable is empty".to_owned());
    }
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 64 * 1024];
    loop {
        let read = file.read(&mut buffer).map_err(|error| {
            format!(
                "cannot hash native collector executable {}: {error}",
                executable.display()
            )
        })?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }

    Ok(NativeCollectorIdentity {
        schema_version: COLLECTOR_SCHEMA,
        collector: collector.into(),
        executable_digest: format!("sha256:{:x}", digest.finalize()),
        executable_bytes,
        build_configuration: native_build_configuration()?,
    })
}

fn native_build_configuration() -> Result<NativeCollectorBuildConfiguration, String> {
    if cfg!(debug_assertions) {
        // Unit and explicit test-mode binaries are not gate evidence. Retaining
        // their true profile keeps their JSON honest while the gate requires
        // the release recipe below.
        return Ok(NativeCollectorBuildConfiguration {
            schema_version: BUILD_SCHEMA,
            cargo_profile: "debug",
            opt_level: "0",
            debug_info: 2,
            debug_assertions: true,
            overflow_checks: true,
            lto: false,
            panic: "unwind",
            incremental: true,
            codegen_units: 256,
            strip: "none",
            path_remap_policy: "none",
            linker_build_id: "unspecified",
            promoted_local_symbols: "module-hash",
        });
    }

    let expected = [
        (
            "PHASE0_NATIVE_RELEASE_PATH_REMAP",
            "source-target-cargo-home-v1",
            option_env!("PHASE0_NATIVE_RELEASE_PATH_REMAP"),
        ),
        (
            "PHASE0_NATIVE_RELEASE_LINKER_BUILD_ID",
            "sha1",
            option_env!("PHASE0_NATIVE_RELEASE_LINKER_BUILD_ID"),
        ),
        (
            "PHASE0_NATIVE_RELEASE_PROMOTED_LOCALS",
            "source-filename",
            option_env!("PHASE0_NATIVE_RELEASE_PROMOTED_LOCALS"),
        ),
        (
            "CARGO_PROFILE_RELEASE_OPT_LEVEL",
            "3",
            option_env!("CARGO_PROFILE_RELEASE_OPT_LEVEL"),
        ),
        (
            "CARGO_PROFILE_RELEASE_DEBUG",
            "1",
            option_env!("CARGO_PROFILE_RELEASE_DEBUG"),
        ),
        (
            "CARGO_PROFILE_RELEASE_DEBUG_ASSERTIONS",
            "false",
            option_env!("CARGO_PROFILE_RELEASE_DEBUG_ASSERTIONS"),
        ),
        (
            "CARGO_PROFILE_RELEASE_OVERFLOW_CHECKS",
            "false",
            option_env!("CARGO_PROFILE_RELEASE_OVERFLOW_CHECKS"),
        ),
        (
            "CARGO_PROFILE_RELEASE_LTO",
            "false",
            option_env!("CARGO_PROFILE_RELEASE_LTO"),
        ),
        (
            "CARGO_PROFILE_RELEASE_PANIC",
            "unwind",
            option_env!("CARGO_PROFILE_RELEASE_PANIC"),
        ),
        (
            "CARGO_PROFILE_RELEASE_INCREMENTAL",
            "false",
            option_env!("CARGO_PROFILE_RELEASE_INCREMENTAL"),
        ),
        (
            "CARGO_PROFILE_RELEASE_CODEGEN_UNITS",
            "16",
            option_env!("CARGO_PROFILE_RELEASE_CODEGEN_UNITS"),
        ),
        (
            "CARGO_PROFILE_RELEASE_STRIP",
            "none",
            option_env!("CARGO_PROFILE_RELEASE_STRIP"),
        ),
    ];
    for (name, required, observed) in expected {
        if observed != Some(required) {
            return Err(format!(
                "native Phase 0 collector was not compiled with the committed release recipe: {name} expected {required:?}, observed {observed:?}"
            ));
        }
    }

    Ok(NativeCollectorBuildConfiguration {
        schema_version: BUILD_SCHEMA,
        cargo_profile: "release",
        opt_level: "3",
        debug_info: 1,
        debug_assertions: false,
        overflow_checks: false,
        lto: false,
        panic: "unwind",
        incremental: false,
        codegen_units: 16,
        strip: "none",
        path_remap_policy: "source-target-cargo-home-v1",
        linker_build_id: "sha1",
        promoted_local_symbols: "source-filename",
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_binary_retains_its_actual_collector_identity() {
        let identity = native_collector_identity("phase0-test").expect("collector identity");
        assert_eq!(identity.schema_version, COLLECTOR_SCHEMA);
        assert_eq!(identity.collector, "phase0-test");
        assert!(identity.executable_digest.starts_with("sha256:"));
        assert_eq!(identity.executable_digest.len(), 71);
        assert!(identity.executable_bytes > 0);
        assert_eq!(identity.build_configuration.schema_version, BUILD_SCHEMA);
        assert_eq!(identity.build_configuration.cargo_profile, "debug");
    }
}
