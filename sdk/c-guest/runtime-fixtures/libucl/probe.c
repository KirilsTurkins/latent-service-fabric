/* SPDX-License-Identifier: Apache-2.0 */
/* Unchanged libucl owns include loading, HTTP reading and domain parsing. */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <ucl.h>
#include "probe.h"

static int equal_string(const ucl_object_t *value, const char *expected, size_t size) {
    const char *text = NULL;
    size_t length = 0;
    return value && ucl_object_type(value) == UCL_STRING &&
        ucl_object_tolstring_safe(value, &text, &length) && length == size &&
        (size == 0 || memcmp(text, expected, size) == 0);
}

static int domain(const ucl_object_t *object) {
    if (!object || ucl_object_type(object) != UCL_OBJECT || object->len != 4) return 0;
    const ucl_object_t *id = ucl_object_lookup(object, "id");
    const ucl_object_t *items = ucl_object_lookup(object, "items");
    int64_t number = 0;
    return id && items && ucl_object_type(id) == UCL_INT && ucl_object_toint_safe(id, &number) && number == 7 &&
        equal_string(ucl_object_lookup(object, "name"), "caf\xc3\xa9", 5) &&
        ucl_object_type(items) == UCL_ARRAY && ucl_array_size(items) == 2 &&
        equal_string(ucl_array_find_index(items, 0), "first", 5) &&
        equal_string(ucl_array_find_index(items, 1), "\xce\xbb", 2) &&
        equal_string(ucl_object_lookup(object, "empty"), "", 0);
}

bool exports_examples_libfetch_api_run(probe_string_t *input, probe_string_t *result,
                                    probe_string_t *error) {
    if (!input->len || input->len > 4096 || memchr(input->ptr, 0, input->len)) {
        probe_string_free(input); probe_string_dup(error, "invalid-input"); return false;
    }
    char *copy = malloc(input->len + 1);
    if (!copy) { probe_string_free(input); probe_string_dup(error, "input-memory"); return false; }
    memcpy(copy, input->ptr, input->len); copy[input->len] = 0; probe_string_free(input);
    char *url = strchr(copy, '\n');
    if (!url) { free(copy); probe_string_dup(error, "invalid-input"); return false; }
    *url++ = 0;
    const int local_file = strcmp(copy, "file") == 0;
    const int local_glob = strcmp(copy, "glob") == 0;
    if (!local_file && !local_glob && strcmp(copy, "normal") &&
        strcmp(copy, "not-found") && strcmp(copy, "denied")) {
        free(copy); probe_string_dup(error, "invalid-input"); return false;
    }
    /* Bound the ordinary include string without permitting UCL source injection. */
    for (const unsigned char *at = (const unsigned char *)url; *at; ++at) {
        if (*at < 32 || *at == '"' || *at == '\\' || *at == '$') {
            free(copy); probe_string_dup(error, "invalid-input"); return false;
        }
    }
    static const char prefix[] = ".include(url=true) \"";
    static const char suffix[] = "\";\n";
    const size_t length = strlen(url);
    char *source = malloc(sizeof(prefix) - 1 + length + sizeof(suffix));
    if (!source) { free(copy); probe_string_dup(error, "input-memory"); return false; }
    memcpy(source, prefix, sizeof(prefix) - 1);
    memcpy(source + sizeof(prefix) - 1, url, length);
    memcpy(source + sizeof(prefix) - 1 + length, suffix, sizeof(suffix));
    free(copy);
    const char *selected = local_file ? ".include \"/not-available.ucl\";\n" :
        local_glob ? ".include(glob=true) \"/not-available-*.ucl\";\n" : source;
    struct ucl_parser *parser = ucl_parser_new(UCL_PARSER_NO_FILEVARS);
    if (!parser) { free(source); probe_string_dup(error, "parser-memory"); return false; }
    const bool parsed = ucl_parser_add_chunk(parser, (const unsigned char *)selected, strlen(selected));
    ucl_object_t *object = parsed ? ucl_parser_get_object(parser) : NULL;
    const int valid = parsed && domain(object);
    ucl_object_unref(object);
    ucl_parser_free(parser);
    free(source);
    /* Upstream's successful URL loader does not fclose its FILE. Do not invent
     * a pointer or retirement ACK; original Store abandonment remains charged. */
    if (!parsed) { probe_string_dup(error, "include-rejected"); return false; }
    if (!valid || local_file || local_glob) {
        probe_string_dup(error, "domain-mismatch"); return false;
    }
    probe_string_dup(result, "ucl:7:caf\xc3\xa9:first:\xce\xbb:0");
    return true;
}
