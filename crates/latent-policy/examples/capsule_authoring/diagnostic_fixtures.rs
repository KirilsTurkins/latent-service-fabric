//! Exactly four preserved FF9 inputs plus one explicitly sourced diagnostic.
//! All package/report checks finish before the caller creates fixture keys.
use super::{fixtures, inputs, Result};
use latent_packaging::read_package_file;
use serde_json::Value;
use std::{collections::BTreeSet, ffi::OsString, path::Path};

const ORIGINAL_SOURCE: &str = "ff9ecd0733456bceacf5b96f14274b9c2dc0e8e6";
const ABI: &str = "sha256:3b85f790f85ab23d36e492d7bd4a04a1b8aab87fc6f67dd7d7498bcf28129d35";
const LEGACY_COMPANION: &str =
    "sha256:24a689c7166ffbdbaacefa8d7d7efe18a98d532adc94fc4392968aaab837349d";
const LEGACY_REQUIREMENTS: &str =
    "sha256:f9c50d3923dea8e7973946c87d0a9b08abe5a7b1af67acbbc3709d7e37cdc205";

struct Original {
    variant: &'static str,
    report: &'static str,
    component: &'static str,
    snapshot: &'static str,
    archive: &'static str,
    companion: &'static str,
    requirements: Option<&'static str>,
}

const ORIGINALS: [Original; 4] = [
    Original {
        variant: "aggregate",
        report: "sha256:290fe4705578e1d60935878531cf05335a277f408f9b88f2f7a6f7378d67e9a7",
        component: "sha256:3d7f1e8795c09088645e5ae10e75a913b2078ae77fe2822504a533b8f22c5c6a",
        snapshot: "sha256:019460935a0fac39fd842ea630a7f07b4c6a7c4f5e4a961926f3d4166b4eb6d5",
        archive: "sha256:c9fa4b58ddce06c51ecdb576236f26f48465cafda2facc40ba7ea5eaab132823",
        companion: "sha256:6554b968e80b2e3132742d3c95e21ba2056fa4fa9f846b419c36daf2da3a57e4",
        requirements: None,
    },
    Original {
        variant: "put-once-legacy-v1",
        report: "sha256:b8733ee83c85e78c5c6be66662a175d903fd24c89e64ead7ceb769e496135139",
        component: "sha256:112e60fbf29c131d221f21de677d0e3b268cacf5bc17db184b94655c0513734d",
        snapshot: "sha256:aab19decd17686ddea99afdda836256bb179eb0c593567f62c90d768aff569db",
        archive: "sha256:122c2f666a57f83f00967f33f3ad728720f53a6f1e1f31cf02c37c85a0c68b6d",
        companion: LEGACY_COMPANION,
        requirements: Some(LEGACY_REQUIREMENTS),
    },
    Original {
        variant: "put-once-compatible-v2",
        report: "sha256:9334422b2c8f297d03851f44db5c0c3d4b9805dd577ccb985202f274f06a567e",
        component: "sha256:1221ffac1d4f8db71327d56fba1624df19bff849a26f687a57888ccc4a0279ae",
        snapshot: "sha256:7b04765cc056526c01cbe2fcc10e7c3d3e1208bdd5ef3f1fc9f3b3963caa9163",
        archive: "sha256:a7d936cd1008f0b36be9dc470ef290922a3f620d7388a24a51d6aeafecebd689",
        companion: LEGACY_COMPANION,
        requirements: Some(LEGACY_REQUIREMENTS),
    },
    Original {
        variant: "put-once-writer-v2",
        report: "sha256:b13deaa5df52d599deaabb70e20928252581645df6186e2a2dae090e28b95f4e",
        component: "sha256:ec6ac5b4a95957406f664f7df9feb4a92829fb26e8634cde97f8b44ae21082ce",
        snapshot: "sha256:17540127721207407d3f4450b7e418098a039dbc23ab1ac62029611ee9867614",
        archive: "sha256:4fbeec46bd691afb94e1e2b44addcadafaa9edfc130b07f371d78b22433243e0",
        companion: "sha256:e5719a610fb20811a402aed0531d13d71547978104048d9e275ae7b7ae061c49",
        requirements: Some(
            "sha256:23fdda7e19691d21bb832ac5e59113ddc2afdecfc8668715fb43d6ae9c23a275",
        ),
    },
];

fn check_original(name: &str, fixture: &Value, report: &Value) -> Result<()> {
    let selected = ORIGINALS
        .iter()
        .find(|pin| name.strip_prefix("java718-") == Some(pin.variant))
        .ok_or("only the four preserved positive Java packages may enter this bridge")?;
    if fixture["compilerSource"] != ORIGINAL_SOURCE
        || fixture["compilerReportDigest"] != selected.report
        || fixture["componentDigest"] != selected.component
        || fixture["sourceSnapshotDigest"] != selected.snapshot
        || fixture["sourceArchiveDigest"] != selected.archive
        || fixture["companionDigest"] != selected.companion
        || fixture["requirementsDigest"].as_str() != selected.requirements
        || report["variant"] != selected.variant
        || report["hostAbiDigest"] != ABI
    {
        return Err("preserved FF9 diagnostic bridge identity changed".into());
    }
    Ok(())
}

fn check_diagnostic(name: &str, fixture: &Value, report: &Value, source: &str) -> Result<()> {
    if source == ORIGINAL_SOURCE
        || name != "java718-put-once-diagnostics"
        || fixture["compilerSource"] != source
        || report["variant"] != "put-once-diagnostics"
        || report["hostAbiDigest"] != ABI
        || fixture["companionDigest"] != LEGACY_COMPANION
        || fixture["requirementsDigest"] != LEGACY_REQUIREMENTS
    {
        return Err(
            "one independently sourced diagnostic with original ABI and effect links required"
                .into(),
        );
    }
    Ok(())
}

fn material(root: &Path) -> Result<(Value, Value, Value)> {
    let read = |name: &str, maximum| -> Result<Value> {
        let raw = read_package_file(root, name, maximum).map_err(|error| error.message)?;
        Ok(serde_json::from_slice(&raw)?)
    };
    Ok((
        read("fixture-provenance-input.json", 65_536)?,
        read("compiler-report.json", 262_144)?,
        read("transaction-profile.json", 65_536)?,
    ))
}

pub(super) fn load(
    source: &str,
    diagnostic: &Path,
    originals: &[OsString],
) -> Result<Vec<inputs::Build>> {
    if originals.len() != 4 {
        return Err("diagnostic fixture bridge requires exactly four original inputs".into());
    }
    let mut builds = Vec::new();
    let mut names = BTreeSet::new();
    for root in originals {
        let root = Path::new(root);
        let build = fixtures::load_current(root, ORIGINAL_SOURCE)?;
        let name = &build.bundle.layout().config().name;
        let (fixture, report, profile) = material(root)?;
        check_original(name, &fixture, &report)?;
        if profile["hostAbiDigest"] != ABI || !names.insert(name.clone()) {
            return Err("duplicate original package or changed signed transaction profile".into());
        }
        builds.push(build);
    }
    let build = fixtures::load_current(diagnostic, source)?;
    let (fixture, report, profile) = material(diagnostic)?;
    check_diagnostic(
        &build.bundle.layout().config().name,
        &fixture,
        &report,
        source,
    )?;
    if profile["hostAbiDigest"] != ABI {
        return Err("diagnostic signed transaction profile changed".into());
    }
    builds.push(build);
    Ok(builds)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn original(pin: &Original) -> (Value, Value) {
        (
            json!({"compilerSource":ORIGINAL_SOURCE,"compilerReportDigest":pin.report,
                "componentDigest":pin.component,"sourceSnapshotDigest":pin.snapshot,
                "sourceArchiveDigest":pin.archive,"companionDigest":pin.companion,
                "requirementsDigest":pin.requirements}),
            json!({"variant":pin.variant,"hostAbiDigest":ABI}),
        )
    }

    #[test]
    fn original_bridge_refuses_source_name_and_every_material_swap() {
        for pin in &ORIGINALS {
            let (fixture, report) = original(pin);
            let name = format!("java718-{}", pin.variant);
            check_original(&name, &fixture, &report).unwrap();
            for field in [
                "compilerSource",
                "compilerReportDigest",
                "componentDigest",
                "sourceSnapshotDigest",
                "sourceArchiveDigest",
                "companionDigest",
                "requirementsDigest",
            ] {
                let mut changed = fixture.clone();
                changed[field] = json!("changed");
                assert!(check_original(&name, &changed, &report).is_err(), "{field}");
            }
            assert!(check_original("java718-put-once-values", &fixture, &report).is_err());
            let mut changed = report.clone();
            changed["hostAbiDigest"] = json!("changed");
            assert!(check_original(&name, &fixture, &changed).is_err());
        }
    }

    #[test]
    fn diagnostic_bridge_refuses_source_aliases_wrong_recipe_and_original_link_drift() {
        let source = "a".repeat(40);
        let fixture = json!({"compilerSource":source,"companionDigest":LEGACY_COMPANION,
            "requirementsDigest":LEGACY_REQUIREMENTS});
        let report = json!({"variant":"put-once-diagnostics","hostAbiDigest":ABI});
        check_diagnostic("java718-put-once-diagnostics", &fixture, &report, &source).unwrap();
        for field in ["compilerSource", "companionDigest", "requirementsDigest"] {
            let mut changed = fixture.clone();
            changed[field] = json!("changed");
            assert!(
                check_diagnostic("java718-put-once-diagnostics", &changed, &report, &source)
                    .is_err()
            );
        }
        for field in ["variant", "hostAbiDigest"] {
            let mut changed = report.clone();
            changed[field] = json!("changed");
            assert!(
                check_diagnostic("java718-put-once-diagnostics", &fixture, &changed, &source)
                    .is_err()
            );
        }
        assert!(check_diagnostic("java718-aggregate", &fixture, &report, &source).is_err());
        assert!(check_diagnostic(
            "java718-put-once-diagnostics",
            &fixture,
            &report,
            ORIGINAL_SOURCE
        )
        .is_err());
    }
}
