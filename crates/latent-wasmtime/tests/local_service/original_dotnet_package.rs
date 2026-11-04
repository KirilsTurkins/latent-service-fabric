//! The exact normal neutral packager, reused in-process for one original .NET component.
//! No compiler, guest rewrite, signing bypass or new helper executable.
#![allow(dead_code)]
use std::path::Path;

use latent_packaging::PackageBundle;
use latent_signing::{BuildObservation, ProvenanceLimits};

// These parent names and files are identical to capsule_authoring/mod.rs.
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
const TENANT: &str = "examples";
#[path = "../../../latent-policy/examples/capsule_authoring/inputs.rs"]
mod inputs;
#[path = "../../../latent-policy/examples/capsule_authoring/resource_neutral.rs"]
mod resource_neutral;

pub(super) fn load(root: &Path) -> Result<(PackageBundle, BuildObservation)> {
    let build = resource_neutral::load(root)?;
    let raw =
        latent_packaging::read_package_file(root, "normal-neutral-build-observation.json", 32768)
            .map_err(|error| error.message)?;
    let reference = latent_signing::decode_build_observation(&raw, ProvenanceLimits::default())?;
    // Fresh packaging has its own time. Every other compiler/source/component,
    // package inventory and derivation asset field must match the normal run.
    if build.observation.started_at == 0
        || build.observation.started_at != build.observation.finished_at
    {
        return Err("normal neutral packaging time is not a fresh single event".into());
    }
    let mut compared = build.observation.clone();
    compared.started_at = reference.started_at;
    compared.finished_at = reference.finished_at;
    if compared != reference {
        return Err("normal neutral packaging differs from authenticated original ancestry".into());
    }
    if build.service != "my-greeting" || build.world != "examples:greeting/service@1.0.0" {
        return Err("normal neutral package service/world mismatch".into());
    }
    Ok((build.bundle, build.observation))
}
