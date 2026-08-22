from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


class UnicodeQualityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NormalizedText:
    text: str
    flags: tuple[str, ...] = ()


_COMMON_MOJIBAKE = re.compile(
    r"(?:Ã[\x80-\xBF§©®±¼½¾]|Â[\x80-\xBF]|â(?:€|™|œ|ž|€“|€”|€™)|ðŸ|ï¿½)"
)


def _reject_disallowed_controls(text: str) -> None:
    for ch in text:
        cp = ord(ch)
        category = unicodedata.category(ch)
        if category == "Cc" and ch not in "\t\n\r":
            raise UnicodeQualityError(f"disallowed control character U+{cp:04X}")


def normalize_text(text: str) -> NormalizedText:
    if not isinstance(text, str):
        raise UnicodeQualityError("text must be a Unicode string decoded as UTF-8")
    if "\ufffd" in text:
        raise UnicodeQualityError("U+FFFD replacement character is not allowed")
    _reject_disallowed_controls(text)
    normalized = unicodedata.normalize("NFC", text)
    normalized = " ".join(normalized.split())
    flags: list[str] = []
    if _COMMON_MOJIBAKE.search(normalized):
        flags.append("suspicious_mojibake")
    return NormalizedText(normalized, tuple(flags))


def normalize_aliases(values):
    aliases: list[str] = []
    flags: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        result = normalize_text(value)
        if not result.text or result.text in seen:
            continue
        seen.add(result.text)
        aliases.append(result.text)
        flags.extend(result.flags)
    return aliases, sorted(set(flags))
