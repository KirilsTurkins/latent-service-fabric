/* Captured ordinary C application for the combined-profile build control. */
#include "probe.h"
#include <netdb.h>
#include <netinet/in.h>
#include <stdio.h>
#include <sys/socket.h>
#include <unistd.h>

static bool failed(probe_string_t *name, probe_string_t *error, int descriptor) {
    if (descriptor >= 3) (void)close(descriptor);
    probe_string_free(name);
    probe_string_dup(error, "combined-profile-control-failed");
    return false;
}

bool exports_examples_greeting_api_greet(probe_string_t *name, probe_string_t *value,
                                        probe_string_t *error) {
    int descriptor = socket(AF_INET, SOCK_STREAM, 0);
    if (descriptor != 3 || write(1, "out", 3) != 3 || write(2, "err", 3) != 3 ||
        fprintf(stderr, "stdio\n") < 0 || write(0, "in", 2) != -1 || close(1) != -1)
        return failed(name, error, descriptor);
    struct addrinfo hints = {.ai_family = AF_INET, .ai_socktype = SOCK_STREAM};
    struct addrinfo *selected = NULL;
    if (getaddrinfo("127.0.0.1", "8080", &hints, &selected) || !selected)
        return failed(name, error, descriptor);
    if (selected->ai_family != AF_INET || !selected->ai_addr ||
        selected->ai_addrlen != sizeof(struct sockaddr_in)) {
        freeaddrinfo(selected);
        return failed(name, error, descriptor);
    }
    struct sockaddr_in peer = *(const struct sockaddr_in *)selected->ai_addr;
    freeaddrinfo(selected);
    selected = NULL;
    int failure = getaddrinfo("example.com", "80", &hints, &selected);
    if (failure != EAI_NONAME || selected) {
        if (selected) freeaddrinfo(selected);
        return failed(name, error, descriptor);
    }
    if (name->len && name->ptr[0] == 'c') {
        if (connect(descriptor, (struct sockaddr *)&peer, sizeof(peer)) != 0 ||
            write(descriptor, "xyz", 3) < 0) return failed(name, error, descriptor);
    } else if (write(descriptor, "xyz", 3) != -1) {
        return failed(name, error, descriptor);
    }
    if (close(descriptor) != 0) return failed(name, error, -1);
    probe_string_free(name);
    probe_string_dup(value, "ok");
    return true;
}
