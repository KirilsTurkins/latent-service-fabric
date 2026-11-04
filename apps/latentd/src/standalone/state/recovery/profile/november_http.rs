//! Closed associations for the November constructor and captured components.
use super::http_custody::CurrentHttpInput;
use super::reconstructed_http::SelectedHttpCustody;
use super::{digest, Profile};
use latent_core::PlatformError;

#[cfg(test)]
mod tests;

pub(super) const MARKER: &str = "fc1d027365f876578c95296cf57e2a3467c2a5a9358544251462e472a6a094e2";
const REQUIREMENTS: &str = "17166184306ac8a81d3d0e13256afc64550403b1a6fe18e02386035dd9a7ffb8";
const WRITER_REQUIREMENTS: &str =
    "2734a95873297041cbe25c5bae27b4c95c2367d57cfd82971e28c41892887eaf";

pub(super) fn select(
    profile: Profile,
    input: &CurrentHttpInput<'_>,
) -> Result<SelectedHttpCustody, PlatformError> {
    if input.marker.len() > 8192
        || input.requirements.len() > 8192
        || digest(input.marker) != MARKER
    {
        return Err(super::super::denied());
    }
    let (component, writer) = match profile {
        Profile::CurrentLegacy => (
            "sha256:355dbd17c29b2a8756d5dfccb34582e878b03fd299c35c0652cbec4bb7d7338a",
            false,
        ),
        Profile::CurrentCompatible => (
            "sha256:6c31f6763a5d3d8d84aa0668a44b220c3ba619f9c257e9a0d0b441e58d94099b",
            false,
        ),
        Profile::CurrentWriter => (
            "sha256:5f2f4bd6880bf516f042d65b2fc65d06ad80036a82b7ad60a2b95438972546a8",
            true,
        ),
        Profile::CurrentDiagnostic => (
            "sha256:25258bd576a7ee6e79f20a0b7a13e10293780fce310d03f529ac811c7ccdc5e0",
            false,
        ),
        Profile::CurrentValues => (
            "sha256:e5fb75766a283d8ac818c073288706cea89303746b9d347746a2f44429c5f424",
            false,
        ),
        _ => return Err(super::super::denied()),
    };
    let companion = if writer {
        "sha256:e5719a610fb20811a402aed0531d13d71547978104048d9e275ae7b7ae061c49"
    } else {
        "sha256:24a689c7166ffbdbaacefa8d7d7efe18a98d532adc94fc4392968aaab837349d"
    };
    let requirements = if writer {
        WRITER_REQUIREMENTS
    } else {
        REQUIREMENTS
    };
    if input.component != component
        || Profile::installed(input.component)? != profile
        || input.companion != companion
        || input.requirements_digest != format!("sha256:{requirements}")
        || digest(input.requirements) != requirements
    {
        return Err(super::super::denied());
    }
    Ok(SelectedHttpCustody::November)
}
