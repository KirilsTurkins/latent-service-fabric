/* Unavailable ambient effects fail; they are never silently acknowledged. */
#include "uchar.h"
#include <wchar.h>
#include <stdint.h>

_Noreturn void abort(void) { __builtin_trap(); }
void teavm_printString(char16_t* value) { (void)value; __builtin_trap(); }
void teavm_printWString(wchar_t* value) { (void)value; __builtin_trap(); }
void teavm_printInt(int32_t value) { (void)value; __builtin_trap(); }
void teavm_logCodePoint(int32_t value) { (void)value; __builtin_trap(); }
