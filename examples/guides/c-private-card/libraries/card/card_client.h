#ifndef CARD_CLIENT_H
#define CARD_CLIENT_H
#include <stddef.h>
#include <stdint.h>

struct card_client;
struct card_result {
    unsigned identifier;
    size_t name_bytes;
    size_t body_bytes;
    uint32_t body_checksum;
};
enum card_status {
    CARD_OK = 0, CARD_ARGUMENT, CARD_RESOURCE, CARD_MEMORY,
    CARD_URL, CARD_HTTP, CARD_READ, CARD_TOO_LARGE, CARD_CLOSE, CARD_DOMAIN
};

/* Constructor/destructor are ordinary calls inside the exported application root. */
struct card_client *card_client_new(const char *url, enum card_status *status);
enum card_status card_client_request(struct card_client *client, struct card_result *result);
void card_client_free(struct card_client *client);
#endif
