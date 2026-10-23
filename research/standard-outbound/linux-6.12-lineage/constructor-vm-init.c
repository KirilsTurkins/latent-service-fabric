/* SPDX-License-Identifier: GPL-2.0-only */
/* Isolated VM PID1 only. Never run this programme on the build/physical host. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

enum { MAGIC = 0x4c534646, VERSION = 2, BEGIN = 1, WAIT = 2, CLOSE_REQUEST = 3 };
enum { PENDING = 1, READY = 2, CLOSED = 4, DIAGNOSTIC_BYTES = 104 };
static const char device[] = "/dev/lsf-stream-factory";
static uint64_t expiry;

static void finish(int success, const char *stage)
{
    printf("LSFVM1 result=%s stage=%s\n", success ? "PASS" : "FAIL", stage);
    fflush(stdout);
    if (getpid() == 1) {
        (void)reboot(RB_POWER_OFF);
        for (;;)
            pause(); /* Host deadline is failure if poweroff itself fails. */
    }
    _exit(success ? 0 : 1);
}

static void check(int value, const char *stage)
{
    if (!value)
        finish(0, stage);
}

static uint64_t now_ns(void)
{
    struct timespec now;
    check(clock_gettime(CLOCK_MONOTONIC, &now) == 0 && now.tv_sec >= 0 &&
          (uint64_t)now.tv_sec <= (UINT64_MAX - 999999999u) / 1000000000u,
          "monotonic-clock");
    return (uint64_t)now.tv_sec * 1000000000u + (uint64_t)now.tv_nsec;
}

static uint64_t little(const unsigned char *bytes, unsigned int size)
{
    uint64_t result = 0;
    for (unsigned int i = 0; i < size; ++i)
        result |= (uint64_t)bytes[i] << (i * 8);
    return result;
}

static void put(unsigned char *bytes, uint64_t value, unsigned int size)
{
    for (unsigned int i = 0; i < size; ++i)
        bytes[i] = (unsigned char)(value >> (i * 8));
}

static void request(unsigned char bytes[24], unsigned int operation, uint64_t deadline)
{
    memset(bytes, 0, 24);
    put(bytes, MAGIC, 4);
    put(bytes + 4, VERSION, 4);
    put(bytes + 8, operation, 4);
    put(bytes + 16, deadline, 8);
}

static void observe(int fd, unsigned char bytes[DIAGNOSTIC_BYTES])
{
    check(read(fd, bytes, DIAGNOSTIC_BYTES) == DIAGNOSTIC_BYTES, "diagnostic-read");
    check(little(bytes, 4) == MAGIC && little(bytes + 4, 4) == VERSION,
          "diagnostic-version");
    check(little(bytes + 16, 8) == expiry, "immutable-expiry");
}

static void snapshot(const char *name, const unsigned char bytes[DIAGNOSTIC_BYTES])
{
    printf("LSFVM1 snapshot=%s state=%" PRIu64 " error=%" PRIu64, name,
           little(bytes + 8, 4), little(bytes + 12, 4));
    for (unsigned int i = 0; i < 10; ++i)
        printf(" field%u=%" PRIu64, i, little(bytes + 24 + i * 8, 8));
    printf("\n");
}

static int terminal(const unsigned char bytes[DIAGNOSTIC_BYTES])
{
    /* Source-derived expectations for actual Task/Control/child retirement.
     * The original backing view and real Root remain held by this FD.
     * Both are LIVE records; this is NOT Root final-free. */
    static const uint64_t fields[] = {8, 5, 0, 2, 0, 1, 2, 0, 1, 1};
    if (little(bytes + 8, 4) != CLOSED || little(bytes + 12, 4))
        return 0;
    for (unsigned int i = 0; i < 10; ++i)
        if (little(bytes + 24 + i * 8, 8) != fields[i])
            return 0;
    return 1;
}

int main(void)
{
    unsigned char bytes[24], before[DIAGNOSTIC_BYTES], status[DIAGNOSTIC_BYTES];
    struct timespec delay = {.tv_sec = 0, .tv_nsec = 10000000};
    int fd, second, child_status;
    pid_t child;
    uint64_t retirement_deadline;
    if (getpid() != 1) {
        fputs("Isolated VM PID1 required; refusing host execution.\n", stderr);
        return 2;
    }
    setvbuf(stdout, NULL, _IONBF, 0);
    check(mount("devtmpfs", "/dev", "devtmpfs", MS_NOSUID | MS_NOEXEC, "") == 0,
          "devtmpfs-mount");
    puts("LSFVM1 boot=constructor-only production-sockets=disabled");
    fd = open(device, O_RDWR | O_CLOEXEC);
    check(fd >= 0, "original-factory-open");
    observe(fd, before);
    snapshot("opened", before);
    check(little(before + 8, 4) == 0 && little(before + 12, 4) == 0,
          "open-is-not-ready");
    second = open(device, O_RDWR | O_CLOEXEC);
    check(second == -1 && errno == EBUSY, "second-open-refused");
    request(bytes, BEGIN, now_ns() + 20000000000u);
    bytes[4] ^= 1;
    check(write(fd, bytes, sizeof(bytes)) == -1 && errno == EINVAL,
          "wrong-version-before-birth");
    observe(fd, status);
    check(memcmp(before, status, sizeof(status)) == 0, "invalid-request-preserves-original");
    child = fork();
    check(child >= 0, "ordinary-fork");
    if (!child) {
        request(bytes, BEGIN, now_ns() + 20000000000u);
        int denied = write(fd, bytes, sizeof(bytes)) == -1 && errno == EPERM;
        _exit(denied ? 0 : 1);
    }
    check(waitpid(child, &child_status, 0) == child && WIFEXITED(child_status) &&
          WEXITSTATUS(child_status) == 0, "foreign-fd-actor-refused");
    observe(fd, status);
    check(memcmp(before, status, sizeof(status)) == 0, "foreign-request-preserves-original");
    expiry = now_ns() + 20000000000u;
    request(bytes, BEGIN, expiry);
    ssize_t admitted = write(fd, bytes, sizeof(bytes));
    if (admitted != (ssize_t)sizeof(bytes)) {
        int admission_error = errno;
        /* Numeric refusal evidence only. An early refusal may preserve the
         * original zero expiry, so do not apply observe's post-BEGIN check. */
        ssize_t observed = read(fd, status, sizeof(status));
        printf("LSFVM1 begin-refusal result=%jd errno=%u diagnostic-bytes=%jd\n",
               (intmax_t)admitted, (unsigned)admission_error, (intmax_t)observed);
        if (observed == (ssize_t)sizeof(status) && little(status, 4) == MAGIC &&
            little(status + 4, 4) == VERSION)
            snapshot("begin-refused", status);
        finish(0, "full-constructor-begin");
    }
    observe(fd, status);
    for (unsigned int attempt = 0; little(status + 8, 4) == PENDING && attempt < 16; ++attempt) {
        check(now_ns() < expiry, "pending-expiry");
        request(bytes, WAIT, expiry);
        check(write(fd, bytes, sizeof(bytes)) == (ssize_t)sizeof(bytes), "paid-constructor-wait");
        observe(fd, status);
    }
    snapshot("ready", status);
    check(little(status + 8, 4) == READY && little(status + 12, 4) == 0,
          "actual-constructor-ready");
    memcpy(before, status, sizeof(before));
    request(bytes, WAIT, expiry + 1);
    check(write(fd, bytes, sizeof(bytes)) == -1 && errno == EINVAL, "expiry-widening-refused");
    request(bytes, BEGIN, expiry);
    check(write(fd, bytes, sizeof(bytes)) == -1 && errno == EALREADY, "duplicate-birth-refused");
    observe(fd, status);
    /* Creator users and Control readers can retire independently of refusal.
     * Preserve immutable status/expiry and the one original positive birth;
     * require exact terminal counters only after the physical close drain. */
    check(memcmp(before, status, 24) == 0 &&
          little(status + 24, 8) == 3 && little(status + 32, 8) == 0 &&
          little(status + 40, 8) <= 1 && little(status + 48, 8) == 1 &&
          little(status + 56, 8) >= 1 && little(status + 56, 8) <= 256 &&
          little(status + 64, 8) == 0 && little(status + 72, 8) >= 6 &&
          little(status + 72, 8) <= 256 &&
          little(status + 80, 8) <= little(status + 72, 8) &&
          little(status + 88, 8) == 0 && little(status + 96, 8) == 0,
          "refused-retry-preserves-original");
    request(bytes, CLOSE_REQUEST, expiry);
    check(write(fd, bytes, sizeof(bytes)) == (ssize_t)sizeof(bytes), "physical-cleanup-request");
    retirement_deadline = now_ns() + 20000000000u;
    do {
        observe(fd, status);
        if (terminal(status))
            break;
        if (now_ns() >= retirement_deadline) {
            snapshot("retirement-failed", status);
            finish(0, "unproven-child-retirement");
        }
        (void)nanosleep(&delay, NULL);
    } while (1);
    snapshot("child-retired-root-held", status);
    check(close(fd) == 0, "descriptor-close");
    finish(1, "actual-child-retirement-root-final-free-unqualified");
    return 1;
}
