"""Exact executable closure approval consumed only by an isolated build stage."""
from dataclasses import dataclass
from pathlib import Path

from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical, digest


def request(verified, isolation, recipe_digest: str) -> dict:
    if isolation.receipt.get('profile') != 'linux-captured-compiler-namespaces-v1':
        raise DependencyError('dependency-execution-isolation-profile-unavailable')
    return {'formatVersion': 1, 'inputIdentity': verified.identity,
            'executableInputs': [row for row in verified.lock['artifacts'] if row['role'] == 'build-tool'],
            'selection': verified.lock['selection'], 'recipeDigest': recipe_digest,
            'isolationProfile': isolation.receipt['profile'],
            'compilerInputsDigest': digest(canonical(isolation.receipt)),
            'network': 'denied', 'ambientHome': 'absent', 'credentials': 'not-inherited',
            'boundary': 'trusted-single-user-build-host-not-hardened-multitenant-vm', 'hermetic': False}


@dataclass(frozen=True)
class Approval:
    identity: str
    specification: dict
    isolation: object

    def validate(self, verified, work: Path):
        if (request(verified, self.isolation, self.specification['recipeDigest']) != self.specification
                or digest(canonical(self.specification)) != self.identity
                or not work.resolve().is_relative_to(self.isolation.workspace)):
            raise DependencyError('dependency-execution-approval-stale-or-outside-isolation')
        self.isolation.check_unchanged()


def approve(verified, isolation, recipe_digest: str, approved_identity: str) -> Approval:
    specification = request(verified, isolation, recipe_digest)
    identity = digest(canonical(specification))
    if approved_identity != identity:
        raise DependencyError('dependency-execution-approval-mismatch')
    return Approval(identity, specification, isolation)
