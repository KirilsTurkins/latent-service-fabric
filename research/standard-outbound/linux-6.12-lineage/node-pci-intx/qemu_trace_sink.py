"""Review-only single-file fail-stop trace-sink derivation for Linux QEMU."""
import hashlib

SOURCE_BYTES = 17141
SOURCE_SHA256 = 'c349dc3eea8b198df00591cb6d1cc3a12c11b354b295fe3205d077dd1b76f978'
FAIL_EXIT = 74

def require(value, reason):
    if not value:
        raise ValueError('q35-trace-sink-'+reason)

def transform(raw):
    require(type(raw) is bytes and len(raw) == SOURCE_BYTES and
        hashlib.sha256(raw).hexdigest() == SOURCE_SHA256, 'exact-qemu-log-source')
    changes = [
        (b'#ifdef CONFIG_LINUX\n#include <sys/syscall.h>\n#endif\n',
         b'#ifdef CONFIG_LINUX\n#include <sys/syscall.h>\n#include <unistd.h>\n'
         b'#else\n#error "q35 trace qualification requires a Linux host"\n#endif\n'),
        (b'        fflush(logfile);\n        qemu_funlockfile(logfile);\n',
         b'        int lsf_flush_error = fflush(logfile);\n'
         b'        if (qemu_loglevel_mask(LOG_TRACE) && (lsf_flush_error || ferror(logfile)))\n'
         b'            _exit(74);\n'
         b'        qemu_funlockfile(logfile);\n'),
        (b'    FILE *f = qemu_log_trylock_with_context();\n    if (f) {\n',
         b'    FILE *f = qemu_log_trylock_with_context();\n'
         b'    if (!f && qemu_loglevel_mask(LOG_TRACE))\n        _exit(74);\n'
         b'    if (f) {\n')]
    out = raw
    for old, new in changes:
        require(out.count(old) == 1 and out.count(new) == 0, 'unique-forward-anchor')
        out = out.replace(old, new, 1)
    inverse = out
    for old, new in reversed(changes):
        require(inverse.count(new) == 1, 'unique-inverse-anchor')
        inverse = inverse.replace(new, old, 1)
    require(inverse == raw, 'exact-inverse')
    return out, {'sourceBytes': len(raw), 'sourceSha256': hashlib.sha256(raw).hexdigest(),
                 'derivedBytes': len(out), 'derivedSha256': hashlib.sha256(out).hexdigest(),
                 'originalSourceInverseExact': True, 'failStopExit': FAIL_EXIT,
                 'qemuExecuted': False, 'traceCompletenessQualified': False}
