/* SPDX-License-Identifier: GPL-2.0-only */
/* Constructor execution requires isolated VM PID1. Only the explicit late
 * --kmsg-control entry runs pure parser controls on the build host; it returns
 * before all guest setup, device access and failure/reboot paths. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
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

#ifndef LSF_VM_LATE_FD
#define LSF_VM_LATE_FD 0
#endif
#if LSF_VM_LATE_FD != 0 && LSF_VM_LATE_FD != 1
#error Invalid isolated constructor observation mode
#endif
#ifndef LSF_VM_NO_BEGIN
#define LSF_VM_NO_BEGIN 0
#endif
#if (LSF_VM_NO_BEGIN != 0 && LSF_VM_NO_BEGIN != 1) || (LSF_VM_NO_BEGIN && LSF_VM_LATE_FD)
#error Invalid isolated no-BEGIN observation mode
#endif

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

#if LSF_VM_LATE_FD
/* Fixed ABI records are data. Never echo kernel messages or print a kernel
 * physical marker from PID1. UART remains a separate host observation. */
static int log_number(const char **cursor, const char *end, uint64_t maximum,
                      uint64_t *result)
{
    uint64_t value = 0;
    unsigned int digits = 0;
    while (*cursor < end && **cursor >= '0' && **cursor <= '9') {
        unsigned int digit = (unsigned int)(**cursor - '0');
        if (++digits > 20 || value > (maximum - digit) / 10)
            return 0;
        value = value * 10 + digit;
        ++*cursor;
    }
    if (!digits || *cursor >= end || **cursor != ',')
        return 0;
    ++*cursor;
    *result = value;
    return 1;
}

static int log_marker(const char *bytes, size_t length, uint64_t *sequence)
{
    static const char handoff[] =
        "LSFVM1 fd-handoff=original-root opened=2 request=LIVE pending=1\n";
    static const char outside[] =
        "LSFVM1 outside-collector=kthreadd-root-bank-and-actor-refs\n";
    const char *separator, *cursor = bytes, *flag_end;
    uint64_t priority, timestamp;
    unsigned int extensions = 0;
    if (!bytes || !sequence || !length || length > 4096)
        return -1;
    separator = memchr(bytes, ';', length);
    if (!separator || separator - bytes > 256 ||
        !log_number(&cursor, separator, 2047, &priority) ||
        !log_number(&cursor, separator, UINT64_MAX, sequence) ||
        !log_number(&cursor, separator, UINT64_MAX, &timestamp))
        return -1;
    (void)timestamp;
    flag_end = cursor;
    while (flag_end < separator && *flag_end != ',')
        ++flag_end;
    /* The pinned ABI permits bounded unknown metadata fields after flags. */
    for (const char *p = cursor; p < separator; ++p) {
        if (*p < ' ' || *p > '~' || (*p == ',' && ++extensions > 16))
            return -1;
    }
    size_t message_bytes = length - (size_t)(separator + 1 - bytes);
    int result = 0;
    if (message_bytes == sizeof(handoff) - 1 &&
        !memcmp(separator + 1, handoff, sizeof(handoff) - 1))
        result = 1;
    else if (message_bytes == sizeof(outside) - 1 &&
             !memcmp(separator + 1, outside, sizeof(outside) - 1))
        result = 2;
    if (result && !(priority <= 7 && flag_end == cursor + 1 && *cursor == '-'))
        return -1;
    return result;
}

struct log_observation {
    uint64_t last_sequence;
    unsigned int records, total, phase, have_sequence;
};

/* Same pure leaf in hosted finite controls and the actual PID1 event waiter.
 * No syscall, printk, guest failure/reboot path or ownership state is here. */
static int observe_log_record(struct log_observation *state, const char *record, size_t length)
{
    uint64_t sequence;
    if (!state || state->records >= 128 || state->total > 65536 ||
        length > 65536u - state->total)
        return -1;
    int marker = log_marker(record, length, &sequence);
    if (marker < 0 || (state->have_sequence && sequence <= state->last_sequence))
        return -1;
    ++state->records;
    state->total += (unsigned int)length;
    state->last_sequence = sequence;
    state->have_sequence = 1;
    if (marker == 1) {
        if (state->phase != 0)
            return -1;
        state->phase = 1;
    } else if (marker == 2) {
        if (state->phase != 1)
            return -1;
        state->phase = 2;
        return 1;
    }
    return 0;
}

static int kmsg_controls(void)
{
    static const char handoff[] =
        "6,10,123,-;LSFVM1 fd-handoff=original-root opened=2 request=LIVE pending=1\n";
    static const char outside[] =
        "6,11,124,-;LSFVM1 outside-collector=kthreadd-root-bank-and-actor-refs\n";
    static const char extension[] =
        "6,10,123,-,future=value;LSFVM1 fd-handoff=original-root opened=2 request=LIVE pending=1\n";
    static const char *bad[] = {
        "30,10,123,-;LSFVM1 fd-handoff=original-root opened=2 request=LIVE pending=1\n",
        "6,10,123,c;LSFVM1 fd-handoff=original-root opened=2 request=LIVE pending=1\n",
        "2048,10,123,-;ignored\n", "6,18446744073709551616,123,-;ignored\n",
        "6,10,18446744073709551616,-;ignored\n", "6,10,123\n",
        "-1,10,123,-;ignored\n", "6,,123,-;ignored\n",
        "6,10,123,-\n;ignored\n"
    };
    uint64_t sequence;
    unsigned int cases = 0;
    struct log_observation state = {0};
#define CONTROL(test) do { ++cases; if (!(test)) { \
    fputs("KMSG_CONTROL FAIL\n", stderr); return 1; } } while (0)
    CONTROL(observe_log_record(&state, handoff, sizeof(handoff)-1) == 0);
    CONTROL(observe_log_record(&state, outside, sizeof(outside)-1) == 1);
    CONTROL(observe_log_record(&state, outside, sizeof(outside)-1) == -1);
    for (unsigned int i = 0; i < sizeof(bad)/sizeof(bad[0]); ++i)
        CONTROL(log_marker(bad[i], strlen(bad[i]), &sequence) == -1);
    CONTROL(log_marker(extension, sizeof(extension)-1, &sequence) == 1);
    CONTROL(log_marker(handoff, 4097, &sequence) == -1);
    CONTROL(log_marker(handoff, 0, &sequence) == -1);
    state = (struct log_observation){0};
    CONTROL(observe_log_record(&state, outside, sizeof(outside)-1) == -1);
    state = (struct log_observation){0};
    CONTROL(observe_log_record(&state, handoff, sizeof(handoff)-1) == 0);
    CONTROL(observe_log_record(&state, handoff, sizeof(handoff)-1) == -1);
    state = (struct log_observation){.records=128};
    CONTROL(observe_log_record(&state, handoff, sizeof(handoff)-1) == -1);
    state = (struct log_observation){.total=65536};
    CONTROL(observe_log_record(&state, handoff, sizeof(handoff)-1) == -1);
    state = (struct log_observation){.records=127, .total=65536-(sizeof(handoff)-1)};
    CONTROL(observe_log_record(&state, handoff, sizeof(handoff)-1) == 0);
    CONTROL(state.records == 128 && state.total == 65536);
#undef CONTROL
    if (cases != 22)
        return 1;
    puts("KMSG_CONTROL PASS cases=22");
    return 0;
}

static void wait_outside_collector(int log_fd)
{
    uint64_t deadline = now_ns() + 20000000000u;
    unsigned int interruptions = 0;
    struct log_observation state = {0};
    for (;;) {
        char record[4096];
        check(now_ns() < deadline, "outside-collector-event-deadline");
        ssize_t count = read(log_fd, record, sizeof(record));
        if (count > 0) {
            check(now_ns() < deadline, "outside-collector-read-deadline");
            int observed = observe_log_record(&state, record, (size_t)count);
            check(observed >= 0, "kernel-log-observation");
            if (observed == 1) {
                check(now_ns() < deadline, "outside-collector-completion-deadline");
                return;
            }
            continue;
        }
        if (count == -1 && errno == EINTR) {
            check(++interruptions <= 128, "kernel-log-interruption-bound");
            continue;
        }
        /* Overrun/EPIPE and undersized-record/EINVAL lose a real record.
         * Never retry or reconstruct either as a successful observation. */
        check(count == -1 && errno == EAGAIN, "kernel-log-read");
        uint64_t now = now_ns();
        check(now < deadline, "outside-collector-poll-deadline");
        int millis = (int)((deadline - now + 999999u) / 1000000u);
        struct pollfd poll_fd = {.fd = log_fd, .events = POLLIN, .revents = 0};
        int ready = poll(&poll_fd, 1, millis);
        if (ready == -1 && errno == EINTR) {
            check(++interruptions <= 128, "kernel-log-interruption-bound");
            continue;
        }
        check(ready == 1 && (poll_fd.revents & POLLIN) &&
              !(poll_fd.revents & (POLLERR | POLLHUP | POLLNVAL)), "kernel-log-poll");
    }
}
#endif

int main(int argc, char **argv)
{
    unsigned char bytes[24], before[DIAGNOSTIC_BYTES], status[DIAGNOSTIC_BYTES];
    struct timespec delay = {.tv_sec = 0, .tv_nsec = 10000000};
    int fd, second, child_status;
    pid_t child;
    uint64_t retirement_deadline;
#if LSF_VM_LATE_FD
    /* Pure parser controls are the ONLY permitted non-PID1 entry. No mount,
     * /dev/kmsg access, guest finish/reboot or constructor runs in this mode. */
    if (argc == 2 && !strcmp(argv[1], "--kmsg-control"))
        return kmsg_controls();
#endif
    (void)argc;
    (void)argv;
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
#if LSF_VM_NO_BEGIN
    check(close(fd) == 0, "no-begin-descriptor-close");
    /* Only close returning is observed here. The host requires the actual
     * kernel post-physical-return marker, never a synthetic child snapshot. */
    finish(1, "actual-no-begin-descriptor-close-returned");
    return 1; /* No fallthrough to BEGIN even if finish were ever changed. */
#endif
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
#if LSF_VM_LATE_FD
    int log_fd = open("/dev/kmsg", O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    check(log_fd >= 0 && lseek(log_fd, 0, SEEK_END) == 0, "kernel-log-event-reader");
    check(close(fd) == 0, "pending-descriptor-close");
    wait_outside_collector(log_fd);
    check(close(log_fd) == 0, "kernel-log-reader-close");
    finish(1, "actual-pending-fd-retirement-root-release-check");
#endif
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
    /* PID1 observes only close returning. The outside host controller must
     * independently require the kernel's post-physical-return observation. */
    finish(1, "actual-child-retirement-root-release-check");
    return 1;
}
