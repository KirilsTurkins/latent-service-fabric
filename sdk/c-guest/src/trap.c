/* SPDX-License-Identifier: Apache-2.0 */
/* The freestanding reactor has no ambient WASI process/stdio imports. */
_Noreturn void abort(void) { __builtin_trap(); }
