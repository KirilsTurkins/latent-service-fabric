/* Standalone linear-stack layout witness, not a Java/compiler qualification. */
static volatile unsigned char marker[65536];

__attribute__((export_name("marker_address")))
unsigned marker_address(void) {
    return (unsigned)(unsigned long)marker;
}

__attribute__((export_name("within"), noinline))
unsigned within(void) {
    volatile unsigned char frame[4096];
    frame[0] = 17;
    frame[4095] = 25;
    __asm__ volatile("" : : "r"(frame) : "memory");
    return frame[0] + frame[4095];
}

__attribute__((export_name("exhaust"), noinline))
unsigned exhaust(void) {
    volatile unsigned char frame[70000];
    frame[0] = 123;
    frame[69999] = 1;
    __asm__ volatile("" : : "r"(frame) : "memory");
    return frame[0] + frame[69999];
}
