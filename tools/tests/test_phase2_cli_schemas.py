"""Closed on-disk operator inputs; runtime also enforces bytes and file ownership."""
import copy
import json
import pathlib
import unittest

import jsonschema

ROOT = pathlib.Path(__file__).resolve().parents[2]


class Phase2CliSchemas(unittest.TestCase):
    def validator(self, name):
        schema = json.loads((ROOT / 'schemas' / f'{name}.schema.json').read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        return jsonschema.Draft202012Validator(schema)

    def test_evidence_requires_exact_subject_and_closed_portable_selection(self):
        validator = self.validator('package-evidence-index')
        value = dict(formatVersion=1, packageDigest='sha256:' + 'a' * 64,
                     signatures=[], provenance=[], sboms=[])
        validator.validate(value)
        files = dict(manifest='signature/0/manifest.json',
                     configuration='signature/0/config.json', payload='signature/0/payload.json')
        value['signatures'] = [files]
        validator.validate(value)
        for change in ({'payload': '../private'}, {'payload': 'CON'}, {'payload': None}, {'extra': 'x'}):
            invalid = copy.deepcopy(value)
            invalid['signatures'][0].update(change)
            self.assertFalse(validator.is_valid(invalid))
        value['signatures'] = [files] * 9
        self.assertFalse(validator.is_valid(value))

    def test_registry_profile_rejects_inline_secrets_null_and_unbounded_sets(self):
        validator = self.validator('cli-registry-profile')
        value = dict(formatVersion=1, origin='https://registry.example',
                     repository='tenant/application', addresses=['127.0.0.1:443'],
                     credentialFile='credentials.json')
        validator.validate(value)
        for change in ({'token': 'private'}, {'credentialFile': None},
                       {'credentialFile': '../private'}, {'rootCertificates': ['ca.der'] * 9},
                       {'addresses': ['127.0.0.1:443'] * 17}):
            self.assertFalse(validator.is_valid(value | change))

    def test_credential_modes_are_closed_and_disjoint(self):
        validator = self.validator('cli-registry-credentials')
        validator.validate(dict(mode='bearer', token='secret'))
        validator.validate(dict(mode='basic', username='client', password='secret'))
        for value in (dict(mode='bearer', token=None), dict(mode='basic', token='x'),
                      dict(mode='bearer', token='x', username='client'), dict(mode='bearer', token='')):
            self.assertFalse(validator.is_valid(value))

    def test_challenge_network_profile_is_closed_versioned_and_bounded(self):
        validator = self.validator('cli-registry-profile')
        value = json.loads((ROOT / 'examples/guides/registry-challenge.json').read_text())
        validator.validate(value)
        changes = [
            ('formatVersion', 1), ('formatVersion', 3), ('allowInsecureLoopback', True),
            ('addresses', ['192.0.2.10:443']), ('credentialFile', None), ('network', None),
            ('bearerChallenge/identity/credentialEpoch', 0), ('bearerChallenge/actions', 'delete'),
            ('bearerChallenge/password', 'private'), ('bearerChallenge', None),
            ('network/maximumRedirects', 4), ('network/destinations', []),
            ('network/destinations/0/addresses/networks', []),
            ('network/destinations/0/addresses/specialAddresses', ['192.0.2.10'] * 17),
            ('network/destinations/0/resolution/maximumTtlSeconds', 301),
            ('network/destinations/0/resolution/addresses', ['192.0.2.10']),
        ]
        for pointer, change in changes:
            invalid = copy.deepcopy(value)
            parts = pointer.split('/')
            parent = invalid
            for part in parts[:-1]:
                parent = parent[int(part)] if isinstance(parent, list) else parent[part]
            parent[parts[-1]] = change
            with self.subTest(pointer=pointer):
                self.assertFalse(validator.is_valid(invalid))

    def test_challenge_profile_allows_separate_static_token_resolution(self):
        validator = self.validator('cli-registry-profile')
        value = json.loads((ROOT / 'examples/guides/registry-challenge.json').read_text())
        del value['network']
        value['addresses'] = ['192.0.2.10:443']
        value['bearerChallenge']['addresses'] = ['192.0.2.20:443']
        validator.validate(value)
        del value['bearerChallenge']
        self.assertFalse(validator.is_valid(value))


if __name__ == '__main__':
    unittest.main()
