"""Deterministic strict decoding with lossless character-to-evidence offsets."""

from dataclasses import dataclass
from typing import Literal


class TextCoverageError(ValueError):
    def __init__(
        self, code: Literal["BINARY_CONTENT", "INVALID_ENCODING", "UNSUPPORTED_NEWLINES"]
    ) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DecodedSource:
    text: str
    encoding: Literal["utf-8", "utf-8-bom", "utf-16-le-bom", "utf-16-be-bom"]
    offsets: tuple[int, ...]
    line_starts: tuple[int, ...]

    def byte_span(self, start: int, end: int) -> tuple[int, int]:
        if not 0 <= start < end <= len(self.text):
            raise ValueError("invalid decoded span")
        return self.offsets[start], self.offsets[end]

    def ast_position(self, line: int, utf8_column: int) -> int:
        """AST columns are UTF-8 bytes, even when retained evidence is UTF-16."""

        start = self.line_starts[line - 1]
        stop = self.line_starts[line] - 1 if line < len(self.line_starts) else len(self.text)
        text_line = self.text[start:stop]
        chars = text_line.encode("utf-8")[:utf8_column].decode("utf-8", errors="strict")
        return start + len(chars)


def decode_source(content: bytes) -> DecodedSource:
    label: Literal["utf-8", "utf-8-bom", "utf-16-le-bom", "utf-16-be-bom"]
    if content.startswith(b"\xff\xfe"):
        codec, bom, label = "utf-16-le", 2, "utf-16-le-bom"
    elif content.startswith(b"\xfe\xff"):
        codec, bom, label = "utf-16-be", 2, "utf-16-be-bom"
    elif content.startswith(b"\xef\xbb\xbf"):
        codec, bom, label = "utf-8", 3, "utf-8-bom"
    else:
        codec, bom, label = "utf-8", 0, "utf-8"
    # BOM-aware bounded control-byte detection precedes decoding. UTF-16 zero
    # octets are ordinary encoding bytes, not evidence of binary content.
    if bom == 0 and any(byte < 32 and byte not in (9, 10, 13) for byte in content[:4096]):
        raise TextCoverageError("BINARY_CONTENT")
    try:
        text = content[bom:].decode(codec, errors="strict")
    except UnicodeError as error:
        raise TextCoverageError("INVALID_ENCODING") from error
    if any((ord(char) < 32 and char not in "\t\n\r") or ord(char) == 127 for char in text):
        raise TextCoverageError("BINARY_CONTENT")
    if any(char == "\r" and text[index : index + 2] != "\r\n" for index, char in enumerate(text)):
        raise TextCoverageError("UNSUPPORTED_NEWLINES")
    offsets = [bom]
    for char in text:
        offsets.append(offsets[-1] + len(char.encode(codec)))
    return DecodedSource(
        text=text,
        encoding=label,
        offsets=tuple(offsets),
        line_starts=(0, *(index + 1 for index, char in enumerate(text) if char == "\n")),
    )
