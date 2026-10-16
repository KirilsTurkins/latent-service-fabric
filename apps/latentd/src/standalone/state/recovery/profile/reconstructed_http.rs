//! One captured replacement installation; historical associations remain separate.
use super::http_custody::{CurrentHttpInput, HttpCustody};
use super::{digest, Profile};
use latent_core::PlatformError;

#[cfg(test)]
mod tests;

pub(super) const MARKER: &str = "53e4284300b2194f4faec8db23680a76027f9e7f9202215e571dc44a47f28f71";
const REQUIREMENTS: &str = "d6190b8331152fabb6e030c476883445d97793923cf6bb37ec61bd2df5a88dd6";
const WRITER_REQUIREMENTS: &str =
    "aee137a27e70d85bee5d81aea605e662bbbaaee56b3b51140bd0d5d51c14a88f";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum SelectedHttpCustody {
    Historical(HttpCustody),
    Reconstructed,
    Refreshed,
}

impl SelectedHttpCustody {
    pub(super) fn select(
        profile: Profile,
        input: &CurrentHttpInput<'_>,
    ) -> Result<Self, PlatformError> {
        if input.marker.len() > 8192 || input.requirements.len() > 8192 {
            return Err(super::super::denied());
        }
        let marker = digest(input.marker);
        if marker == super::refreshed_http::MARKER {
            return super::refreshed_http::select(profile, input);
        }
        if marker != MARKER {
            return HttpCustody::select(profile, input).map(Self::Historical);
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
        Ok(Self::Reconstructed)
    }
}
