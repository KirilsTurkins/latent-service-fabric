/* SPDX-License-Identifier: Apache-2.0
 * A bounded numeric-only getaddrinfo for the selected IPv4 stream profile.
 * It parses locally, creates no network request and grants no authority.
 */
#include <netdb.h>
#include <netinet/in.h>
#include <stdint.h>
#include <stdlib.h>

struct numeric_address {
    struct addrinfo info;
    struct sockaddr_in address;
};

/* Match the pinned libc's strict dotted-decimal IPv4 spelling. */
static int numeric_ipv4(const char *name, uint8_t bytes[4]) {
    if (!name) return 0;
    for (unsigned index = 0; index < 4; ++index) {
        unsigned number = 0, count = 0;
        const char *start = name;
        while (count < 3 && *name >= '0' && *name <= '9') {
            number = number * 10u + (unsigned)(*name++ - '0');
            ++count;
        }
        if (!count || (count > 1 && *start == '0') || number > 255) return 0;
        bytes[index] = (uint8_t)number;
        if (index == 3) return *name == '\0';
        if (*name++ != '.') return 0;
    }
    return 0;
}

static int numeric_port(const char *service, int flags, uint16_t *port) {
    if (!service) { *port = 0; return 0; }
    unsigned value = 0, count = 0;
    while (count < 5 && *service >= '0' && *service <= '9') {
        value = value * 10u + (unsigned)(*service++ - '0');
        ++count;
    }
    if (!count || *service) {
        if ((flags & AI_NUMERICSERV) && (*service < '0' || *service > '9')) return EAI_NONAME;
        return EAI_SERVICE;
    }
    if (value > 65535u) return EAI_SERVICE;
    *port = (uint16_t)value;
    return 0;
}

int getaddrinfo(const char *restrict name, const char *restrict service,
                const struct addrinfo *restrict hints, struct addrinfo **restrict result) {
    if (!result) return EAI_FAIL;
    *result = NULL;
    int flags = hints ? hints->ai_flags : 0;
    if ((flags & ~(AI_NUMERICHOST | AI_NUMERICSERV)) ||
        (hints && (hints->ai_addrlen || hints->ai_addr || hints->ai_canonname || hints->ai_next)))
        return EAI_BADFLAGS;
    if (hints && hints->ai_family != AF_UNSPEC && hints->ai_family != AF_INET) return EAI_FAMILY;
    if (hints && hints->ai_socktype && hints->ai_socktype != SOCK_STREAM) return EAI_SOCKTYPE;
    if (hints && hints->ai_protocol && hints->ai_protocol != IPPROTO_TCP) return EAI_SOCKTYPE;
    uint8_t bytes[4];
    uint16_t port;
    if (!numeric_ipv4(name, bytes)) return EAI_NONAME;
    int service_error = numeric_port(service, flags, &port);
    if (service_error) return service_error;
    struct numeric_address *owned = malloc(sizeof(*owned));
    if (!owned) return EAI_MEMORY;
    *owned = (struct numeric_address){0};
    owned->info.ai_flags = flags;
    owned->info.ai_family = AF_INET;
    owned->info.ai_socktype = SOCK_STREAM;
    owned->info.ai_protocol = IPPROTO_TCP;
    owned->info.ai_addrlen = sizeof(owned->address);
    owned->info.ai_addr = (struct sockaddr *)&owned->address;
    owned->address.sin_family = AF_INET;
    uint8_t *ip = (uint8_t *)&owned->address.sin_addr;
    uint8_t *port_bytes = (uint8_t *)&owned->address.sin_port;
    for (unsigned index = 0; index < 4; ++index) ip[index] = bytes[index];
    port_bytes[0] = (uint8_t)(port >> 8);
    port_bytes[1] = (uint8_t)port;
    *result = &owned->info;
    return 0;
}

void freeaddrinfo(struct addrinfo *result) { free(result); }
