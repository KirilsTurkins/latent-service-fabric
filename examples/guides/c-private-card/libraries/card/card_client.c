#include "order_worker.h"
#include "card_client.h"
#include <errno.h>
#include <fetch.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* A declared, captured build resource. No runtime filesystem is requested. */
static const unsigned char policy[] = {
#embed "expected-card.txt" suffix(,0)
};

struct card_client {
    struct url *url;
    unsigned identifier;
    unsigned char name[32];
    size_t name_bytes;
};

static int decimal(const unsigned char **cursor, unsigned *value) {
    const unsigned char *p = *cursor;
    unsigned n = 0;
    if (*p < '0' || *p > '9') return 0;
    do {
        unsigned digit = (unsigned)(*p++ - '0');
        if (n > (UINT_MAX - digit) / 10u) return 0;
        n = n * 10u + digit;
    } while (*p >= '0' && *p <= '9');
    *cursor = p;
    *value = n;
    return 1;
}

static int configure(struct card_client *client) {
    if (sizeof(policy) < 13 || sizeof(policy) > 128 || memcmp(policy, "id=", 3)) return 0;
    const unsigned char *p = policy + 3;
    if (!decimal(&p, &client->identifier) || *p++ != '\n') return 0;
    if ((size_t)(p - policy) + 5 > sizeof(policy) || memcmp(p, "name=", 5)) return 0;
    p += 5;
    const unsigned char *begin = p;
    while (*p && *p != '\n') {
        if (*p < 32 || *p == '"' || *p == '\\' || (size_t)(p - begin) >= sizeof(client->name)) return 0;
        ++p;
    }
    if (p == begin || *p++ != '\n' || *p != 0 || (size_t)(p - policy) != sizeof(policy) - 1) return 0;
    client->name_bytes = (size_t)(p - begin) - 1;
    memcpy(client->name, begin, client->name_bytes);
    return 1;
}

struct card_client *card_client_new(const char *url, enum card_status *status) {
    if (!status) return NULL;
    *status = CARD_ARGUMENT;
    if (!url || !*url) return NULL;
    struct card_client *client = calloc(1, sizeof(*client));
    if (!client) { *status = CARD_MEMORY; return NULL; }
    if (!configure(client)) { free(client); *status = CARD_RESOURCE; return NULL; }
    client->url = fetchParseURL(url);
    if (!client->url) {
        int first_errno = errno;
        free(client);
        errno = first_errno;
        *status = CARD_URL;
        return NULL;
    }
    *status = CARD_OK;
    return client;
}

static int domain(const unsigned char *body, size_t size, struct card_client *client,
                  struct card_result *result) {
    if (memchr(body, 0, size)) return 0;
    const unsigned char *id = (const unsigned char *)strstr((const char *)body, "\"id\":");
    const unsigned char *name = (const unsigned char *)strstr((const char *)body, "\"name\":\"");
    unsigned identifier;
    if (!id || !name) return 0;
    id += 5;
    if (!decimal(&id, &identifier) || identifier != client->identifier || (*id != ',' && *id != '}')) return 0;
    name += 8;
    if ((size_t)(name - body) + client->name_bytes + 1 > size
            || memcmp(name, client->name, client->name_bytes) || name[client->name_bytes] != '"') return 0;
    uint32_t checksum = UINT32_C(2166136261);
    for (size_t i = 0; i < size; ++i) checksum = (checksum ^ body[i]) * UINT32_C(16777619);
    *result = (struct card_result){identifier, client->name_bytes, size, checksum};
    return 1;
}

static enum card_status read_card(struct card_client *client, struct card_result *result) {
    if (!client || !result) return CARD_ARGUMENT;
    memset(result, 0, sizeof(*result));
    FILE *stream = fetchGet(client->url, "A");
    if (!stream) return CARD_HTTP;
    unsigned char body[4097];
    size_t used = 0;
    enum card_status status = CARD_OK;
    int first_errno = errno;
    while (used < sizeof(body) - 1) {
        size_t n = fread(body + used, 1, sizeof(body) - 1 - used, stream);
        used += n;
        if (n == 0) {
            if (ferror(stream) || !feof(stream)) { status = CARD_READ; first_errno = errno; }
            break;
        }
    }
    if (status == CARD_OK && used == sizeof(body) - 1) {
        unsigned char excess;
        if (fread(&excess, 1, 1, stream) != 0) { status = CARD_TOO_LARGE; first_errno = errno; }
        else if (ferror(stream) || !feof(stream)) { status = CARD_READ; first_errno = errno; }
    }
    if (fclose(stream) != 0 && status == CARD_OK) { status = CARD_CLOSE; first_errno = errno; }
    if (status != CARD_OK) { errno = first_errno; return status; }
    body[used] = 0;
    return domain(body, used, client, result) ? CARD_OK : CARD_DOMAIN;
}

void card_client_free(struct card_client *client) {
    if (client) { fetchFreeURL(client->url); free(client); }
}

struct request_arguments {
    struct card_client *client;
    struct card_result *result;
};
static int read_order(void *argument) {
    struct request_arguments *args = argument;
    return read_card(args->client, args->result);
}
enum card_status card_client_request(struct card_client *client, struct card_result *result) {
    struct request_arguments args = {client, result};
    int outcome;
    int error = order_run_request(read_order, &args, &outcome);
    if (error) { errno = error; return CARD_HTTP; }
    return (enum card_status)outcome;
}
