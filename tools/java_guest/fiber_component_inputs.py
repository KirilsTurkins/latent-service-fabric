"""Failure-only assembly inputs for the one fixed normal public fiber fixture."""
from pathlib import Path

from tools.dev_workflow import paths
from tools.java_guest.c_failure_context import encoded
from tools.rust_capsule_project import digest

JAVA = 'sha256:6a2f7a5a13b3295761b0f18989e47cc7ff106a7c9546c559492247fcd36430c8'
WIT = 'sha256:14c7bb47a7634153b4dcf39473a31f7f87f971f8c90a602b378be498dc938236'
LIMITS = {'core.wasm': 64*1024*1024, 'closed-runtime.wasm': 4*1024*1024}
SCHEMA = 'latent.java.public-fixture-component-inputs.v1'


def retain(compiler, output: Path) -> None:
    """Copy only failed assembly inputs; never replace the original exception."""
    if compiler is None:
        return
    target = output/'build/component-inputs'
    try:
        records = compiler.records
        if (type(records) is not list or not records or type(records[-1]) is not dict
                or records[-1].get('stage') != 'component-new'
                or type(records[-1].get('exitCode')) is not int or records[-1]['exitCode'] == 0):
            return
        paths.absolute(output)
        if sorted(path.name for path in (output/'src').iterdir()) != ['Capsule.java']:
            raise ValueError('normal-public-fiber-source-set')
        identities = {
            'src/Capsule.java': (JAVA, 1024*1024),
            'build/project/src/main/java/Capsule.java': (JAVA, 1024*1024),
            'wit/service.wit': (WIT, 64*1024),
            'build/wit/service.wit': (WIT, 64*1024),
        }
        for name, (expected, maximum) in identities.items():
            if digest(paths.read(output, name, maximum)) != expected:
                raise ValueError('normal-public-fiber-source-identity')
        for name in ('captured-application', 'captured-processor-api'):
            try:
                (output/'build/project'/name).lstat()
            except FileNotFoundError:
                pass
            else:
                raise ValueError('normal-public-fiber-extra-classpath')
        raw = {name: paths.read(output/'build', name, maximum) for name, maximum in LIMITS.items()}
        if any(not value.startswith(b'\0asm\x01\0\0\0') for value in raw.values()):
            raise ValueError('normal-public-fiber-component-input-magic')
        # Authenticate both fixed sources and both bounded inputs before any raw publication.
        target.mkdir()
        for name, value in raw.items():
            paths.write_new(target/name, value)
        paths.write_new(target/'record.json', encoded({
            'schemaVersion': SCHEMA, 'status': 'retained', 'qualification': False,
            'publicFixtureOnly': True, 'normalPublicFiberOnly': True,
            'failedStage': 'component-new', 'fixtureSourceDigest': JAVA, 'fixtureWitDigest': WIT,
            'inputs': {name: {'sha256': digest(value), 'bytes': len(value)} for name, value in raw.items()},
            'limits': LIMITS, 'logLimitBytesUnchanged': 16*1024*1024,
            'compilerAcceptanceChanged': False}))
    except BaseException:
        try:
            target.mkdir(exist_ok=True)
            paths.write_new(target/'refused.json', encoded({
                'schemaVersion': SCHEMA, 'status': 'unavailable', 'qualification': False,
                'reason': 'fixed-normal-public-fiber-inputs-unavailable-or-unsafe'}))
        except BaseException:
            pass
