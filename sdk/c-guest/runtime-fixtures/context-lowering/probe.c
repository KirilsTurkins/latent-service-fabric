/* Compiler mechanism control only. The pause import is not a runtime port. */
_Thread_local volatile unsigned counter = 7;
_Thread_local volatile unsigned char scratch[32];
__attribute__((import_module("$root"), import_name("[context-get-1]")))
unsigned context_get(void);
__attribute__((import_module("control"), import_name("pause")))
void pause_control(unsigned value, unsigned stack, unsigned tls);
__attribute__((export_name("context_anchor")))
unsigned context_anchor(void) { return context_get(); }
__attribute__((noinline, export_name("probe")))
unsigned probe(unsigned value) {
    volatile unsigned stack[16];
    for (unsigned i = 0; i < 16; i++) stack[i] = value + i;
    counter += value;
    scratch[value & 31] = (unsigned char)value;
    pause_control(value, (unsigned)stack, (unsigned)&counter);
    return stack[0] + stack[15] + counter;
}
