//! Closed signed marker, component, companion and requirement associations.
use super::{digest, Profile, CURRENT_MARKER};
use latent_core::PlatformError;

#[derive(Clone, Copy)]
pub(in crate::standalone::state::recovery) struct CurrentHttpInput<'a> {
    pub component: &'a str,
    pub companion: &'a str,
    pub marker: &'a [u8],
    pub requirements_digest: &'a str,
    pub requirements: &'a [u8],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum HttpCustody {
    Original,
    Fresh,
}

impl HttpCustody {
    pub fn select(profile: Profile, input: &CurrentHttpInput<'_>) -> Result<Self, PlatformError> {
        if !profile.current_http()
            || Profile::installed(input.component)? != profile
            || input.marker.len() > 8192
            || input.requirements.len() > 8192
        {
            return Err(super::super::denied());
        }
        let custody = match digest(input.marker).as_str() {
            CURRENT_MARKER => Self::Original,
            "c62dd813a48cd7ab58246c87e06aca500b004421eb5a9b324f6e89a061556c9b" => Self::Fresh,
            _ => return Err(super::super::denied()),
        };
        if input.component == super::native_memory::COMPONENT && custody != Self::Fresh {
            return Err(super::super::denied());
        }
        let writer = profile.base() == Profile::Writer;
        let companion = if writer {
            "sha256:e5719a610fb20811a402aed0531d13d71547978104048d9e275ae7b7ae061c49"
        } else {
            "sha256:24a689c7166ffbdbaacefa8d7d7efe18a98d532adc94fc4392968aaab837349d"
        };
        let requirements = custody.requirements(writer);
        if input.companion != companion
            || input.requirements_digest != format!("sha256:{requirements}")
            || digest(input.requirements) != requirements
        {
            return Err(super::super::denied());
        }
        Ok(custody)
    }

    pub const fn marker(self) -> &'static str {
        match self {
            Self::Original => CURRENT_MARKER,
            Self::Fresh => "c62dd813a48cd7ab58246c87e06aca500b004421eb5a9b324f6e89a061556c9b",
        }
    }

    fn requirements(self, writer: bool) -> &'static str {
        match (self, writer) {
            (Self::Original, false) => {
                "dfa7b1459dbe78c9dc1a43aef3171916d84f78f49fc8df50ea09dc13036f80ab"
            }
            (Self::Original, true) => {
                "83c1d6de5fee0d54d255ad8cc6007911adf1a3d755521c02be67676b374980cd"
            }
            (Self::Fresh, false) => {
                "49c9b8af6be278198d286b776f492e0fda9a6621b9b2fcd36aa788d77a2e5c54"
            }
            (Self::Fresh, true) => {
                "4b4e375e4834be64784c71da140da42540bd901d8bc33a8ff813a9a2e18c6f1b"
            }
        }
    }
}
