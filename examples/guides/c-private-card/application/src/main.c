#include "probe.h"
#include "card_client.h"
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

bool exports_examples_libfetch_api_run(probe_string_t *input, probe_string_t *result,
                                       probe_string_t *error) {
    if (!input->len || input->len > 8192 || memchr(input->ptr, 0, input->len)) {
        probe_string_free(input); probe_string_dup(error, "invalid-url"); return false;
    }
    char *url = malloc(input->len + 1);
    if (!url) { probe_string_free(input); probe_string_dup(error, "url-memory"); return false; }
    memcpy(url, input->ptr, input->len); url[input->len] = 0;
    probe_string_free(input);
    enum card_status status;
    struct card_client *client = card_client_new(url, &status);
    free(url);
    struct card_result card;
    if (client) status = card_client_request(client, &card);
    card_client_free(client);
    char output[128];
    if (status != CARD_OK) {
        snprintf(output, sizeof(output), "card-status:%u", (unsigned)status);
        probe_string_dup(error, output); return false;
    }
    int length = snprintf(output, sizeof(output), "card:%u:%zu:%zu:%u",
        card.identifier, card.name_bytes, card.body_bytes, card.body_checksum);
    if (length < 0 || (size_t)length >= sizeof(output)) { probe_string_dup(error, "card-output"); return false; }
    probe_string_dup(result, output);
    return true;
}
