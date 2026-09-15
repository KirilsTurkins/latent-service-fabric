use latent_core::PlatformError;
use sha2::{Digest, Sha256};

use super::{exhausted, incompatible, invalid, model, version, CPU_FEATURES};
use crate::{
    CapsuleManifest, ExecutionBackendKind, StateModel, ThreadingModel, PHASE1_FABRIC_VERSION,
};

/// Immutable facts supplied by a trusted host adapter. Constructing this value
/// does not detect hardware; the Wasmtime adapter supplies native detected facts.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeCompatibilityProfile {
    engine: Box<str>,
    version: Box<str>,
    target: Box<str>,
    cpu: Box<[Box<str>]>,
    maximum_memory_bytes: u64,
    maximum_fuel: u64,
    renderer: Option<crate::RendererRequirement>,
    digest: [u8; 32],
}

impl RuntimeCompatibilityProfile {
    pub fn new(
        engine: &str,
        runtime_version: &str,
        target: &str,
        cpu: &[&str],
        maximum_memory_bytes: u64,
        maximum_fuel: u64,
    ) -> Result<Self, PlatformError> {
        if engine.len() > 128 || target.len() > 128 || cpu.len() > 32 {
            return Err(exhausted());
        }
        version(runtime_version)?;
        if engine != "wasmtime"
            || !model::target(target)
            || maximum_memory_bytes == 0
            || maximum_fuel == 0
        {
            return Err(invalid());
        }
        let architecture = target.split('-').next().ok_or_else(invalid)?;
        for (index, value) in cpu.iter().enumerate() {
            if value.len() > 128 {
                return Err(exhausted());
            }
            if !CPU_FEATURES.contains(value)
                || cpu[..index].contains(value)
                || value.split('.').next() != Some(architecture)
            {
                return Err(invalid());
            }
        }
        let mut cpu: Vec<Box<str>> = cpu.iter().map(|value| Box::<str>::from(*value)).collect();
        cpu.sort_unstable();
        let mut profile = Self {
            engine: engine.into(),
            version: runtime_version.into(),
            target: target.into(),
            cpu: cpu.into_boxed_slice(),
            maximum_memory_bytes,
            maximum_fuel,
            renderer: None,
            digest: [0; 32],
        };
        profile.digest = profile.fingerprint();
        Ok(profile)
    }

    #[must_use]
    pub fn digest(&self) -> &[u8; 32] {
        &self.digest
    }

    /// The trusted adapter installs a renderer only after checking its engine
    /// and resource policy. This does not grant any capsule permission to run.
    pub fn with_renderer(
        mut self,
        renderer: crate::RendererRequirement,
    ) -> Result<Self, PlatformError> {
        renderer.validate()?;
        if renderer != crate::RendererRequirement::angular() || self.version.as_ref() != "47.0.4" {
            return Err(incompatible("renderer-profile-incompatible"));
        }
        self.renderer = Some(renderer);
        self.digest = self.fingerprint();
        Ok(self)
    }
    #[must_use]
    pub fn target_triple(&self) -> &str {
        &self.target
    }
    #[must_use]
    pub fn runtime_version(&self) -> &str {
        &self.version
    }
    #[must_use]
    pub fn cpu_features(&self) -> &[Box<str>] {
        &self.cpu
    }

    /// Checks declared requirements and the implemented stateless Wasm execution
    /// profile. Import signatures remain the component/WIT validator's concern.
    pub fn check_capsule(&self, manifest: &CapsuleManifest) -> Result<(), PlatformError> {
        let requirements = &manifest.runtime_requirements;
        requirements.validate()?;
        if let Some(renderer) = &requirements.renderer {
            if self.renderer.as_ref() != Some(renderer) {
                return Err(incompatible("renderer-profile-incompatible"));
            }
            let budget = &manifest.execution.resource_budget_ceiling;
            if renderer.profile == crate::RendererProfile::AngularSsrComponentV1
                && (manifest.execution.threading != ThreadingModel::SingleThreaded
                    || budget.memory_bytes > 256 * 1024 * 1024
                    || budget.cpu_fuel > 2_000_000_000
                    || budget
                        .wall_time_limit_millis
                        .is_none_or(|value| value == 0 || value > 5000)
                    || manifest.execution.snapshot_eligible
                    || manifest.execution.fusion_eligible)
            {
                return Err(incompatible("renderer-resource-profile-incompatible"));
            }
        }
        if version(&manifest.minimum_fabric_version)? > version(PHASE1_FABRIC_VERSION)? {
            return Err(incompatible("fabric-contract-version-incompatible"));
        }
        if let Some(runtime) = &requirements.runtime {
            if runtime.engine != self.engine.as_ref()
                || version(&runtime.minimum_version)? > version(&self.version)?
            {
                return Err(incompatible("runtime-version-incompatible"));
            }
        }
        if !requirements.target_triples.is_empty()
            && !requirements
                .target_triples
                .iter()
                .any(|target| target == self.target.as_ref())
        {
            return Err(incompatible("runtime-target-incompatible"));
        }
        if requirements
            .cpu_features
            .iter()
            .any(|required| !self.cpu.iter().any(|feature| feature.as_ref() == required))
        {
            return Err(incompatible("runtime-cpu-incompatible"));
        }
        if manifest.execution.backend != ExecutionBackendKind::WasmComponent
            || !matches!(
                manifest.execution.threading,
                ThreadingModel::SingleThreaded | ThreadingModel::Reentrant
            )
            || manifest.execution.state_model != StateModel::Stateless
        {
            return Err(incompatible("runtime-execution-incompatible"));
        }
        let budget = &manifest.execution.resource_budget_ceiling;
        if budget.memory_bytes == 0
            || budget.memory_bytes > self.maximum_memory_bytes
            || budget.cpu_fuel == 0
            || budget.cpu_fuel > self.maximum_fuel
            || budget.wall_time_limit_millis == Some(0)
        {
            return Err(incompatible("runtime-resource-profile-incompatible"));
        }
        Ok(())
    }

    fn fingerprint(&self) -> [u8; 32] {
        let mut hash = Sha256::new();
        hash.update(b"latent-runtime-compatibility-v1\0");
        for value in [
            PHASE1_FABRIC_VERSION,
            self.engine.as_ref(),
            self.version.as_ref(),
            self.target.as_ref(),
        ] {
            hash.update((value.len() as u64).to_le_bytes());
            hash.update(value.as_bytes());
        }
        hash.update((self.cpu.len() as u64).to_le_bytes());
        for value in &self.cpu {
            hash.update((value.len() as u64).to_le_bytes());
            hash.update(value.as_bytes());
        }
        hash.update(self.maximum_memory_bytes.to_le_bytes());
        hash.update(self.maximum_fuel.to_le_bytes());
        if let Some(renderer) = &self.renderer {
            hash.update(b"renderer-requirement-v1\0");
            hash.update([match renderer.profile {
                crate::RendererProfile::WasmWebBufferedV1 => 0,
                crate::RendererProfile::AngularSsrComponentV1 => 1,
            }]);
            hash.update((renderer.profile_digest.len() as u64).to_le_bytes());
            hash.update(renderer.profile_digest.as_bytes());
        }
        hash.finalize().into()
    }
}
