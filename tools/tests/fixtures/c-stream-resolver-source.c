/* Actual selected-source getaddrinfo control, compiled for pinned wasm32. */
#include <netdb.h>
#include <netinet/in.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define CHECK(x) do { if (!(x)) return __LINE__; } while (0)

static int same_text(const char *left, const char *right) {
    if (!left || !right) return 0;
    while (*left && *left == *right) { ++left; ++right; }
    return *left == *right;
}

#ifdef LSF_C_RESOLVER_TEST_ALLOC
/* This compile-only allocator double targets refusal without invoking the
 * separately unqualified real-libc errno getter. */
static struct { _Alignas(max_align_t) unsigned char data[128]; int used; } slots[4];
static int refuse_allocation, live_allocations, bad_free;
static size_t allocation_request;
void *lsf_test_malloc(size_t size) {
    allocation_request = size;
    if (refuse_allocation || size > sizeof(slots[0].data)) return NULL;
    for (unsigned i = 0; i < 4; ++i) {
        if (!slots[i].used) { slots[i].used = 1; ++live_allocations; return slots[i].data; }
    }
    return NULL;
}
void lsf_test_free(void *value) {
    if (!value) return;
    for (unsigned i = 0; i < 4; ++i) {
        if (value == slots[i].data && slots[i].used) {
            slots[i].used = 0; --live_allocations; return;
        }
    }
    bad_free = 1;
}
#endif

__attribute__((export_name("numeric_resolver_controls")))
int numeric_resolver_controls(void) {
    struct addrinfo hints = {0}, *first = NULL, *second = NULL;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    CHECK(getaddrinfo("127.0.0.1", "8080", &hints, &first) == 0);
    CHECK(first && first->ai_family == AF_INET && first->ai_socktype == SOCK_STREAM);
    CHECK(first->ai_protocol == IPPROTO_TCP && first->ai_addrlen == sizeof(struct sockaddr_in));
    CHECK(first->ai_next == NULL && first->ai_canonname == NULL);
    const struct sockaddr_in *a = (const struct sockaddr_in *)first->ai_addr;
    const uint8_t *octets = (const uint8_t *)&a->sin_addr;
    const uint8_t *port = (const uint8_t *)&a->sin_port;
    CHECK(a->sin_family == AF_INET && octets[0] == 127 && octets[1] == 0 && octets[2] == 0 && octets[3] == 1);
    CHECK(port[0] == 0x1f && port[1] == 0x90);
    CHECK(getaddrinfo("198.51.100.7", "443", &hints, &second) == 0);
    CHECK(second && second != first && second->ai_addr != first->ai_addr);
    CHECK(octets[0] == 127 && octets[3] == 1 && port[0] == 0x1f && port[1] == 0x90);
    freeaddrinfo(second);
    freeaddrinfo(first);

    first = NULL;
    CHECK(getaddrinfo("example.com", "443", &hints, &first) == EAI_NONAME && first == NULL);
    CHECK(getaddrinfo("localhost", "443", &hints, &first) == EAI_NONAME && first == NULL);
    CHECK(getaddrinfo("127.0.0.01", "443", &hints, &first) == EAI_NONAME && first == NULL);
    CHECK(getaddrinfo("256.0.0.1", "443", &hints, &first) == EAI_NONAME && first == NULL);
    CHECK(getaddrinfo("127.0.0.1", "https", &hints, &first) == EAI_SERVICE && first == NULL);
    CHECK(getaddrinfo("127.0.0.1", "65536", &hints, &first) == EAI_SERVICE && first == NULL);
    CHECK(getaddrinfo(NULL, "80", &hints, &first) == EAI_NONAME && first == NULL);
    CHECK(getaddrinfo("1.2.3.4.5", "80", &hints, &first) == EAI_NONAME && first == NULL);
    hints.ai_flags = AI_CANONNAME;
    char literal[] = "127.0.0.1";
    CHECK(getaddrinfo(literal, "80", &hints, &first) == 0 && first);
    CHECK(first->ai_canonname != literal && same_text(first->ai_canonname, "127.0.0.1"));
    literal[0] = '9';
    CHECK(same_text(first->ai_canonname, "127.0.0.1"));
    hints.ai_flags = AI_CANONNAME | AI_NUMERICHOST | AI_NUMERICSERV;
    CHECK(getaddrinfo("255.255.255.255", "443", &hints, &second) == 0 && second);
    CHECK(second != first && second->ai_canonname != first->ai_canonname);
    CHECK(same_text(second->ai_canonname, "255.255.255.255"));
    freeaddrinfo(first); first = NULL;
    CHECK(same_text(second->ai_canonname, "255.255.255.255"));
    freeaddrinfo(second); second = NULL;
    CHECK(getaddrinfo("0.9.10.100", NULL, &hints, &first) == 0 && first);
    CHECK(same_text(first->ai_canonname, "0.9.10.100"));
    freeaddrinfo(first); first = NULL;
    CHECK(getaddrinfo("99.101.200.255", "0", &hints, &first) == 0 && first);
    CHECK(same_text(first->ai_canonname, "99.101.200.255"));
    freeaddrinfo(first); first = NULL;
    CHECK(getaddrinfo("example.com", "443", &hints, &first) == EAI_NONAME && first == NULL);
    hints.ai_flags = AI_ADDRCONFIG;
    CHECK(getaddrinfo("127.0.0.1", "80", &hints, &first) == EAI_BADFLAGS && first == NULL);
    hints.ai_flags = AI_CANONNAME | AI_PASSIVE;
    CHECK(getaddrinfo("127.0.0.1", "80", &hints, &first) == EAI_BADFLAGS && first == NULL);
    hints.ai_flags = AI_NUMERICHOST | AI_NUMERICSERV;
    CHECK(getaddrinfo("127.0.0.1", "https", &hints, &first) == EAI_NONAME && first == NULL);
    CHECK(getaddrinfo("203.0.113.9", NULL, &hints, &first) == 0 && first);
    CHECK(((const uint8_t *)&((const struct sockaddr_in *)first->ai_addr)->sin_port)[0] == 0);
    CHECK(((const uint8_t *)&((const struct sockaddr_in *)first->ai_addr)->sin_port)[1] == 0);
    freeaddrinfo(first); first = NULL;
    hints.ai_family = AF_INET6;
    CHECK(getaddrinfo("127.0.0.1", "80", &hints, &first) == EAI_FAMILY && first == NULL);
    hints.ai_family = AF_INET; hints.ai_socktype = SOCK_DGRAM;
    CHECK(getaddrinfo("127.0.0.1", "80", &hints, &first) == EAI_SOCKTYPE && first == NULL);
#ifdef LSF_C_RESOLVER_TEST_ALLOC
    CHECK(live_allocations == 0 && !bad_free);
#endif
    return 0;
}

#ifdef LSF_C_RESOLVER_TEST_ALLOC
__attribute__((export_name("numeric_resolver_allocation_refusal")))
int numeric_resolver_allocation_refusal(void) {
    struct addrinfo hints = {.ai_family = AF_INET, .ai_socktype = SOCK_STREAM};
    struct addrinfo *result = (struct addrinfo *)(uintptr_t)1;
    refuse_allocation = 1;
    CHECK(getaddrinfo("127.0.0.1", "8080", &hints, &result) == EAI_MEMORY);
    CHECK(result == NULL && live_allocations == 0 && !bad_free);
    refuse_allocation = 0;
    CHECK(getaddrinfo("127.0.0.1", "8080", &hints, &result) == 0 && result);
    size_t original_request = allocation_request;
    CHECK(live_allocations == 1);
    freeaddrinfo(result);
    CHECK(live_allocations == 0 && !bad_free);
    hints.ai_flags = AI_CANONNAME; refuse_allocation = 1;
    CHECK(getaddrinfo("127.0.0.1", "8080", &hints, &result) == EAI_MEMORY);
    CHECK(allocation_request == original_request + sizeof("127.0.0.1"));
    CHECK(result == NULL && live_allocations == 0 && !bad_free);
    refuse_allocation = 0;
    CHECK(getaddrinfo("127.0.0.1", "8080", &hints, &result) == 0 && result);
    CHECK(same_text(result->ai_canonname, "127.0.0.1") && live_allocations == 1);
    freeaddrinfo(result);
    CHECK(live_allocations == 0 && !bad_free);
    return 0;
}
#endif
