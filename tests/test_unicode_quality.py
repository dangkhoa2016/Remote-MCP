import importlib
import unicodedata

import pytest


def _quality():
    return importlib.import_module('app.unicode_quality')


def test_decomposed_vietnamese_is_normalized_to_nfc():
    q = _quality()
    raw = 'Vie\u0323t Nam'
    result = q.normalize_text(raw)
    assert result.text == unicodedata.normalize('NFC', raw)
    assert unicodedata.is_normalized('NFC', result.text)


def test_replacement_character_is_rejected():
    q = _quality()
    with pytest.raises(q.UnicodeQualityError, match='U\\+FFFD'):
        q.normalize_text('Vi\ufffd?t Nam')


def test_disallowed_control_character_is_rejected():
    q = _quality()
    with pytest.raises(q.UnicodeQualityError, match='control'):
        q.normalize_text('hello\x00world')


def test_whitespace_is_collapsed_but_legitimate_unicode_is_preserved():
    q = _quality()
    result = q.normalize_text('  Ð  Ã\nÂ   Việt Nam  ')
    assert result.text == 'Ð Ã Â Việt Nam'


def test_suspicious_mojibake_is_flagged_not_rewritten():
    q = _quality()
    raw = 'FranÃ§ois'
    result = q.normalize_text(raw)
    assert result.text == raw
    assert 'suspicious_mojibake' in result.flags



def test_nfd_and_nfc_vietnamese_normalize_to_identical_text():
    q = _quality()
    nfc = 'Cộng hòa Xã hội chủ nghĩa Việt Nam'
    nfd = unicodedata.normalize('NFD', nfc)
    assert nfd != nfc
    assert q.normalize_text(nfd).text == q.normalize_text(nfc).text == nfc


def test_emoji_cjk_and_mixed_scripts_are_preserved():
    q = _quality()
    raw = 'Việt Nam 🇻🇳 東京 AI研究 — مرحبا'
    result = q.normalize_text(raw)
    assert result.text == raw
    assert '🇻🇳' in result.text
    assert '東京' in result.text
    assert 'مرحبا' in result.text
