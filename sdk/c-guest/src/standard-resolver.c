/* SPDX-License-Identifier: Apache-2.0
 * A bounded numeric-only resolver for the selected IPv4 stream profile.
 * It parses locally, creates no network request and grants no authority.
 */
#ifdef gai_strerror
#error "gai_strerror is owned by the selected numeric resolver"
#endif
#ifdef getnameinfo
#error "getnameinfo is owned by the selected numeric resolver"
#endif
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

/* Format only the parsed address; do not associate it with a hostname. */
static size_t numeric_canonical_name(const uint8_t bytes[4], char output[16]) {
    size_t length = 0;
    for (unsigned index = 0; index < 4; ++index) {
        unsigned value = bytes[index];
        if (index) output[length++] = '.';
        if (value >= 100) output[length++] = (char)('0' + value / 100);
        if (value >= 10) output[length++] = (char)('0' + (value / 10) % 10);
        output[length++] = (char)('0' + value % 10);
    }
    output[length++] = '\0';
    return length;
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
    if ((flags & ~(AI_NUMERICHOST | AI_NUMERICSERV | AI_CANONNAME)) ||
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
    char canonical[16];
    size_t canonical_length = (flags & AI_CANONNAME) ? numeric_canonical_name(bytes, canonical) : 0;
    struct numeric_address *owned = malloc(sizeof(*owned) + canonical_length);
    if (!owned) return EAI_MEMORY;
    *owned = (struct numeric_address){0};
    if (canonical_length) {
        owned->info.ai_canonname = (char *)(owned + 1);
        for (size_t index = 0; index < canonical_length; ++index)
            owned->info.ai_canonname[index] = canonical[index];
    }
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

/* Render an already supplied IPv4 address without reverse DNS or services. */
int getnameinfo(const struct sockaddr *restrict address, socklen_t address_length,
                char *restrict host, socklen_t host_length,
                char *restrict service, socklen_t service_length, int flags) {
    if (flags & ~(NI_NUMERICHOST | NI_NUMERICSERV)) return EAI_BADFLAGS;
    if (!address || address_length < sizeof(struct sockaddr_in)) return EAI_FAMILY;
    struct sockaddr_in input;
    uint8_t *destination = (uint8_t *)&input;
    const uint8_t *source = (const uint8_t *)address;
    for (size_t index = 0; index < sizeof(input); ++index) destination[index] = source[index];
    if (input.sin_family != AF_INET) return EAI_FAMILY;
    if ((host && host_length && !(flags & NI_NUMERICHOST)) ||
        (service && service_length && !(flags & NI_NUMERICSERV))) return EAI_NONAME;
    if (host && host_length) {
        char value[16];
        size_t length = numeric_canonical_name((const uint8_t *)&input.sin_addr, value);
        if (length > host_length) return EAI_OVERFLOW;
        for (size_t index = 0; index < length; ++index) host[index] = value[index];
    }
    if (service && service_length) {
        const uint8_t *bytes = (const uint8_t *)&input.sin_port;
        unsigned port = (unsigned)bytes[0] * 256u + bytes[1];
        char value[6];
        size_t start = sizeof(value);
        value[--start] = '\0';
        do { value[--start] = (char)('0' + port % 10); port /= 10; } while (port);
        size_t length = sizeof(value) - start;
        if (length > service_length) return EAI_OVERFLOW;
        for (size_t index = 0; index < length; ++index) service[index] = value[start + index];
    }
    return 0;
}

/* Match the pinned libc's C-locale diagnostics without allocating or
 * consulting an ambient resolver. Unknown values remain explicit. */
const char *gai_strerror(int error) {
    if (error == EAI_BADFLAGS) return "Invalid flags";
    if (error == EAI_NONAME) return "Name does not resolve";
    if (error == EAI_AGAIN) return "Try again";
    if (error == EAI_FAIL) return "Non-recoverable error";
#ifdef EAI_NODATA
    if (error == EAI_NODATA) return "Name has no usable address";
#endif
    if (error == EAI_FAMILY) return "Unrecognized address family or invalid length";
    if (error == EAI_SOCKTYPE) return "Unrecognized socket type";
    if (error == EAI_SERVICE) return "Unrecognized service";
    if (error == EAI_MEMORY) return "Out of memory";
    if (error == EAI_SYSTEM) return "System error";
    if (error == EAI_OVERFLOW) return "Overflow";
    return "Unknown error";
}
