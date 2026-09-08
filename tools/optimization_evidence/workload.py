"""Small independent reference for the fixed, retained pure-function inputs."""

import json

from .common import fields, integer, require, text

MEDIA = "application/vnd.latent.wit-values.v1+json"
MASK = 2**32 - 1


def rotate(value, count):
    return ((value << count) | (value >> (32 - count))) & MASK


def framed(value):
    # Rust's struct output preserves WIT declaration order (label,bytes,values).
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def expected(function, payload):
    require(isinstance(payload, list), "invalid-workload-frame")
    if function == "echo":
        require(len(payload) == 1, "invalid-echo-frame")
        text(payload[0], 1024 * 1024, empty=True)
        return framed(payload)
    if function == "compute":
        require(len(payload) == 2, "invalid-compute-frame")
        value = integer(payload[0], 0, MASK)
        rounds = integer(payload[1], 0, 1_000_000)
        for turn in range(rounds):
            value = rotate((value + (turn ^ 0x9E3779B9)) & MASK, 5)
            value = (value * 1_664_525 + 1_013_904_223) & MASK
            value ^= rotate(value, 19)
        return framed([value])
    require(function == "transform" and len(payload) == 1, "invalid-transform-frame")
    value = fields(payload[0], "label bytes values")
    text(value["label"], 1024 * 1024, empty=True)
    require(all(isinstance(value[key], list) and len(value[key]) <= 4096
                for key in ("bytes", "values")), "invalid-transform-size")
    data = [integer(item, 0, 255) for item in value["bytes"]]
    values = [rotate((integer(item, 0, MASK) * 3 + index) & MASK, 7)
              for index, item in enumerate(value["values"])]
    return framed([{"label": value["label"], "bytes": data[::-1], "values": values}])
