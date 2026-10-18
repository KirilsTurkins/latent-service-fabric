//! Closed signed associations for the fresh constructor's captured HTTP profile.
use super::http_custody::CurrentHttpInput;
use super::reconstructed_http::SelectedHttpCustody;
use super::{digest, Profile};
use latent_core::PlatformError;

#[cfg(test)]
mod tests;

pub(super) const MARKER: &str = "3f06bac2b40ee883e2583fab347a0d666924b3d47e91b32d0920c62c0023d407";
const REQUIREMENTS: &str = "7d33a4376a49e137e1864e1f20946ad1b7979bde9cacfa8745da0e4aa603c171";
const WRITER_REQUIREMENTS: &str =
    "9c3c5c20dd790a4c06982299ea649b6cd76d3350169086b43b1f5a6d7f2ab6de";

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
            "sha256:eae8efb880744d60ba7163590fb0fd825d45cb2018760b7c1cd00272e4cefecd",
            false,
        ),
        Profile::CurrentCompatible => (
            "sha256:ecd7d566a6403468a1166ad0c9042a51cce47e12f92e63907bce680daa08f813",
            false,
        ),
        Profile::CurrentWriter => (
            "sha256:05e8bbaa90168aa250d779431a317fcde8f785d93e511054e0d5facaaad5787d",
            true,
        ),
        Profile::CurrentDiagnostic => (
            "sha256:b46606299b77eeb9efb12abb2bdb793d5bba78bb1f8dc42d1be4bc92f5463115",
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
    Ok(SelectedHttpCustody::Refreshed)
}
