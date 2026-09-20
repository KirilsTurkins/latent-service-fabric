"""Local-only SVG references; the deliberately small CSS subset is in docs/svg-style.md.

This is a tokenizer, not a CSS engine or an SVG sanitizer. It never resolves a
URL, reads another file, evaluates CSS, or changes the supplied XML elements.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence, Set
from xml.etree.ElementTree import Element

CSS_WHITESPACE = " \t\r\n\f"
# SVG presentation attributes (including SVG 1.1's legacy resource properties).
# Include animation values so the previous URL checks cannot be bypassed by SMIL.
# Non-CSS metadata such as aria-label, id and data-* must not be parsed as CSS.
CSS_ATTRIBUTES = frozenset("""
    alignment-baseline baseline-shift clip clip-path clip-rule color color-interpolation
    color-interpolation-filters color-profile color-rendering cursor direction display
    dominant-baseline fill fill-opacity fill-rule filter flood-color flood-opacity
    font-family font-size font-size-adjust font-stretch font-style font-variant font-weight
    glyph-orientation-horizontal glyph-orientation-vertical image-rendering isolation
    kerning letter-spacing lighting-color marker marker-end marker-mid marker-start mask
    mask-type mix-blend-mode opacity overflow paint-order pointer-events shape-rendering
    solid-color solid-opacity stop-color stop-opacity stroke stroke-dasharray
    stroke-dashoffset stroke-linecap stroke-linejoin stroke-miterlimit stroke-opacity
    stroke-width style text-anchor text-decoration text-overflow text-rendering transform
    transform-origin unicode-bidi vector-effect visibility white-space word-spacing
    writing-mode cx cy r rx ry x y width height d patternTransform gradientTransform
    from to by values
""".split())
# These can load resources from strings rather than literal url() tokens. They
# are outside the static-diagram subset, not silently treated as inert strings.
INDIRECT_RESOURCE_FUNCTIONS = frozenset({"image", "image-set", "-webkit-image-set", "src", "attr"})


class CssReferenceError(ValueError):
    """An unsupported or malformed token, with its original character offset."""

    def __init__(self, offset: int, message: str) -> None:
        super().__init__(message)
        self.offset = offset


def _name_character(char: str) -> bool:
    return (char.isascii() and (char.isalnum() or char in "-_")) or ord(char) >= 128


def _check_character(text: str, index: int) -> None:
    char = text[index]
    if char == "\\":
        raise CssReferenceError(index, "CSS escapes are unsupported; use literal tokens")
    if (ord(char) < 32 and char not in CSS_WHITESPACE) or ord(char) == 127:
        raise CssReferenceError(index, "CSS control characters are unsupported")


def _string(text: str, index: int) -> tuple[str, int]:
    start = index
    quote = text[index]
    index += 1
    while index < len(text):
        _check_character(text, index)
        if text[index] == quote:
            return text[start + 1:index], index + 1
        if text[index] in "\r\n\f":
            raise CssReferenceError(index, "newline in CSS string")
        index += 1
    raise CssReferenceError(start, "unterminated CSS string")


def _url(text: str, index: int) -> tuple[str, int]:
    """Read after url(; comments inside a URL are explicitly unsupported.

    In particular, do NOT strip comments from unquoted URL tokens: CSS would
    treat those characters as part of the URL, not as a comment between tokens.
    """
    start = index
    while index < len(text) and text[index] in CSS_WHITESPACE:
        index += 1
    if index == len(text):
        raise CssReferenceError(start, "unterminated url()")
    if text[index] in "\"'":
        value, index = _string(text, index)
    else:
        first = index
        while index < len(text) and text[index] not in CSS_WHITESPACE + ")":
            _check_character(text, index)
            if text.startswith("/*", index):
                raise CssReferenceError(index, "comments inside url() are unsupported")
            if text[index] in "\"'(":
                raise CssReferenceError(index, "malformed unquoted url()")
            index += 1
        value = text[first:index]
    while index < len(text) and text[index] in CSS_WHITESPACE:
        index += 1
    if text.startswith("/*", index):
        raise CssReferenceError(index, "comments inside url() are unsupported")
    if index == len(text) or text[index] != ")":
        raise CssReferenceError(index, "url() must end after one literal reference")
    return value, index + 1


def css_references(text: str) -> Iterator[tuple[int, str]]:
    """Yield (offset, URL) in source order, rejecting ambiguous/unsupported syntax.

    Comments and ordinary quoted strings are inert. Literal case-insensitive
    url() and @import tokens are recognized without joining tokens across
    comments. An iterative delimiter stack avoids recursive parsing limits.
    """
    index = 0
    stack: list[tuple[str, int]] = []
    closing = {"(": ")", "[": "]", "{": "}"}
    while index < len(text):
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise CssReferenceError(index, "unterminated CSS comment")
            index = end + 2
            continue
        _check_character(text, index)
        char = text[index]
        if char in "\"'":
            _, index = _string(text, index)
            continue
        if char == "@" or _name_character(char):
            start = index
            at_rule = char == "@"
            index += 1
            while index < len(text) and _name_character(text[index]):
                index += 1
            name = text[start + int(at_rule):index].lower()
            if at_rule and name == "import":
                raise CssReferenceError(start, "external CSS import (@import) is disallowed")
            if not at_rule and name == "url":
                if index < len(text) and text[index] == "(":
                    value, index = _url(text, index + 1)
                    yield start, value
                    continue
                # Whitespace/comment-separated function names are not url()
                # tokens. Reject that ambiguous spelling instead of fixing it.
                tail = index
                while tail < len(text):
                    if text[tail] in CSS_WHITESPACE:
                        tail += 1
                    elif text.startswith("/*", tail):
                        end = text.find("*/", tail + 2)
                        if end < 0:
                            raise CssReferenceError(tail, "unterminated CSS comment")
                        tail = end + 2
                    else:
                        break
                if text.startswith("(", tail):
                    raise CssReferenceError(start, "url must be immediately followed by '('")
            if (not at_rule and name in INDIRECT_RESOURCE_FUNCTIONS
                    and index < len(text) and text[index] == "("):
                raise CssReferenceError(start, f"resource function {name}() is unsupported; use url()")
            continue
        if char in closing:
            stack.append((closing[char], index))
        elif char in ")]}":
            if not stack or stack[-1][0] != char:
                raise CssReferenceError(index, f"unmatched CSS delimiter {char!r}")
            stack.pop()
        index += 1
    if stack:
        expected, start = stack[-1]
        raise CssReferenceError(start, f"unclosed CSS delimiter; expected {expected!r}")


def _reference_error(value: str, identifiers: Set[str]) -> str | None:
    if not value:
        return "empty resource reference"
    if not value.startswith("#"):
        return "non-local reference"
    fragment = value[1:]
    if not fragment:
        return "empty resource fragment"
    # Literal IDs only: no URI decoding, CSS escapes or SVG view specifications.
    # This prevents authoring-time equality from disagreeing with URL decoding.
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127
           or char in "%\\#()" for char in fragment):
        return "unsupported resource fragment; use a literal ID without whitespace, escapes or encoding"
    if fragment not in identifiers:
        return "resource reference to missing ID"
    return None


def _css_errors(text: str, context: str, identifiers: Set[str]) -> Iterator[str]:
    try:
        for offset, value in css_references(text):
            error = _reference_error(value, identifiers)
            if error:
                yield f"SVG {error} {value!r} in {context} at CSS offset {offset}"
    except CssReferenceError as exc:
        preview = text[max(0, exc.offset - 16):exc.offset + 64]
        yield f"SVG {exc} in {context} at CSS offset {exc.offset} near {preview!r}"


def svg_reference_errors(elements: Sequence[Element], identifiers: Set[str]) -> Iterator[str]:
    """Check each source independently against the complete, document-local ID set."""
    for number, element in enumerate(elements, 1):
        if not isinstance(element.tag, str):
            continue
        name = element.tag.rsplit("}", 1)[-1]
        context = f"<{name}> element {number}"
        for attribute, value in sorted(element.attrib.items()):
            local = attribute.rsplit("}", 1)[-1]
            if attribute == "{http://www.w3.org/XML/1998/namespace}base" and value:
                yield f"SVG xml:base is unsupported {value!r} in {context}; references must stay in this document"
            if local in {"href", "src"}:
                reference = value.strip(CSS_WHITESPACE)
                error = _reference_error(reference, identifiers)
                if error:
                    yield f"SVG contains {error} in {local} {reference!r} ({context}, attribute {attribute})"
            elif local in CSS_ATTRIBUTES:
                yield from _css_errors(value, f"{context} attribute {attribute}", identifiers)
        if name == "style":
            yield from _css_errors("".join(element.itertext()), context, identifiers)
