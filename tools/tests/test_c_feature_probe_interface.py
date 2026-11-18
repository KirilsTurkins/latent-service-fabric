import unittest

from tools.c_guest.feature_detection import resolver_interface


class ResolverInterfaceTests(unittest.TestCase):
    def test_qualified_old_and_current_resolver_interfaces(self):
        old = {'strongSymbols': ['freeaddrinfo', 'getaddrinfo'],
               'nonlocalSymbols': ['freeaddrinfo', 'getaddrinfo'],
               'definedSymbols': ['freeaddrinfo', 'getaddrinfo', 'numeric_canonical_name']}
        current = {'strongSymbols': ['freeaddrinfo', 'gai_strerror', 'getaddrinfo', 'getnameinfo'],
                   'nonlocalSymbols': ['freeaddrinfo', 'gai_strerror', 'getaddrinfo', 'getnameinfo'],
                   'definedSymbols': ['.L.str', '.L.str.1', '.Lswitch.table.gai_strerror',
                                      'freeaddrinfo', 'gai_strerror', 'getaddrinfo',
                                      'getnameinfo', 'numeric_canonical_name']}
        for observed in (old, current):
            with self.subTest(observed=observed):
                self.assertTrue(resolver_interface(observed))
                self.assertFalse(resolver_interface({**observed, 'definedSymbols':
                                                     observed['definedSymbols'] + ['unapproved']}))
                self.assertFalse(resolver_interface({**observed, 'nonlocalSymbols':
                                                     observed['nonlocalSymbols'] + ['numeric_canonical_name']}))
                self.assertFalse(resolver_interface({**observed, 'strongSymbols':
                                                     observed['strongSymbols'] + ['unapproved']}))

    def test_missing_expected_definition_is_rejected(self):
        self.assertFalse(resolver_interface({'strongSymbols': ['freeaddrinfo', 'getaddrinfo'],
                                             'nonlocalSymbols': ['freeaddrinfo', 'getaddrinfo'],
                                             'definedSymbols': ['getaddrinfo']}))


if __name__ == '__main__':
    unittest.main()
