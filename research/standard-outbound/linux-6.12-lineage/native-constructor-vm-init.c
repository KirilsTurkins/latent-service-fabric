/* SPDX-License-Identifier: GPL-2.0-only */
/* Only this tiny supervisor is PID1. Its child is the actual Rust caller.
 * The existing probe's pure ABI parser/helpers are reused, never its constructor.
 * --native-kmsg-control is a pure, pre-setup build-host parser entry only. */
#define LSF_VM_LATE_FD 1
#define main original_constructor_vm_main
#include "constructor-vm-init.c"
#undef main

/* Validate every header with the maintained parser first. Recognize the shared
 * post-physical-return record too, but never echo it onto the UART. */
static int native_record(struct log_observation *state, const char *record, size_t length)
{
    static const char physical[] =
        "LSFVM1 physical-return=constructor-root-bank-and-actor-refs\n";
    uint64_t sequence, priority, timestamp;
    const char *separator, *cursor = record;
    if (!state || state->records >= 128 || state->total > 65536 ||
        length > 65536u - state->total || log_marker(record, length, &sequence) < 0)
        return -1;
    if (state->have_sequence && sequence <= state->last_sequence)
        return -1;
    separator = memchr(record, ';', length);
    if (!separator || !log_number(&cursor, separator, 2047, &priority) ||
        !log_number(&cursor, separator, UINT64_MAX, &sequence) ||
        !log_number(&cursor, separator, UINT64_MAX, &timestamp))
        return -1;
    (void)timestamp;
    size_t bytes = length - (size_t)(separator + 1 - record);
    int matched = bytes == sizeof(physical) - 1 &&
        !memcmp(separator + 1, physical, sizeof(physical) - 1);
    if (matched && (priority > 7 || cursor >= separator || *cursor != '-' ||
        (cursor + 1 != separator && cursor[1] != ',') || state->phase))
        return -1;
    ++state->records;
    state->total += (unsigned int)length;
    state->last_sequence = sequence;
    state->have_sequence = 1;
    if (matched) state->phase = 1;
    return matched;
}

static int native_kmsg_controls(void)
{
    struct log_observation state = {0};
    static const char good[] =
        "6,1,2,-;LSFVM1 physical-return=constructor-root-bank-and-actor-refs\n";
    static const char later[] =
        "6,2,2,-;LSFVM1 physical-return=constructor-root-bank-and-actor-refs\n";
    static const char user[] =
        "14,1,2,-;LSFVM1 physical-return=constructor-root-bank-and-actor-refs\n";
    static const char fragment[] =
        "6,1,2,c;LSFVM1 physical-return=constructor-root-bank-and-actor-refs\n";
    static const char overflow[] = "6,18446744073709551616,2,-;unrelated\n";
    static const char bad_time[] = "6,1,x,-;unrelated\n";
    static const char unknown[] = "6,1,2,-,future=value;unrelated\n";
    char large[4097] = {0};
    unsigned int cases = 0;
#define CONTROL(expression) do { if (!(expression)) return 2; ++cases; } while (0)
    CONTROL(native_record(&state, good, sizeof(good)-1) == 1);
    CONTROL(native_record(&state, later, sizeof(later)-1) == -1);
    state = (struct log_observation){0};
    CONTROL(native_record(&state, user, sizeof(user)-1) == -1);
    CONTROL(native_record(&state, fragment, sizeof(fragment)-1) == -1);
    CONTROL(native_record(&state, overflow, sizeof(overflow)-1) == -1);
    CONTROL(native_record(&state, bad_time, sizeof(bad_time)-1) == -1);
    CONTROL(native_record(&state, large, sizeof(large)) == -1);
    CONTROL(native_record(&state, unknown, sizeof(unknown)-1) == 0);
    CONTROL(native_record(&state, good, sizeof(good)-1) == -1);
    state = (struct log_observation){.records = 128};
    CONTROL(native_record(&state, good, sizeof(good)-1) == -1);
    state = (struct log_observation){.total = 65536};
    CONTROL(native_record(&state, good, sizeof(good)-1) == -1);
    state = (struct log_observation){0};
    CONTROL(native_record(&state, good, sizeof(good)-2) == 0);
#undef CONTROL
    if (cases != 12) return 2;
    puts("LSFNATIVE1 kmsg-controls=PASS cases=12");
    return 0;
}

int main(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1], "--native-kmsg-control"))
        return native_kmsg_controls(); /* No mount/child/device/finish on host. */
    if (getpid() != 1) return 2;
    setvbuf(stdout, NULL, _IONBF, 0);
    check(mount("devtmpfs", "/dev", "devtmpfs", MS_NOSUID | MS_NOEXEC, "") == 0,
          "native-devtmpfs");
    check(mount("proc", "/proc", "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC, "") == 0,
          "native-proc");
    check(mount("tmpfs", "/tmp", "tmpfs", MS_NOSUID | MS_NODEV | MS_NOEXEC,
                "size=16m,mode=1777") == 0, "native-temporary-files");
    puts("LSFVM1 boot=native-constructor-only production-sockets=disabled");
    int log_fd = open("/dev/kmsg", O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    check(log_fd >= 0 && lseek(log_fd, 0, SEEK_END) >= 0, "native-kmsg-start");
    uint64_t deadline = now_ns() + 20000000000u;
    pid_t child = fork();
    check(child >= 0, "native-child-create");
    if (!child) {
        char *arguments[] = {"/native-init", "--constructor-vm-child", NULL};
        char *environment[] = {"TMPDIR=/tmp", NULL};
        execve(arguments[0], arguments, environment);
        _exit(2);
    }
    unsigned int interruptions = 0;
    int child_done = 0;
    struct log_observation state = {0};
    for (;;) {
        char record[4096];
        check(now_ns() < deadline, "native-overall-event-deadline");
        if (!child_done) {
            int status = 0;
            pid_t result = waitpid(child, &status, WNOHANG);
            if (result == child) {
                check(WIFEXITED(status) && WEXITSTATUS(status) == 0, "native-child-status");
                child_done = 1;
            } else if (result == -1 && errno == EINTR) {
                check(++interruptions <= 128, "native-interruption-bound");
            } else check(result == 0, "native-child-wait");
        }
        ssize_t count = read(log_fd, record, sizeof(record));
        if (count > 0) {
            check(now_ns() < deadline, "native-postread-deadline");
            check(native_record(&state, record, (size_t)count) >= 0, "native-kmsg-record");
        } else if (count == -1 && errno == EINTR) {
            check(++interruptions <= 128, "native-interruption-bound");
            continue;
        } else check(count == -1 && errno == EAGAIN, "native-kmsg-read");
        if (child_done && state.phase == 1) {
            check(now_ns() < deadline, "native-terminal-deadline");
            check(close(log_fd) == 0, "native-kmsg-close");
            finish(1, "actual-native-constructor-and-kernel-return");
            return 1;
        }
        uint64_t now = now_ns();
        check(now < deadline, "native-poll-deadline");
        int milliseconds = (int)((deadline-now+999999u)/1000000u);
        if (milliseconds > 10) milliseconds = 10; /* Also observe real child exit. */
        struct pollfd waiting = {.fd = log_fd, .events = POLLIN, .revents = 0};
        int result = poll(&waiting, 1, milliseconds);
        if (result == -1 && errno == EINTR) {
            check(++interruptions <= 128, "native-interruption-bound");
            continue;
        }
        check(result == 0 || (result == 1 && (waiting.revents & POLLIN) &&
              !(waiting.revents & (POLLERR | POLLHUP | POLLNVAL))), "native-kmsg-poll");
    }
}
