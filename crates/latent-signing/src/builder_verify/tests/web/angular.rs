//! Authentication tests use format fixtures. Actual produced component/package
//! bytes are additionally required by the production Angular build gate.
use super::*;
use latent_artifacts::web::{renderer_profile_digest, WebRendererProfile};

fn observed(subject: &PackageSigningSubject) -> WebBuildObservation {
    let mut value = observation(subject);
    let (renderer, size) = subject.renderer().unwrap();
    value.build_type = ANGULAR_BUILD_TYPE.into();
    value.parameters = WebBuildRecipe::Angular(AngularBuildRecipe {
        compiler: "lsf-angular-component".into(),
        recipe_version: 1,
        renderer_profile: "angular-ssr-component-v1".into(),
        profile_digest: renderer_profile_digest(WebRendererProfile::AngularSsrComponentV1)
            .to_string(),
        renderer_digest: renderer.to_string(),
        renderer_size: size,
        max_hydration_bytes: 32768,
        lifecycle_scripts: false,
    });
    for name in [
        "node",
        "cargo",
        "rustc",
        "wasm-tools",
        "dependency-lock",
        "npm-lock",
        "npm-tree",
        "javascript-embedding",
        "async-adapter",
        "adapter-source",
        "public-wit",
        "private-wit",
        "renderer-component",
        "angular-server-bundle",
        "angular-client-bundle",
    ] {
        value.materials.push(BuildMaterial {
            name: name.into(),
            digest: renderer.to_string(),
            size,
        });
    }
    value
}

fn sign(
    signer: &LocalBuilderSigner,
    subject: &PackageSigningSubject,
    value: &WebBuildObservation,
) -> SignatureResult<ProvenanceEvidence> {
    signer.sign_web_build(
        subject,
        value,
        SignatureValidity {
            issued_at: 1000,
            expires_at: 2000,
        },
        ProvenanceLimits::default(),
    )
}

#[test]
fn angular_requires_its_own_builder_approval_and_does_not_claim_reproducibility() {
    let (signer, public, _) = signer(BUILDER);
    let subject = subject(true);
    let value = observed(&subject);
    let signed = sign(&signer, &subject, &value).unwrap();
    assert_eq!(
        verifier(&policy(&public))
            .verify_web_package(&subject, signed.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::PredicateDisallowed
    );
    let mut approved = policy(&public);
    approved["requirements"][0]["buildType"] = ANGULAR_BUILD_TYPE.into();
    let proof = verifier(&approved)
        .verify_web_package(&subject, signed.as_ref(), NOW)
        .unwrap();
    assert_eq!(proof.outputs_digest().as_str(), value.outputs_digest);
    approved["requirements"][0]["requireReproducible"] = true.into();
    assert_eq!(
        verifier(&approved)
            .verify_web_package(&subject, signed.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::SourceDisallowed
    );
}

#[test]
fn angular_recipe_rejects_missing_materials_false_profiles_and_renderer_substitution() {
    let (signer, _, _) = signer(BUILDER);
    let subject = subject(true);
    let original = observed(&subject);
    for material in &original.materials {
        let mut value = original.clone();
        value.materials.retain(|item| item.name != material.name);
        assert!(
            sign(&signer, &subject, &value).is_err(),
            "{}",
            material.name
        );
    }
    for index in 0..8 {
        let mut value = original.clone();
        let WebBuildRecipe::Angular(recipe) = &mut value.parameters else {
            unreachable!()
        };
        match index {
            0 => recipe.lifecycle_scripts = true,
            1 => recipe.max_hydration_bytes += 1,
            2 => recipe.profile_digest = format!("sha256:{}", "a".repeat(64)),
            3 => recipe.renderer_size += 1,
            4 => recipe.recipe_version += 1,
            5 => recipe.renderer_digest = format!("sha256:{}", "a".repeat(64)),
            6 => value.build_type = WEB_ASSEMBLY_BUILD_TYPE.into(),
            _ => recipe.renderer_profile = "node-process-v1".into(),
        }
        assert!(sign(&signer, &subject, &value).is_err(), "case {index}");
    }
    // Changing both the material and recipe cannot change the authenticated
    // package's actual renderer output descriptor.
    let mut value = original;
    let WebBuildRecipe::Angular(recipe) = &mut value.parameters else {
        unreachable!()
    };
    recipe.renderer_size += 1;
    value
        .materials
        .iter_mut()
        .find(|item| item.name == "renderer-component")
        .unwrap()
        .size += 1;
    assert_eq!(
        sign(&signer, &subject, &value).unwrap_err().reason(),
        SignatureFailure::SubjectMismatch
    );
}

#[test]
fn angular_parameters_are_closed_and_legacy_assembly_wire_bytes_are_preserved() {
    let original = observation(&subject(false));
    let wire = serde_json::to_value(&original).unwrap();
    assert_eq!(
        wire["parameters"],
        json!({"assembler":"lsf-web-package-assembly","recipeVersion":1,"inputMode":"explicit-supplied-files"})
    );
    assert_eq!(
        decode_web_build_observation(
            &serde_json::to_vec(&wire).unwrap(),
            ProvenanceLimits::default()
        )
        .unwrap(),
        original
    );
    let value = serde_json::to_value(observed(&subject(true))).unwrap();
    for field in value["parameters"]
        .as_object()
        .unwrap()
        .keys()
        .chain(std::iter::once(&"unknown".to_owned()))
    {
        let mut changed = value.clone();
        let parameters = changed["parameters"].as_object_mut().unwrap();
        if field == "unknown" {
            parameters.insert(field.clone(), true.into());
        } else {
            parameters.remove(field);
        }
        assert!(
            decode_web_build_observation(
                &serde_json::to_vec(&changed).unwrap(),
                ProvenanceLimits::default()
            )
            .is_err(),
            "{field}"
        );
    }
}
