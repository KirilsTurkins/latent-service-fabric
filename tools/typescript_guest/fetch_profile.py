"""Automatic buffered fetch candidate; no claim of signed runtime qualification."""
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

PROFILE = 'lsf-fetch-buffered-v1'
INTERFACE = 'latent:http/streaming@0.3.0'


def selected(runtime_profile: str, imports: list[str]) -> bool:
    """Real async imports and explicit typed authority are both prerequisites."""
    return runtime_profile == IMPORT_PROFILE and INTERFACE in imports


def bundle_configuration(configuration: dict, runtime_profile: str, imports: list[str]) -> dict:
    result = dict(configuration)
    # Capture metadata cannot install or override the compiler-owned backend.
    if 'standardFetchProfile' in result:
        raise ValueError('application-cannot-override-standard-fetch-backend')
    result['runtimeProfile'] = runtime_profile
    if selected(runtime_profile, imports):
        result['standardFetchProfile'] = PROFILE
    return result
