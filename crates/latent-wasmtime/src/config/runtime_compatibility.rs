use latent_core::PlatformError;
use latent_manifest::RuntimeCompatibilityProfile;

use super::{WasmtimeConfig, WASMTIME_VERSION};

impl WasmtimeConfig {
    /// Captures native host facts once during node/factory construction. The
    /// configurable `cpu_feature_set` label supplies no hardware authority.
    pub fn detected_runtime_profile(&self) -> Result<RuntimeCompatibilityProfile, PlatformError> {
        self.validate()?;
        RuntimeCompatibilityProfile::new(
            "wasmtime",
            WASMTIME_VERSION,
            env!("LATENT_WASMTIME_HOST_TARGET"),
            &detected_cpu_features(),
            self.maximum_memory_bytes,
            self.maximum_fuel,
        )
    }
}

fn detected_cpu_features() -> Vec<&'static str> {
    #[allow(unused_mut)]
    let mut features = Vec::new();
    #[cfg(target_arch = "x86_64")]
    {
        macro_rules! detect { ($($feature:tt),+ $(,)?) => { $(if std::is_x86_feature_detected!($feature) { features.push(concat!("x86_64.", $feature)); })+ }; }
        detect!(
            "sse2",
            "cmpxchg16b",
            "sse3",
            "ssse3",
            "sse4.1",
            "sse4.2",
            "popcnt",
            "avx",
            "avx2",
            "fma",
            "bmi1",
            "bmi2",
            "avx512bitalg",
            "avx512dq",
            "avx512f",
            "avx512vl",
            "avx512vbmi",
            "lzcnt"
        );
    }
    #[cfg(target_arch = "aarch64")]
    {
        macro_rules! detect { ($($feature:tt),+ $(,)?) => { $(if std::arch::is_aarch64_feature_detected!($feature) { features.push(concat!("aarch64.", $feature)); })+ }; }
        detect!("lse", "paca", "fp16", "dotprod");
    }
    features
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_facts_ignore_the_callers_cpu_label() {
        let mut config = WasmtimeConfig::default();
        let first = config.detected_runtime_profile().unwrap();
        config.cpu_feature_set = "pretend-avx512-and-future-features".into();
        assert_eq!(first, config.detected_runtime_profile().unwrap());
        assert_eq!(first.target_triple(), env!("LATENT_WASMTIME_HOST_TARGET"));
        #[cfg(target_arch = "x86_64")]
        assert!(first
            .cpu_features()
            .iter()
            .any(|value| value.as_ref() == "x86_64.sse2"));
    }
}
