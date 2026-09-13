//! The sole audited native load. Both provenance and actual byte ownership are
//! sealed before this module; a replaceable cache path is never deserialized.

use crate::aot::image_budget::{NativeImageBudget, NativeImagePermit};
use crate::aot::seal::AuthenticatedNative;
use crate::aot::supervisor::AotPreparedInput;
use crate::aot::{error, mismatch};
use latent_core::{PlatformError, PlatformErrorCode};
use std::sync::Arc;
use wasmtime::{component::Component, Engine};

pub(crate) struct LoadedNative {
    component: Component,
    image: NativeImagePermit,
}
impl LoadedNative {
    pub(crate) fn component(&self) -> &Component {
        &self.component
    }
    /// Call only after `InstancePre` owns the code and all fallible setup passed.
    /// The component handle is retired before the affine allowance is returned.
    pub(crate) fn retire_component(self) -> NativeImagePermit {
        let Self { component, image } = self;
        drop(component);
        image
    }
}

#[expect(
    clippy::needless_pass_by_value,
    reason = "each native load consumes its affine authenticated-byte proof"
)]
pub(crate) fn load(
    input: &AotPreparedInput,
    proof: AuthenticatedNative<'_>,
    engine: &Engine,
    budget: &Arc<NativeImageBudget>,
) -> Result<LoadedNative, PlatformError> {
    if !proof.belongs_to(input) {
        return Err(mismatch());
    }
    input.check_engine(engine)?;
    let image = budget.reserve(proof.bytes().len())?;
    input.check()?;
    image.record_attempt();
    let component = deserialize_authenticated(engine, &proof)?;
    // Never perform fallible post-load work with an unwrapped native owner: on
    // every later failure the native handle drops before the image allowance.
    let mut loaded = LoadedNative { component, image };
    let range = loaded.component.image_range();
    if range.end.addr().checked_sub(range.start.addr()) != Some(proof.bytes().len()) {
        return Err(load_failed());
    }
    input.check()?;
    loaded.image.loaded();
    Ok(loaded)
}

#[allow(
    unsafe_code,
    reason = "the sole native loader accepts only a private proof over authenticated immutable bytes"
)]
fn deserialize_authenticated(
    engine: &Engine,
    proof: &AuthenticatedNative<'_>,
) -> Result<Component, PlatformError> {
    // SAFETY: proof can only borrow TrustedAotOutput from the checked isolated
    // producer, or RawArtifactBytes whose complete digest/size was authenticated
    // by that same configured authority's keyed receipt. The private receipt
    // verifier requires every field of the freshly checked compatibility key;
    // load additionally checks its exact input owner and actual Engine identity.
    // The owner is immutable and retains its full byte reservation throughout
    // this call. Wasmtime 47.0.3 copies this slice into its own unique MmapVec;
    // it never references a mutable cache file. No arbitrary safe slice can mint
    // this proof. The page-rounded destination mapping was reserved before entry.
    unsafe { Component::deserialize(engine, proof.bytes()) }.map_err(|_| load_failed())
}
fn load_failed() -> PlatformError {
    error(PlatformErrorCode::CorruptArtifact, "aot-native-load-failed")
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests {
    use super::*;
    use crate::aot::{image_budget::NativeImageLimits, supervisor::InputFixture};

    fn budget() -> Arc<NativeImageBudget> {
        NativeImageBudget::new(NativeImageLimits {
            maximum_images: 1,
            maximum_image_bytes: 1024 * 1024,
            maximum_total_bytes: 1024 * 1024,
        })
        .unwrap()
    }

    #[test]
    fn real_copied_component_retains_full_mapping_until_last_pre_owner_is_retired() {
        let fixture = InputFixture::new();
        let input = fixture.read();
        let engine = fixture.engine();
        let output = fixture.output(&input, &engine);
        let budget = budget();
        let loaded = load(
            &input,
            input.authenticate_output(&output).unwrap(),
            &engine,
            &budget,
        )
        .unwrap();
        assert_eq!(budget.snapshot().loader_attempts, 1);
        assert_eq!(budget.snapshot().loading_images, 0);
        let page = rustix::param::page_size();
        assert_eq!(
            budget.snapshot().bytes,
            (output.output().len() + page - 1) & !(page - 1)
        );
        // A linked owner retains the same code after the wrapper's Component
        // handle is dropped. Transfer only after all fallible setup completes.
        let linker = wasmtime::component::Linker::<()>::new(&engine);
        let pre = linker.instantiate_pre(loaded.component()).unwrap();
        let permit = loaded.retire_component();
        drop(output);
        assert_eq!(budget.snapshot().images, 1);
        assert!(budget.reserve(1).is_err());
        drop(pre);
        drop(permit);
        assert_eq!(budget.snapshot().bytes, 0);
    }

    #[test]
    fn authenticated_cache_bytes_load_after_receipt_and_cache_root_owners_drop() {
        let fixture = InputFixture::new();
        let input = fixture.read();
        let engine = fixture.engine();
        let output = fixture.output(&input, &engine);
        let raw = fixture.raw_bytes(output.output());
        let receipt_bytes = output.receipt().to_vec();
        let receipt = input.authenticate_receipt(&receipt_bytes).unwrap();
        drop(receipt_bytes);
        drop(output);
        let proof = receipt.authenticate_bytes(&raw).unwrap();
        let budget = budget();
        let loaded = load(&input, proof, &engine, &budget).unwrap();
        drop(raw);
        assert_eq!(budget.snapshot().images, 1);
        drop(loaded);
        assert_eq!(budget.snapshot().images, 0);
    }

    #[test]
    fn proof_cannot_move_to_an_equal_key_from_another_checked_input() {
        let fixture = InputFixture::new();
        let input = fixture.read();
        let other = fixture.read();
        assert_eq!(input.key(), other.key());
        let engine = fixture.engine();
        let output = fixture.output(&input, &engine);
        let budget = budget();
        let result = load(
            &other,
            input.authenticate_output(&output).unwrap(),
            &engine,
            &budget,
        );
        assert!(matches!(result, Err(error) if error.code == PlatformErrorCode::PermissionDenied));
        assert_eq!(budget.snapshot().loader_attempts, 0);
        assert_eq!(budget.snapshot().images, 0);
    }

    #[test]
    fn revoked_proof_and_capacity_failure_do_not_enter_the_native_loader() {
        let fixture = InputFixture::new();
        let input = fixture.read();
        let engine = fixture.engine();
        let output = fixture.output(&input, &engine);
        let tiny = NativeImageBudget::new(NativeImageLimits {
            maximum_images: 1,
            maximum_image_bytes: 1,
            maximum_total_bytes: 1,
        })
        .unwrap();
        let result = load(
            &input,
            input.authenticate_output(&output).unwrap(),
            &engine,
            &tiny,
        );
        assert!(matches!(result, Err(error) if error.code == PlatformErrorCode::ResourceExhausted));
        assert_eq!(tiny.snapshot().loader_attempts, 0);
        let proof = input.authenticate_output(&output).unwrap();
        fixture.revoke();
        let budget = budget();
        assert!(load(&input, proof, &engine, &budget).is_err());
        assert_eq!(budget.snapshot().loader_attempts, 0);
    }

    #[test]
    fn actual_engine_mismatch_is_rejected_before_mapping_and_loading() {
        let fixture = InputFixture::new();
        let input = fixture.read();
        let engine = fixture.engine();
        let output = fixture.output(&input, &engine);
        let changed = crate::aot::ValidatedAotProfile::from_config(
            &crate::WasmtimeConfig {
                compiler_optimization: crate::CompilerOptimization::SpeedAndSize,
                ..Default::default()
            },
            crate::aot::AotCompilerLimits::default(),
        )
        .unwrap();
        let other = crate::aot::profile::engine_from_bootstrap(
            &changed.bootstrap().unwrap(),
            crate::aot::AotCompilerLimits::default(),
        )
        .unwrap()
        .0;
        let budget = budget();
        assert!(load(
            &input,
            input.authenticate_output(&output).unwrap(),
            &other,
            &budget
        )
        .is_err());
        assert_eq!(budget.snapshot().loader_attempts, 0);
        assert_eq!(budget.snapshot().bytes, 0);
    }
}
