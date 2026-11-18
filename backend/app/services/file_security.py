"""Этап 11 (ТЗ) — проверка загружаемых файлов по содержимому, не только по
заявленному расширению: запрет исполняемых файлов независимо от того, как
они названы, и сверка магических байтов с заявленным расширением там, где
у формата есть надёжная сигнатура.

Полноценного антивируса (ClamAV и т.п.) здесь нет — это отдельный процесс/
контейнер (ещё один сервис в docker-compose.yml), не то, что можно добавить
одним файлом сервиса; это известное ограничение, не упущение."""
from __future__ import annotations

# Скомпилированные бинарники — ни один разрешённый формат (картинки, видео,
# документы, аудио, код проекта) не должен начинаться с этих сигнатур,
# независимо от расширения, которое прислал клиент.
_COMPILED_BINARY_SIGNATURES: tuple[bytes, ...] = (
    b"MZ",  # Windows PE (.exe/.dll)
    b"\x7fELF",  # Linux ELF
    b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",  # Mach-O 32/64, big-endian
    b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",  # Mach-O 32/64, little-endian
    b"\xca\xfe\xba\xbe",  # Mach-O fat binary / Java .class
)


def is_compiled_binary(data: bytes) -> bool:
    return any(data.startswith(sig) for sig in _COMPILED_BINARY_SIGNATURES)


def has_shebang(data: bytes) -> bool:
    """#!-скрипт (bash/python/perl/...) — подозрителен только там, где
    расширение НЕ предполагает исполняемый скрипт (картинки, видео,
    документы, фото к ОГЭ). В файлах проекта (.sh/.py/...) шебанг —
    абсолютно обычная первая строка, туда эта проверка не подключается."""
    return data.lstrip(b" \t\r\n").startswith(b"#!")


# Сигнатура магических байт по расширению — только форматы, где она надёжна.
# Текстовые/исходный код (py/js/txt/md/csv/...) сюда не входят: это
# произвольные байты, сверять их с "ожидаемой" сигнатурой нечем — для них
# matches_extension() ниже пропускает проверку (возвращает True).
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "gif": (b"GIF87a", b"GIF89a"),
    "pdf": (b"%PDF-",),
    "mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    "zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    "docx": (b"PK\x03\x04",),
    "xlsx": (b"PK\x03\x04",),
    "pptx": (b"PK\x03\x04",),
    "ods": (b"PK\x03\x04",),
    "doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),  # общий OLE2-контейнер — тот же у .xls/.ppt
    "xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    "ppt": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    "rar": (b"Rar!\x1a\x07",),
    "7z": (b"7z\xbc\xaf\x27\x1c",),
    "webm": (b"\x1a\x45\xdf\xa3",),
}
# ISO BMFF (mp4/mov): 4 байта длины box + b"ftyp" — смещение, не префикс.
_FTYP_EXTENSIONS = {"mp4", "mov"}
# RIFF-контейнер (webp/wav) — тип контейнера на смещении 8, не префикс.
_RIFF_EXTENSIONS = {"webp": b"WEBP", "wav": b"WAVE"}


def matches_extension(data: bytes, ext: str) -> bool:
    """False — содержимое определённо НЕ похоже на заявленное расширение
    (блокировать). True — похоже, или расширение вне проверяемого реестра
    (ничего не блокируем просто потому, что не умеем проверить)."""
    ext = ext.lower()
    if ext in _FTYP_EXTENSIONS:
        return data[4:8] == b"ftyp"
    if ext in _RIFF_EXTENSIONS:
        return data[:4] == b"RIFF" and data[8:12] == _RIFF_EXTENSIONS[ext]
    signatures = _SIGNATURES.get(ext)
    if not signatures:
        return True
    return any(data.startswith(sig) for sig in signatures)
