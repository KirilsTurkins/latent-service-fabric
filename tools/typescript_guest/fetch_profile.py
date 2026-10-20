"""Automatic buffered fetch candidate; no claim of signed runtime qualification."""
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

PROFILE = 'lsf-fetch-buffered-v1'
INTERFACE = 'latent:http/streaming@0.3.0'
PHASE_PROFILE = 'lsf-fetch-phase-buffered-v2'
PHASE_INTERFACE = 'latent:http/phase-timing@0.4.0'


def selected(runtime_profile: str, imports: list[str]) -> bool:
    """Real async imports and explicit typed authority are both prerequisites."""
    return runtime_profile == IMPORT_PROFILE and any(name in imports for name in (INTERFACE,PHASE_INTERFACE))


def bundle_configuration(configuration: dict, runtime_profile: str, imports: list[str]) -> dict:
    result = dict(configuration)
    # Capture metadata cannot install or override the compiler-owned backend.
    if 'standardFetchProfile' in result:
        raise ValueError('application-cannot-override-standard-fetch-backend')
    result['runtimeProfile'] = runtime_profile
    if selected(runtime_profile, imports):
        result['standardFetchProfile'] = PHASE_PROFILE if PHASE_INTERFACE in imports else PROFILE
    return result
