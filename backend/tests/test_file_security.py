"""Этап 11 (ТЗ): проверка MIME по содержимому и запрет исполняемых файлов."""
from app.services.file_security import has_shebang, is_compiled_binary, matches_extension


def test_detects_windows_pe():
    assert is_compiled_binary(b"MZ\x90\x00\x03")


def test_detects_elf():
    assert is_compiled_binary(b"\x7fELF\x02\x01\x01")


def test_detects_mach_o():
    assert is_compiled_binary(b"\xfe\xed\xfa\xce\x00\x00")
    assert is_compiled_binary(b"\xcf\xfa\xed\xfe\x00\x00")


def test_does_not_flag_ordinary_text():
    assert not is_compiled_binary(b"hello world")


def test_detects_shebang_with_leading_whitespace():
    assert has_shebang(b"\n#!/usr/bin/env python3\nprint(1)")


def test_no_shebang_in_ordinary_content():
    assert not has_shebang(b"print(1)")


def test_png_matches_real_signature_only():
    assert matches_extension(b"\x89PNG\r\n\x1a\n" + b"...", "png")
    assert not matches_extension(b"not a png", "png")


def test_jpg_matches_real_signature_only():
    assert matches_extension(b"\xff\xd8\xff\xe0" + b"...", "jpg")
    assert not matches_extension(b"not a jpg", "jpg")


def test_pdf_matches_real_signature_only():
    assert matches_extension(b"%PDF-1.7\n...", "pdf")
    assert not matches_extension(b"not a pdf", "pdf")


def test_zip_family_shares_pk_signature():
    zip_bytes = b"PK\x03\x04" + b"..."
    assert matches_extension(zip_bytes, "zip")
    assert matches_extension(zip_bytes, "docx")
    assert matches_extension(zip_bytes, "xlsx")


def test_mp4_checks_ftyp_box_offset():
    # 4 байта длины box + "ftyp" — не префикс, а смещение 4.
    assert matches_extension(b"\x00\x00\x00\x18ftypisom" + b"...", "mp4")
    assert not matches_extension(b"not an mp4 at all!!", "mp4")


def test_webp_and_wav_check_riff_container_type():
    assert matches_extension(b"RIFF\x00\x00\x00\x00WEBPVP8 ", "webp")
    assert matches_extension(b"RIFF\x00\x00\x00\x00WAVEfmt ", "wav")
    assert not matches_extension(b"RIFF\x00\x00\x00\x00WAVEfmt ", "webp")


def test_unknown_or_text_extensions_are_not_verified():
    # py/js/txt/md/csv и т.п. — произвольные байты, формата без сигнатуры
    # не блокируем просто потому, что не умеем проверить его содержимое.
    assert matches_extension(b"print('hello')", "py")
    assert matches_extension(b"", "txt")
