/* SPDX-License-Identifier: GPL-2.0-only */
/* Reference-only freestanding output. No SDK/runtime or kernel interface. */
#ifndef LSF_LINEAGE_REFERENCE_IO_H
#define LSF_LINEAGE_REFERENCE_IO_H
#include <stddef.h>
#include <stdint.h>

__attribute__((import_module("lineage_reference"), import_name("write")))
void lsf_ref_write(const char *text, unsigned int bytes);
__attribute__((import_module("lineage_reference"), import_name("error")))
void lsf_ref_write_error(const char *text, unsigned int bytes);

static inline unsigned int lsf_ref_length(const char *text)
{
    unsigned int bytes = 0;
    while (text[bytes]) {
        if (++bytes > 256)
            __builtin_trap();
    }
    return bytes;
}

static inline void lsf_ref_check(int result, const char *expression)
{
    if (!result) {
        lsf_ref_write_error(expression, lsf_ref_length(expression));
        __builtin_trap();
    }
}
#define assert(expression) lsf_ref_check(!!(expression), #expression)

void *memset(void *target, int value, size_t bytes)
{
    volatile unsigned char *output = target;
    size_t i;
    for (i = 0; i < bytes; ++i)
        output[i] = (unsigned char)value;
    return target;
}

static inline int lsf_ref_puts(const char *text)
{
    lsf_ref_write(text, lsf_ref_length(text));
    lsf_ref_write("\n", 1);
    return 0;
}

static inline int lsf_ref_string(const char *format, const char *value)
{
    const char *prefix = format[0] == 'L' ? "LINEAGE_CONTROL " : "HOOK_CONTROL ";
    lsf_ref_write(prefix, lsf_ref_length(prefix));
    lsf_ref_write(value, lsf_ref_length(value));
    lsf_ref_write(" PASS\n", 6);
    return 0;
}

static inline int lsf_ref_size(const char *format, size_t value)
{
    char digits[32];
    unsigned int used = 0;
    (void)format;
    do {
        digits[31 - used++] = (char)('0' + value % 10);
        value /= 10;
    } while (value && used < sizeof(digits));
    assert(!value);
    lsf_ref_write("LINEAGE_SIZE ", 13);
    lsf_ref_write(digits + 32 - used, used);
    lsf_ref_write("\n", 1);
    return 0;
}

static inline int lsf_ref_error(const char *text)
{
    lsf_ref_write_error(text, lsf_ref_length(text));
    return 0;
}
#define printf(format, value) _Generic((value), char *: lsf_ref_string, const char *: lsf_ref_string, default: lsf_ref_size)(format, value)
#define puts(text) lsf_ref_puts(text)
#define fputs(text, stream) lsf_ref_error(text)
#define main lsf_reference_main
#endif
