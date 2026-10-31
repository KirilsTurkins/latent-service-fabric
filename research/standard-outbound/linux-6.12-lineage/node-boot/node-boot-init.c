/* SPDX-License-Identifier: GPL-2.0-only */
/* The ordinary helper remains source-exact; this PID1 never claims retirement. */
#define main lsf_original_constructor_main
#include "constructor-vm-init.c"
#undef main
#include <sys/stat.h>

int main(void)
{
    struct timespec delay = {0, 10000000};
    unsigned int interrupted = 0;
    int status = 0;
    pid_t child, observed;

    check(getpid() == 1, "node-PID1-only");
    expiry = now_ns() + UINT64_C(20000000000);
    check(mount("devtmpfs", "/dev", "devtmpfs", MS_NOSUID, "mode=0755") == 0,
          "node-devtmpfs");
    check(mount("proc", "/proc", "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC, NULL) == 0,
          "node-proc");
    check(mkdir("/tmp", 01777) == 0 &&
          mount("tmpfs", "/tmp", "tmpfs", MS_NOSUID | MS_NODEV, "size=16m,mode=1777") == 0,
          "node-private-tmp");
    printf("LSFNODEBOOT1 boot=original-node-preparation-only\n");
    fflush(stdout);
    child = fork();
    check(child >= 0, "node-fork");
    if (child == 0) {
        char *const arguments[] = {"/native-init", "--node-capacity-vm-child", NULL};
        char *const environment[] = {"TMPDIR=/tmp", NULL};
        execve(arguments[0], arguments, environment);
        _exit(127);
    }
    for (;;) {
        check(now_ns() < expiry, "node-child-deadline");
        observed = waitpid(child, &status, WNOHANG);
        if (observed == child)
            break;
        check(observed == 0 || (observed < 0 && errno == EINTR && ++interrupted <= 128),
              "node-wait");
        if (nanosleep(&delay, NULL) < 0)
            check(errno == EINTR && ++interrupted <= 128, "node-sleep");
    }
    check(WIFEXITED(status) && WEXITSTATUS(status) == 0, "node-child-result");
    printf("LSFNODEBOOT1 childExit=0\n");
    finish(1, "actual-node-preparation-and-retained-close");
    return 1;
}
