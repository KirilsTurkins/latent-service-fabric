"""Authenticate the preprocessed TeaVM Date initializer before finite lowering.

This source proof is only one part of admission. Its result is not sufficient
without the separately checked Java method, promoted toolchain and exact link
inputs. Unknown syntax, identities and additional native names fail closed.
"""
from __future__ import annotations

import hashlib
import re

from tools.java_guest.enum_guard import MAX_INPUT, _directives, _token_view

DATE_BLOCK_SHA256 = 'f65fb59460cc76b8b19bfe5d187f297abe5d69b518185c2c456e490573057dea'
DATE_BLOCK_HEAD = 'static time_t teavm_epochStart;'
DATE_BLOCK_TAIL = 'char* teavm_date_format(int64_t time) {'
DATE_INIT = b'''void teavm_date_init() {
    struct tm epochStart = {
        .tm_year = 70,
        .tm_mon = 0,
        .tm_mday = 1,
        .tm_hour = 0,
        .tm_min = 0,
        .tm_sec = 0,
        .tm_isdst = -1
    };



    teavm_epochStart = timegm(&epochStart);

    localtime_r(&teavm_epochStart, &teavm_epochStartTm);
}'''
DATE_JAVA_CALLER = '''void meth_ju_Date__clinit_() {
    teavm_date_init();
}'''
FINITE_INIT = b'''extern const char __utc[];
_Static_assert(sizeof(time_t) == 8, "lsf-date-time-t");
_Static_assert(sizeof(struct tm) == 48, "lsf-date-tm-size");
_Static_assert(__builtin_offsetof(struct tm, tm_sec) == 0, "lsf-date-sec");
_Static_assert(__builtin_offsetof(struct tm, tm_min) == 4, "lsf-date-min");
_Static_assert(__builtin_offsetof(struct tm, tm_hour) == 8, "lsf-date-hour");
_Static_assert(__builtin_offsetof(struct tm, tm_mday) == 12, "lsf-date-mday");
_Static_assert(__builtin_offsetof(struct tm, tm_mon) == 16, "lsf-date-mon");
_Static_assert(__builtin_offsetof(struct tm, tm_year) == 20, "lsf-date-year");
_Static_assert(__builtin_offsetof(struct tm, tm_wday) == 24, "lsf-date-wday");
_Static_assert(__builtin_offsetof(struct tm, tm_yday) == 28, "lsf-date-yday");
_Static_assert(__builtin_offsetof(struct tm, tm_isdst) == 32, "lsf-date-isdst");
_Static_assert(__builtin_offsetof(struct tm, tm_gmtoff) == 36, "lsf-date-gmtoff");
_Static_assert(__builtin_offsetof(struct tm, tm_zone) == 40, "lsf-date-zone");
_Static_assert(__builtin_offsetof(struct tm, __tm_nsec) == 44, "lsf-date-nsec");
void teavm_date_init() {
    teavm_epochStart = 0;
    teavm_epochStartTm.tm_sec = 0;
    teavm_epochStartTm.tm_min = 0;
    teavm_epochStartTm.tm_hour = 0;
    teavm_epochStartTm.tm_mday = 1;
    teavm_epochStartTm.tm_mon = 0;
    teavm_epochStartTm.tm_year = 70;
    teavm_epochStartTm.tm_wday = 4;
    teavm_epochStartTm.tm_yday = 0;
    teavm_epochStartTm.tm_isdst = 0;
    teavm_epochStartTm.tm_gmtoff = 0;
    teavm_epochStartTm.tm_zone = __utc;
}'''
TM_DECLARATION = b'''struct tm {
    int tm_sec;
    int tm_min;
    int tm_hour;
    int tm_mday;
    int tm_mon;
    int tm_year;
    int tm_wday;
    int tm_yday;
    int tm_isdst;
    int tm_gmtoff;
    const char *tm_zone;
    int __tm_nsec;
};'''
LIBC_SYMBOLS = frozenset(('timegm', 'localtime_r', '__secs_to_zone', '__secs_to_tm',
    '__tm_to_secs', '__year_to_secs', '__month_to_secs', '__utc', 'errno', '__stack_pointer'))
PROTECTED = LIBC_SYMBOLS | frozenset(('teavm_date_init', 'teavm_epochStart',
    'teavm_epochStartTm', 'meth_ju_Date__clinit_', 'time_t', 'tm_sec', 'tm_min', 'tm_hour', 'tm_mday',
    'tm_mon', 'tm_year', 'tm_wday', 'tm_yday', 'tm_isdst', 'tm_gmtoff',
    'tm_zone', '__tm_nsec'))


def need(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError('java-date-guard-' + reason)


def word_count(view: str, name: str) -> int:
    return len(re.findall(r'\b' + re.escape(name) + r'\b', view))


def seal(preprocessed: bytes, checked: bytes, *, required: bool) -> tuple[bytes, dict | None]:
    """Return finite C and an observation, or unchanged C when Date is unused."""
    need(type(required) is bool, 'required-selection')
    need(len(preprocessed) <= MAX_INPUT, 'source-bound')
    # Always protect the emitted method name: a macro must not hide a call
    # and make a reachable initializer look unused. Other Date-specific
    # restrictions only apply once an actual caller has been found.
    cleaned = _directives(preprocessed, {'teavm_date_init', 'meth_ju_Date__clinit_'})
    need(cleaned == checked, 'source-binding')
    view = _token_view(cleaned)
    mentions = word_count(view, 'teavm_date_init')
    if mentions == 0:
        need(not required and word_count(view, 'meth_ju_Date__clinit_') == 0, 'missing-required-call')
        return cleaned, None
    if mentions == 2 and view.count('extern void teavm_date_init();') == 1 \
            and view.count('void teavm_date_init() {') == 1:
        need(not required and word_count(view, 'meth_ju_Date__clinit_') == 0, 'missing-required-call')
        return cleaned, None
    need(view.count(DATE_BLOCK_HEAD) == 1 and view.count(DATE_BLOCK_TAIL) == 1, 'block-boundary')
    start = view.index(DATE_BLOCK_HEAD)
    tail = view.index(DATE_BLOCK_TAIL, start)
    begin = view.index('{', tail)
    depth = 0
    for position in range(begin, len(view)):
        depth += (view[position] == '{') - (view[position] == '}')
        if depth == 0:
            break
    else:
        raise ValueError('java-date-guard-block-braces')
    end = position + 1
    block = cleaned[start:end]
    need(hashlib.sha256(block).hexdigest() == DATE_BLOCK_SHA256, 'date-block')
    need(block.count(DATE_INIT) == 1 and word_count(view[start:end], 'teavm_date_init') == 1,
         'date-init')
    outside = view[:start] + view[end:]
    prototype = 'extern void teavm_date_init();'
    need(outside.count(prototype) == 1, 'date-prototype')
    other = outside.replace(prototype, '', 1)
    if word_count(other, 'teavm_date_init') == 0:
        need(not required and word_count(view, 'meth_ju_Date__clinit_') == 0, 'missing-required-call')
        return cleaned, None
    need(other.count(DATE_JAVA_CALLER) == 1
         and word_count(other.replace(DATE_JAVA_CALLER, '', 1), 'teavm_date_init') == 0,
         'java-caller')
    need(_directives(preprocessed, set(PROTECTED)) == checked, 'protected-directives')
    need(not re.search(r'\b(?:asm|__asm|__asm__|alias|__alias__|weak|__weak__|weakref|ifunc)\b', view),
         'linkage-token')
    need(cleaned.count(TM_DECLARATION) == 1 and view.count('typedef long long time_t;') == 1, 'time-abi')
    for name in LIBC_SYMBOLS:
        count = word_count(outside, name)
        need(count == (1 if name in ('timegm', 'localtime_r') else 0), 'external-' + name)
    need(outside.count('time_t timegm(struct tm *);') == 1, 'timegm-prototype')
    need(outside.count('struct tm *localtime_r (const time_t *restrict, struct tm *restrict);') == 1,
         'localtime-prototype')
    need(word_count(outside, 'teavm_epochStart') == 0
         and word_count(outside, 'teavm_epochStartTm') == 0, 'date-static')
    result = cleaned[:start] + block.replace(DATE_INIT, FINITE_INIT) + cleaned[end:]
    need(len(result) <= MAX_INPUT, 'sealed-bound')
    return result, {'schemaVersion': 'latent.java.date-guard-source.v1',
                    'dateBlockSha256': DATE_BLOCK_SHA256,
                    'originalInitSha256': hashlib.sha256(DATE_INIT).hexdigest(),
                    'finiteInitSha256': hashlib.sha256(FINITE_INIT).hexdigest(),
                    'sourceSha256': hashlib.sha256(result).hexdigest()}
