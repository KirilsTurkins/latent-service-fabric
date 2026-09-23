/* SPDX-License-Identifier: Apache-2.0 */
#include "lsf/guest.h"

/* Decimal formatting without locale, stdio or a narrowed integer. */
static probe_string_t event_key(uint64_t value, uint8_t storage[31]) {
    static const uint8_t prefix[] = "guest-sdk-";
    uint8_t reverse[20];
    size_t count = 0;
    do { reverse[count++] = (uint8_t)('0' + value % 10); value /= 10; } while (value);
    memcpy(storage, prefix, sizeof(prefix) - 1);
    for (size_t i = 0; i < count; ++i)
        storage[sizeof(prefix) - 1 + i] = reverse[count - 1 - i];
    return (probe_string_t){storage, sizeof(prefix) - 1 + count};
}

uint64_t exports_tests_nats_events_api_run(uint32_t which, probe_string_t *text,
                                          uint64_t handle) {
    (void)which;
    uint8_t key[31];
    latent_events_publisher_event_t event = {
        .topic = *text, .payload = {(uint8_t *)"payload", 7},
        .media_type = LSF_LITERAL("text/plain"),
        .idempotency_key = event_key(handle, key),
    };
    latent_events_publisher_publish_receipt_t receipt = {0};
    latent_events_publisher_event_error_t error = {0};
    bool ok = latent_events_publisher_publish(&event, &receipt, &error);
    probe_string_free(text);
    if (ok) {
        lsf_require(receipt.event_id.len && receipt.stream_name.len);
        uint64_t sequence = receipt.sequence;
        latent_events_publisher_publish_receipt_free(&receipt);
        return sequence;
    }
    if (error.tag == LATENT_EVENTS_PUBLISHER_EVENT_ERROR_PERMISSION_DENIED) return 10;
    if (error.tag == LATENT_EVENTS_PUBLISHER_EVENT_ERROR_UNCERTAIN) return 11;
    __builtin_trap(); /* No implicit retry, including uncertain publication. */
}
