
#include <signal.h>
extern void __lsf_c_unsupported_signal_operation(void);
__attribute__((noreturn,noinline)) static void signal_unavailable(void) {
    __lsf_c_unsupported_signal_operation();
    __builtin_trap();
}
void __SIG_ERR(int value) { (void)value;__builtin_trap(); }
void __SIG_IGN(int value) { (void)value;__builtin_trap(); }
void (*signal(int value,void (*handler)(int)))(int) {
    (void)value;(void)handler;signal_unavailable();
}
int raise(int value) { (void)value;signal_unavailable(); }
void (*bsd_signal(int value,void (*handler)(int)))(int) {
    (void)value;(void)handler;signal_unavailable();
}
void (*__sysv_signal(int value,void (*handler)(int)))(int) {
    (void)value;(void)handler;signal_unavailable();
}
