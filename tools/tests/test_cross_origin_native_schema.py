"""Closed structural checks; native derivation additionally verifies ownership/canonicality."""
import copy
import json
from pathlib import Path
import unittest

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / 'schemas/node-http-ingress.schema.json').read_text(encoding='utf-8'))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
GRANT = {'authority': 'assets.example.test', 'tenant': 'tests',
         'publication': 'publication:sha256:' + 'ab' * 32,
         'origins': ['https://portal.example.test']}
PUBLIC = {'formatVersion': 1, 'bind': '127.0.0.1:0',
          'transport': {'mode': 'trusted-proxy', 'peers': ['127.0.0.1']},
          'authentication': {'mode': 'public-origins', 'origins': [
              {'authority': GRANT['authority'], 'tenant': 'tests', 'subject': 'reader'}]}}


class CrossOriginNativeSchema(unittest.TestCase):
    def test_documented_native_grant_matches_the_validated_example(self):
        import re
        example = json.loads((ROOT / 'examples/cross-origin-assets/http-ingress.json').read_text())
        VALIDATOR.validate(example)
        guide = (ROOT / 'docs/operations/cross-origin-static-assets.md').read_text()
        block = re.search(r'<!-- native-cors-grant:begin -->\s*```json\n(.*?)\n```\s*<!-- native-cors-grant:end -->',
                          guide, re.S)
        self.assertIsNotNone(block)
        self.assertEqual(json.loads(block.group(1)), example['crossOriginAssets'][0])
        grant = example['crossOriginAssets'][0]
        owner = example['authentication']['origins'][0]
        self.assertEqual((grant['authority'], grant['tenant']), (owner['authority'], owner['tenant']))
        self.assertEqual(grant['credentials'], 'omit')
        self.assertEqual(example['transport']['mode'], 'tls')
        self.assertLessEqual(example['limits']['maximumExchanges'], 2)

    def test_schema_and_default_empty_preserve_existing_adapters(self):
        VALIDATOR.check_schema(SCHEMA)
        for authentication in (PUBLIC['authentication'], {'mode': 'bearer'}):
            for transport in (PUBLIC['transport'], {'mode': 'loopback'}):
                config = dict(PUBLIC, authentication=authentication, transport=transport)
                VALIDATOR.validate(config)
                VALIDATOR.validate(dict(config, crossOriginAssets=[]))
        self.assertEqual(SCHEMA['properties']['crossOriginAssets']['default'], [])

    def test_nonempty_requires_https_public_adapter(self):
        VALIDATOR.validate(dict(PUBLIC, crossOriginAssets=[GRANT]))
        tls = {'mode': 'tls', 'certificateFile': 'server.pem', 'privateKeyFile': 'key.pem'}
        VALIDATOR.validate(dict(PUBLIC, transport=tls, crossOriginAssets=[GRANT]))
        for override in ({'authentication': {'mode': 'bearer'}},
                         {'transport': {'mode': 'loopback'}}):
            self.assertFalse(VALIDATOR.is_valid(dict(PUBLIC, crossOriginAssets=[GRANT], **override)))

    def test_grants_and_credentials_are_closed(self):
        for value in (None, {}, [None], [{}], [dict(GRANT, extra=True)], [GRANT, GRANT]):
            self.assertFalse(VALIDATOR.is_valid(dict(PUBLIC, crossOriginAssets=value)), value)
        for field in GRANT:
            row = copy.deepcopy(GRANT)
            del row[field]
            self.assertFalse(VALIDATOR.is_valid(dict(PUBLIC, crossOriginAssets=[row])))
        for mode in ('omit', 'include'):
            VALIDATOR.validate(dict(PUBLIC, crossOriginAssets=[dict(GRANT, credentials=mode)]))
        for mode in (None, True, 'same-origin', '*'):
            self.assertFalse(VALIDATOR.is_valid(dict(
                PUBLIC, crossOriginAssets=[dict(GRANT, credentials=mode)])))

    def test_cardinality_and_publication_identity(self):
        rows = [dict(GRANT, publication=f'publication:sha256:{index:064x}') for index in range(33)]
        VALIDATOR.validate(dict(PUBLIC, crossOriginAssets=rows[:32]))
        self.assertFalse(VALIDATOR.is_valid(dict(PUBLIC, crossOriginAssets=rows)))
        origins = [f'https://caller{index}.example.test' for index in range(17)]
        VALIDATOR.validate(dict(PUBLIC, crossOriginAssets=[dict(GRANT, origins=origins[:16])]))
        for value in ([], None, origins, ['https://caller.example.test'] * 2):
            self.assertFalse(VALIDATOR.is_valid(dict(
                PUBLIC, crossOriginAssets=[dict(GRANT, origins=value)])))
        for value in ('latest', '*', 'sha256:' + 'ab' * 32,
                      'publication:sha256:' + 'AB' * 32, 'publication:sha256:abcd'):
            self.assertFalse(VALIDATOR.is_valid(dict(
                PUBLIC, crossOriginAssets=[dict(GRANT, publication=value)])))

    def test_origin_forms_reject_wildcards_lists_and_default_port_aliases(self):
        for origin in ('https://portal.example.test', 'https://portal.example.test:8443',
                       'https://127.0.0.1', 'https://[::1]:8443'):
            VALIDATOR.validate(dict(PUBLIC, crossOriginAssets=[dict(GRANT, origins=[origin])]))
        for origin in ('null', '*', 'https://*.example.test', 'http://portal.example.test',
                       'https://PORTAL.example.test', 'https://portal.example.test:443',
                       'https://portal.example.test:08443', 'https://portal.example.test/',
                       'https://portal.example.test/path', 'https://user@portal.example.test',
                       'https://portal.example.test?x=1', 'https://portal.example.test#fragment',
                       'https://portal.example.test,https://other.example.test',
                       'https://portal.example.test https://other.example.test',
                       'https://bücher.example.test', ' https://portal.example.test'):
            self.assertFalse(VALIDATOR.is_valid(dict(
                PUBLIC, crossOriginAssets=[dict(GRANT, origins=[origin])])), origin)


if __name__ == '__main__':
    unittest.main()
