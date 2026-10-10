#include "internal.h"

#include <string.h>

/* Validate the selected Phase 4 wire before nanopb allocates native values.
 * The existing stateless codec remains the owner of protobuf conversion. */
static bool varint(const uint8_t **data, size_t *length, uint64_t *value) {
    *value = 0;
    for (unsigned index = 0; index < 10; ++index) {
        if (*length == 0) return false;
        uint8_t next = **data; ++*data; --*length;
        if (index == 9 && next > 1) return false;
        *value |= (uint64_t)(next & 127u) << (7u * index);
        if ((next & 128u) == 0) return true;
    }
    return false;
}

static latent_string map_key(const uint8_t *data, size_t length) {
    latent_string result = {NULL, 0};
    while (length != 0) {
        uint64_t tag, size;
        if (!varint(&data, &length, &tag)) return result;
        if ((tag & 7u) == 2) {
            if (!varint(&data, &length, &size) || size > length) return result;
            if ((tag >> 3) == 1) result = (latent_string){(const char *)data, (size_t)size};
            data += size; length -= size;
        } else if ((tag & 7u) == 0) {
            if (!varint(&data, &length, &size)) return result;
        } else return result;
    }
    return result;
}

static bool validate(const lsf_message *message, const uint8_t *data, size_t length,
        uint64_t deadline, size_t *nodes, unsigned depth, bool *limit) {
    if (depth > LSF_MAX_DEPTH || message->field_count > 64 || *nodes == 0) {
        *limit = true; return false;
    }
    --*nodes;
    bool seen[64] = {false};
    size_t counts[64] = {0};
    latent_string keys[4][32] = {{{NULL, 0}}};
    int map_indices[64];
    unsigned maps = 0;
    for (size_t index = 0; index < message->field_count; ++index) {
        map_indices[index] = -1;
        if (message->fields[index].map) {
            if (maps == 4) return false;
            map_indices[index] = (int)maps++;
        }
    }
    while (length != 0) {
        if (*nodes == 0 || lsf_now() >= deadline) { *limit = true; return false; }
        --*nodes;
        uint64_t tag, value;
        if (!varint(&data, &length, &tag) || (tag >> 3) == 0 || (tag >> 3) > 536870911) return false;
        unsigned kind = tag & 7u;
        const uint8_t *content = NULL;
        size_t size = 0;
        if (kind == 0) {
            if (!varint(&data, &length, &value)) return false;
        } else if (kind == 2) {
            if (!varint(&data, &length, &value) || value > length) return false;
            content = data; size = (size_t)value;
            data += size; length -= size;
        } else if (kind == 1 || kind == 5) {
            size = kind == 1 ? 8 : 4;
            if (size > length) return false;
            data += size; length -= size; value = 0;
        } else return false;
        size_t index = 0;
        while (index < message->field_count && message->fields[index].tag != tag >> 3) ++index;
        if (index == message->field_count) continue;
        const lsf_field *field = &message->fields[index];
        bool repeated = field->count != LSF_NO_OFFSET;
        if (!repeated && seen[index]) return false;
        if (field->oneof != 0) {
            for (size_t previous = 0; previous < message->field_count; ++previous)
                if (seen[previous] && message->fields[previous].oneof == field->oneof) return false;
        }
        seen[index] = true;
        if (repeated) {
            size_t maximum = field->map ? 32 : strcmp(field->name, "required_record_ids") == 0 ? 256 : 128;
            if (++counts[index] > maximum) { *limit = true; return false; }
        }
        bool bytes = field->kind == LSF_STRING || field->kind == LSF_BYTES || field->kind == LSF_MESSAGE;
        if (kind != (bytes ? 2u : 0u)) return false;
        if (field->kind == LSF_STRING && !lsf_utf8(content, size)) return false;
        if (field->kind == LSF_U32 && value > UINT32_MAX) return false;
        if (field->kind == LSF_BOOL && value > 1) return false;
        if (field->kind == LSF_I32 && value > INT32_MAX && value < UINT64_MAX - INT32_MAX) return false;
        if (field->kind == LSF_MESSAGE) {
            if (!validate(field->message, content, size, deadline, nodes, depth + 1, limit)) return false;
            if (field->map) {
                latent_string key = map_key(content, size);
                size_t count = counts[index] - 1;
                for (size_t previous = 0; previous < count; ++previous)
                    if (lsf_text_equal(keys[map_indices[index]][previous], key)) return false;
                keys[map_indices[index]][count] = key;
            }
        }
    }
    return true;
}

bool lsf_transaction_wire(const lsf_message *message, const uint8_t *data, size_t length,
        uint64_t deadline, bool *limit) {
    size_t nodes = LSF_MAX_ELEMENTS;
    *limit = false;
    return validate(message, data, length, deadline, &nodes, 0, limit);
}
