/* Compile the maintained backend itself for wasm32 with the existing fake
 * binding declarations. This tests metadata conversion, not a signed guest. */
#include "sdk/c-guest/src/libfetch/http.c"

_Static_assert(sizeof(size_t) == 4, "this control requires wasm32 size_t");
_Static_assert(sizeof(off_t) == 8, "this control requires a 64-bit off_t");

static bool check(const char *text, size_t count, bool head, bool expected,
                  size_t expected_length, off_t expected_size) {
    static uint8_t name[] = "Content-Length";
    latent_http_streaming_header_t header = {{name, sizeof(name) - 1}, {(uint8_t *)text, count}};
    latent_http_streaming_list_header_t headers = {&header, 1};
    size_t length = 0;
    off_t representation_size = 0;
    bool known = false;
    bool ok = content_length(&headers, head, &length, &representation_size, &known);
    return expected ? ok && known && length == expected_length && representation_size == expected_size : !ok;
}
#define CHECK(expr) do { if (!(expr)) return __LINE__; } while (0)
#define VALUE(text, head, expected, length, size) \
    check(text, sizeof(text) - 1, head, expected, length, size)

__attribute__((export_name("control"))) int control(void) {
    latent_http_streaming_list_header_t missing = {NULL, 0};
    size_t length = 0;
    off_t representation_size = 0;
    bool known = true;
    CHECK(content_length(&missing, true, &length, &representation_size, &known));
    CHECK(!known && length == SIZE_MAX && representation_size == (off_t)-1);
    CHECK(VALUE("0", true, true, 0, 0));
    CHECK(VALUE("4294967295", true, true, UINT32_MAX, INT64_C(4294967295)));
    CHECK(VALUE("4294967295", false, true, UINT32_MAX, INT64_C(4294967295)));
    CHECK(VALUE("4294967296", true, true, SIZE_MAX, INT64_C(4294967296)));
    CHECK(VALUE("5000000000", true, true, SIZE_MAX, INT64_C(5000000000)));
    CHECK(VALUE("9223372036854775807", true, true, SIZE_MAX, INT64_MAX));
    CHECK(VALUE("4294967296", false, false, 0, 0));
    CHECK(VALUE("9223372036854775808", true, false, 0, 0));
    CHECK(VALUE("18446744073709551615", true, false, 0, 0));
    CHECK(VALUE("12x", true, false, 0, 0));
    CHECK(VALUE("-1", true, false, 0, 0));
    CHECK(VALUE("", true, false, 0, 0));
    static uint8_t name[] = "content-length";
    static uint8_t value[] = "5";
    latent_http_streaming_header_t repeated[2] = {
        {{name, sizeof(name) - 1}, {value, sizeof(value) - 1}},
        {{name, sizeof(name) - 1}, {value, sizeof(value) - 1}}
    };
    latent_http_streaming_list_header_t duplicates = {repeated, 2};
    CHECK(!content_length(&duplicates, true, &length, &representation_size, &known));
    return 0;
}
