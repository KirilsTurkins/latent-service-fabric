/* Captured ordinary C application for the combined-profile build control. */
#include "probe.h"
#include <netinet/in.h>
#include <stdio.h>
#include <sys/socket.h>
#include <unistd.h>

static bool failed(probe_string_t *name, probe_string_t *error) {
    probe_string_free(name);
    probe_string_dup(error, "combined-profile-control-failed");
    return false;
}

bool exports_examples_greeting_api_greet(probe_string_t *name, probe_string_t *value,
                                        probe_string_t *error) {
    int descriptor = socket(AF_INET, SOCK_STREAM, 0);
    if (descriptor != 3 || write(1, "out", 3) != 3 || write(2, "err", 3) != 3 ||
        fprintf(stderr, "stdio\n") < 0 || write(0, "in", 2) != -1 || close(1) != -1)
        return failed(name, error);
    if (name->len && name->ptr[0] == 'c') {
        struct sockaddr_in peer = {.sin_family = AF_INET};
        unsigned char *host = (unsigned char *)&peer.sin_addr;
        unsigned char *port = (unsigned char *)&peer.sin_port;
        host[0] = 127; host[1] = 0; host[2] = 0; host[3] = 1;
        port[0] = 0x1f; port[1] = 0x90;
        if (connect(descriptor, (struct sockaddr *)&peer, sizeof(peer)) != 0 ||
            write(descriptor, "xyz", 3) < 0) return failed(name, error);
    } else if (write(descriptor, "xyz", 3) != -1) {
        return failed(name, error);
    }
    if (close(descriptor) != 0) return failed(name, error);
    probe_string_free(name);
    probe_string_dup(value, "ok");
    return true;
}
