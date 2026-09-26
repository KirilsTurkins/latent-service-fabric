#include "wire.h"

#include <stdalign.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

struct lsf_arena_block {
    lsf_arena_block *next;
    max_align_t alignment;
};

uint64_t lsf_now(void) {
    struct timespec instant;
    if (clock_gettime(CLOCK_MONOTONIC, &instant) != 0) abort();
    return (uint64_t)instant.tv_sec * UINT64_C(1000) + (uint64_t)instant.tv_nsec / UINT64_C(1000000);
}

bool lsf_text_equal(latent_string left, latent_string right) {
    return left.length == right.length && (left.length == 0 ||
           (left.data != NULL && right.data != NULL && memcmp(left.data, right.data, left.length) == 0));
}

bool lsf_utf8(const uint8_t *data, size_t length) {
    if (length != 0 && data == NULL) return false;
    for (size_t index = 0; index < length;) {
        uint32_t value = data[index++];
        if (value < 0x80) continue;
        unsigned trailing;
        uint32_t minimum;
        if (value >= 0xc2 && value <= 0xdf) { trailing = 1; minimum = 0x80; value &= 0x1f; }
        else if (value >= 0xe0 && value <= 0xef) { trailing = 2; minimum = 0x800; value &= 0x0f; }
        else if (value >= 0xf0 && value <= 0xf4) { trailing = 3; minimum = 0x10000; value &= 0x07; }
        else return false;
        if (trailing > length - index) return false;
        for (unsigned position = 0; position < trailing; ++position) {
            uint8_t next = data[index++];
            if ((next & 0xc0) != 0x80) return false;
            value = (value << 6) | (next & 0x3f);
        }
        if (value < minimum || value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff)) return false;
    }
    return true;
}

void *lsf_arena_allocate(lsf_arena *arena, size_t size) {
    if (size == 0) size = 1;
    if (size > SIZE_MAX - sizeof(lsf_arena_block)) return NULL;
    size_t total = size + sizeof(lsf_arena_block);
    if (total > arena->maximum - arena->used) return NULL;
    lsf_arena_block *block = lsf_allocate(arena->owner, total);
    if (block == NULL) return NULL;
    block->next = arena->blocks;
    arena->blocks = block;
    arena->used += total;
    memset(block + 1, 0, size);
    return block + 1;
}

void lsf_arena_clear(lsf_arena *arena) {
    while (arena->blocks != NULL) {
        lsf_arena_block *block = arena->blocks;
        arena->blocks = block->next;
        lsf_deallocate(arena->owner, block);
    }
    arena->used = 0;
}

static bool message_io(const lsf_message *message, void *value, lsf_codec *codec,
                       pb_istream_t *input, pb_ostream_t *output);

static bool visit(lsf_codec *codec) {
    if (++codec->elements > LSF_MAX_ELEMENTS || lsf_now() >= codec->deadline) {
        codec->limit = true;
        return false;
    }
    return true;
}

static bool write_value(pb_ostream_t *output, const pb_field_iter_t *field,
                        lsf_pb_slot *slot, const void *value) {
    const lsf_field *definition = slot->definition;
    if (!visit(slot->codec)) return false;
    if (!pb_encode_tag_for_field(output, field)) return false;
    switch (definition->kind) {
        case LSF_STRING: {
            const latent_string *text = value;
            if (text->length > slot->codec->maximum) { slot->codec->limit = true; return false; }
            return lsf_utf8((const uint8_t *)text->data, text->length)
                && pb_encode_string(output, (const uint8_t *)text->data, text->length);
        }
        case LSF_BYTES: {
            const latent_bytes *bytes = value;
            if (bytes->length > slot->codec->maximum) { slot->codec->limit = true; return false; }
            return (bytes->length == 0 || bytes->data != NULL)
                && pb_encode_string(output, bytes->data, bytes->length);
        }
        case LSF_U64: return pb_encode_varint(output, *(const uint64_t *)value);
        case LSF_U32: return pb_encode_varint(output, *(const uint32_t *)value);
        case LSF_I32: return pb_encode_varint(output, (uint64_t)(int64_t)*(const int32_t *)value);
        case LSF_BOOL: return pb_encode_varint(output, *(const bool *)value ? 1 : 0);
        case LSF_MESSAGE: {
            pb_ostream_t sizing = PB_OSTREAM_SIZING;
            if (!message_io(definition->message, (void *)value, slot->codec, NULL, &sizing)
                || !pb_encode_varint(output, sizing.bytes_written)) return false;
            return message_io(definition->message, (void *)value, slot->codec, NULL, output);
        }
    }
    return false;
}

static bool empty_value(const lsf_field *field, const void *value) {
    switch (field->kind) {
        case LSF_STRING: return ((const latent_string *)value)->length == 0;
        case LSF_BYTES: return ((const latent_bytes *)value)->length == 0;
        case LSF_U64: return *(const uint64_t *)value == 0;
        case LSF_U32: return *(const uint32_t *)value == 0;
        case LSF_I32: return *(const int32_t *)value == 0;
        case LSF_BOOL: return !*(const bool *)value;
        case LSF_MESSAGE: return false;
    }
    return false;
}

static bool encode_field(pb_ostream_t *output, const pb_field_iter_t *field, lsf_pb_slot *slot) {
    const lsf_field *definition = slot->definition;
    const uint8_t *object = slot->object;
    if (definition->presence != LSF_NO_OFFSET && !*(const bool *)(object + definition->presence)) return true;
    if (definition->count == LSF_NO_OFFSET) {
        const void *value = object + definition->offset;
        if (definition->presence == LSF_NO_OFFSET && empty_value(definition, value)) return true;
        return write_value(output, field, slot, value);
    }
    size_t count = *(const size_t *)(object + definition->count);
    const uint8_t *array;
    memcpy(&array, object + definition->offset, sizeof(array));
    if (count > LSF_MAX_ELEMENTS) { slot->codec->limit = true; return false; }
    if (count != 0 && array == NULL) return false;
    for (size_t index = 0; index < count; ++index) {
        const void *value = array + index * definition->stride;
        if (definition->map) {
            const latent_string *key = value;
            for (size_t previous = 0; previous < index; ++previous) {
                const latent_string *other = (const void *)(array + previous * definition->stride);
                if (lsf_text_equal(*key, *other)) return false;
            }
        }
        if (!write_value(output, field, slot, value)) return false;
    }
    return true;
}

static void *next_value(lsf_pb_slot *slot) {
    const lsf_field *field = slot->definition;
    uint8_t *object = slot->object;
    if (field->presence != LSF_NO_OFFSET) *(bool *)(object + field->presence) = true;
    if (field->count == LSF_NO_OFFSET) return object + field->offset;
    size_t *count = (void *)(object + field->count);
    uint8_t *array;
    memcpy(&array, object + field->offset, sizeof(array));
    if (*count >= LSF_MAX_ELEMENTS) return NULL;
    if (*count == slot->capacity) {
        size_t capacity = slot->capacity == 0 ? 4 : slot->capacity * 2;
        if (capacity > LSF_MAX_ELEMENTS || field->stride > SIZE_MAX / capacity) return NULL;
        uint8_t *replacement = lsf_arena_allocate(slot->codec->arena, capacity * field->stride);
        if (replacement == NULL) return NULL;
        if (*count != 0) memcpy(replacement, array, *count * field->stride);
        memcpy(object + field->offset, &replacement, sizeof(replacement));
        slot->capacity = capacity;
        array = replacement;
    }
    return array + (*count)++ * field->stride;
}

static bool decode_field(pb_istream_t *input, lsf_pb_slot *slot) {
    if (!visit(slot->codec)) return false;
    const lsf_field *field = slot->definition;
    void *value = next_value(slot);
    if (value == NULL) { slot->codec->limit = true; return false; }
    uint64_t number;
    switch (field->kind) {
        case LSF_STRING:
        case LSF_BYTES: {
            size_t length = input->bytes_left;
            if (length > slot->codec->maximum || length == SIZE_MAX) { slot->codec->limit = true; return false; }
            uint8_t *bytes = lsf_arena_allocate(slot->codec->arena, length + 1);
            if (bytes == NULL) { slot->codec->limit = true; return false; }
            if (!pb_read(input, bytes, length)) return false;
            if (field->kind == LSF_STRING) {
                if (!lsf_utf8(bytes, length)) return false;
                *(latent_string *)value = (latent_string){(const char *)bytes, length};
            } else *(latent_bytes *)value = (latent_bytes){bytes, length};
            return true;
        }
        case LSF_MESSAGE:
            if (!message_io(field->message, value, slot->codec, input, NULL)) return false;
            if (field->map) {
                uint8_t *object = slot->object;
                uint8_t *array;
                memcpy(&array, object + field->offset, sizeof(array));
                size_t *count = (void *)(object + field->count);
                for (size_t index = 0; index + 1 < *count; ++index) {
                    void *previous = array + index * field->stride;
                    if (lsf_text_equal(*(latent_string *)previous, *(latent_string *)value)) {
                        memcpy(previous, value, field->stride);
                        --*count;
                        break;
                    }
                }
            }
            return true;
        case LSF_U64:
            return pb_decode_varint(input, value);
        case LSF_U32:
            if (!pb_decode_varint(input, &number) || number > UINT32_MAX) return false;
            *(uint32_t *)value = (uint32_t)number;
            return true;
        case LSF_I32: {
            if (!pb_decode_varint(input, &number)
                || (number > UINT32_MAX && number < UINT64_MAX - INT32_MAX)) return false;
            uint32_t bits = (uint32_t)number;
            memcpy(value, &bits, sizeof(bits));
            return true;
        }
        case LSF_BOOL:
            if (!pb_decode_varint(input, &number) || number > 1) return false;
            *(bool *)value = number != 0;
            return true;
    }
    return false;
}

bool lsf_wire_callback(pb_istream_t *input, pb_ostream_t *output, const pb_field_iter_t *field) {
    lsf_pb_slot *slot = field->pData;
    return input != NULL ? decode_field(input, slot) : encode_field(output, field, slot);
}

static bool oneofs_valid(const lsf_message *message, const void *value) {
    const uint8_t *object = value;
    for (size_t index = 0; index < message->field_count; ++index) {
        const lsf_field *field = &message->fields[index];
        if (field->oneof == 0 || !*(const bool *)(object + field->presence)) continue;
        for (size_t previous = 0; previous < index; ++previous) {
            const lsf_field *other = &message->fields[previous];
            if (other->oneof == field->oneof && *(const bool *)(object + other->presence)) return false;
        }
    }
    return true;
}

static bool message_io(const lsf_message *message, void *value, lsf_codec *codec,
                       pb_istream_t *input, pb_ostream_t *output) {
    if (++codec->depth > LSF_MAX_DEPTH) { codec->limit = true; --codec->depth; return false; }
    if (!visit(codec) || !oneofs_valid(message, value)) {
        --codec->depth;
        return false;
    }
    union { max_align_t alignment; uint8_t bytes[LSF_WIRE_STORAGE]; } storage;
    memset(&storage, 0, sizeof(storage));
    pb_field_iter_t iterator;
    bool found = pb_field_iter_begin(&iterator, message->wire, storage.bytes);
    while (found) {
        const lsf_field *definition = NULL;
        for (size_t index = 0; index < message->field_count; ++index) {
            if (message->fields[index].tag == iterator.tag) { definition = &message->fields[index]; break; }
        }
        if (definition == NULL || iterator.data_size != sizeof(lsf_pb_slot)) { --codec->depth; return false; }
        *(lsf_pb_slot *)iterator.pData = (lsf_pb_slot){.codec = codec, .definition = definition, .object = value};
        found = pb_field_iter_next(&iterator);
    }
    bool success = input != NULL ? pb_decode_ex(input, message->wire, storage.bytes, PB_DECODE_NOINIT)
                                 : pb_encode(output, message->wire, storage.bytes);
    --codec->depth;
    return success && oneofs_valid(message, value);
}

typedef struct lsf_output {
    lsf_codec *codec;
    uint8_t *buffer;
    size_t capacity;
} lsf_output;

static bool bounded_write(pb_ostream_t *stream, const pb_byte_t *buffer, size_t count) {
    lsf_output *output = stream->state;
    if (count > output->capacity - stream->bytes_written) { output->codec->limit = true; return false; }
    if (count != 0) memcpy(output->buffer + stream->bytes_written, buffer, count);
    return true;
}

bool lsf_encode(const lsf_message *message, const void *value, uint8_t *output,
                size_t capacity, size_t *length, uint64_t deadline, bool *limit) {
    if (limit != NULL) *limit = false;
    if (message == NULL || value == NULL || output == NULL || length == NULL) return false;
    lsf_codec codec = {.maximum = capacity, .deadline = deadline};
    lsf_output bounded = {&codec, output, capacity};
    pb_ostream_t stream = {.callback = bounded_write, .state = &bounded, .max_size = SIZE_MAX};
    bool success = message_io(message, (void *)value, &codec, NULL, &stream);
    *length = stream.bytes_written;
    if (limit != NULL) *limit = codec.limit;
    return success;
}

bool lsf_decode(const lsf_message *message, const uint8_t *input, size_t length,
                void *value, lsf_arena *arena, uint64_t deadline, bool *limit) {
    lsf_codec codec = {.arena = arena, .maximum = arena->maximum, .deadline = deadline};
    pb_istream_t stream = pb_istream_from_buffer(input, length);
    bool success = message_io(message, value, &codec, &stream, NULL);
    *limit = codec.limit;
    return success && stream.bytes_left == 0;
}
