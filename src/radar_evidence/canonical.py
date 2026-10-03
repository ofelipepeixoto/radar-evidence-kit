# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Versioned local JSON encoding; deliberately not an RFC 8785 claim."""
import json

MAX_BYTES = 65536


def canonical_bytes(value: object) -> bytes:
    def validate(item, depth=0):
        if depth > 8:
            raise ValueError("record too deep")
        if type(item) in (str, int, bool) or item is None:
            if type(item) is int and not -(2**63) <= item < 2**63:
                raise ValueError("integer out of range")
            return
        if type(item) is list:
            if len(item) > 10000:
                raise ValueError("list too long")
            for child in item:
                validate(child, depth + 1)
            return
        if type(item) is dict:
            if len(item) > 10000 or any(type(key) is not str for key in item):
                raise ValueError("invalid object keys")
            for child in item.values():
                validate(child, depth + 1)
            return
        raise TypeError("only plain JSON values without floats are accepted")

    validate(value)
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise ValueError("record exceeds 64 KiB")
    return encoded
