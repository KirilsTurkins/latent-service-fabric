/* SPDX-License-Identifier: Apache-2.0 */
#include "lsf/guest.h"

bool exports_examples_shipping_api_price(exports_examples_shipping_api_parcel_t *input,
    exports_examples_shipping_api_quote_t *out, exports_examples_shipping_api_error_t *error) {
    bool supported = input->destination.len == 2 &&
        (memcmp(input->destination.ptr, "DE", 2) == 0 || memcmp(input->destination.ptr, "LV", 2) == 0);
    probe_string_free(&input->destination);
    if (!input->grams) {
        error->tag = EXPORTS_EXAMPLES_SHIPPING_API_ERROR_INVALID_WEIGHT;
        return false;
    }
    if (!supported) {
        error->tag = EXPORTS_EXAMPLES_SHIPPING_API_ERROR_UNSUPPORTED_DESTINATION;
        return false;
    }
    uint64_t base = input->express ? 1500 : 500;
    if (input->grams > (UINT64_MAX - base) / 2) {
        error->tag = EXPORTS_EXAMPLES_SHIPPING_API_ERROR_OVERFLOW;
        return false;
    }
    lsf_scope_t scope;
    lsf_scope_init(&scope, 3);
    lsf_require(lsf_string_copy(&scope, &out->currency, (const uint8_t *)"EUR", 3));
    out->total_cents = base + input->grams * 2;
    out->eta_days = input->express ? 1 : 5;
    lsf_string_return(&scope, &out->currency);
    lsf_scope_close(&scope);
    return true;
}
