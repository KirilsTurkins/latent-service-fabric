"""Predeclared independent byte specification for the six codec families."""
from functools import lru_cache

@lru_cache(maxsize=1)
def fixtures():
    scalar = '[true,255,65535,4294967295,-128,-32768,-2147483648,"18446744073709551615","-9223372036854775808","0.1","-0","\\ud83d\\ude80","hello"]'
    scalar_out = scalar.replace('\\ud83d\\ude80', chr(0x1F680))
    byte_list = '[[' + ','.join(str(i % 256) for i in range(4096)) + ']]'
    wide_in = '{"c":{"count":3,"name":"c"},"b":{"count":2,"name":"b"},"a":{"count":1,"name":"a"}}'
    wide_out = '{"a":{"name":"a","count":1},"b":{"name":"b","count":2},"c":{"name":"c","count":3}}'
    tail_in = ',{"value":"9","case":"number"},["admin","read"],{"some":{"some":"nested"}},{"err":{"value":"7","case":"number"}},[{"ok":"done"},{"err":{"value":"7","case":"number"}},{"err":{"case":"empty"}}]]'
    tail_out = ',{"case":"number","value":"9"},["read","admin"],{"some":{"some":"nested"}},{"err":{"case":"number","value":"7"}},[{"ok":"done"},{"err":{"case":"number","value":"7"}},{"err":{"case":"empty"}}]]'
    nested_in = '[[' + ','.join([wide_in] * 32) + ']' + tail_in
    nested_out = '[[' + ','.join([wide_out] * 32) + ']' + tail_out
    escaped_token = r'\ud83d\ude80\n\"\\\u00e9'
    escaped_output_token = chr(0x1F680) + r'\n\"\\' + chr(0xE9)
    pairs = {
        'scalar-params': (scalar, scalar_out, 13),
        'byte-list': (byte_list, byte_list, 1),
        'nested-record': (nested_in, nested_out, 6),
        'string-64k': ('["' + 'a' * 65536 + '"]', '["' + 'a' * 65536 + '"]', 1),
        'string-near-limit': ('["' + 'a' * 122880 + '"]', '["' + 'a' * 122880 + '"]', 1),
        'escaped-unicode': ('["' + escaped_token * 4096 + '"]', '["' + escaped_output_token * 4096 + '"]', 1),
    }
    return {key: (source.encode('utf-8'), expected.encode('utf-8'), arity)
            for key, (source, expected, arity) in pairs.items()}
