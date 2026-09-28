# -*- coding: utf-8 -*-
"""
SAMDHAN AI -- Feature 01: Intelligent Fragment Reconstruction
backend/fragment_ingestor.py

Phase 1 of 4: RAW INPUT -> FRAGMENT DISCOVERY -> FRAGMENT EXTRACTION
              -> FRAGMENT FEATURE ANALYSIS -> ANALYZED FRAGMENT DATA

Responsibilities:
  - Accept raw binary files, synthetic fragmented files, or fragment directories.
  - Produce a real FragmentRecord for every fragment.
  - Never modify the source evidence (opened read-only throughout).
  - Never fabricate unavailable physical information (source_offset = UNKNOWN
    when offset cannot be determined).
  - Use existing MAGIC_TABLE and shannon_entropy from integrity_pipeline.

What this phase does NOT do (later phases):
  - Candidate graph construction
  - Edge scoring / path reconstruction
  - Byte reassembly
  - Candidate ranking
  - Frontend visualization
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Re-use existing constants from integrity_pipeline — single source of truth
# ---------------------------------------------------------------------------
# We import only pure-data constants and utility functions, NOT FastAPI objects.
# This keeps fragment_ingestor importable in tests without starting the API.

MAGIC_TABLE: List[Tuple[bytes, str, str]] = [
    (b"\xff\xd8\xff",                  "JPEG",   "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n",            "PNG",    "image/png"),
    (b"%PDF",                          "PDF",    "application/pdf"),
    (b"PK\x03\x04",                   "ZIP",    "application/zip"),
    (b"SQLite format 3\x00",          "SQLITE", "application/x-sqlite3"),
    (b"\xd0\xcf\x11\xe0",             "DOC",    "application/msword"),
    (b"\xd4\xc3\xb2\xa1",             "PCAP",   "application/vnd.tcpdump"),
    (b"\xa1\xb2\xc3\xd4",             "PCAP",   "application/vnd.tcpdump"),
    (b"ElfFile\x00",                   "EVTX",   "application/x-ms-evtx"),
    (b"regf",                          "REGF",   "application/x-windows-registry"),
    (b"MZ",                            "PE",     "application/x-msdownload"),
    (b"GIF8",                          "GIF",    "image/gif"),
    (b"BM",                            "BMP",    "image/bmp"),
    (b"\x1f\x8b",                      "GZIP",   "application/gzip"),
    (b"7z\xbc\xaf\x27\x1c",           "7ZIP",   "application/x-7z-compressed"),
    (b"Rar!\x1a\x07",                  "RAR",    "application/x-rar-compressed"),
    (b"\x00\x00\x01\xba",             "MPEG",   "video/mpeg"),
    (b"\x00\x00\x01\xb3",             "MPEG",   "video/mpeg"),
    (b"ftyp",                          "MP4",    "video/mp4"),  # at offset 4
]

# Footer (trailer) signatures indexed by format type
FOOTER_TABLE: Dict[str, List[bytes]] = {
    "JPEG":   [b"\xff\xd9"],
    "PNG":    [b"\x49\x45\x4e\x44\xae\x42\x60\x82"],  # IEND chunk CRC
    "PDF":    [b"%%EOF"],
    "ZIP":    [b"PK\x05\x06"],
    "GZIP":   [],  # variable
}

# Format-specific internal markers (for structural feature extraction)
INTERNAL_MARKERS: Dict[str, List[bytes]] = {
    "JPEG":   [b"\xff\xc0", b"\xff\xc2", b"\xff\xda", b"\xff\xdb", b"\xff\xc4"],
    "PNG":    [b"IHDR", b"IDAT", b"IEND", b"PLTE"],
    "PDF":    [b" obj", b"endobj", b"xref", b"trailer", b"startxref"],
    "ZIP":    [b"PK\x01\x02", b"PK\x05\x06"],
    "SQLITE": [b"SQLite format 3"],
    "EVTX":   [b"ElfChunk"],
}

# Sentinel for unavailable physical offset
UNKNOWN_OFFSET = -1

# How many bytes to capture as first_bytes / last_bytes
BOUNDARY_WINDOW = 32


# =============================================================================
# Data model
# =============================================================================

@dataclass
class FragmentRecord:
    """
    One real, byte-verified fragment record.

    All fields are populated from actual bytes — never fabricated.
    If a field is unavailable (e.g. source_offset for a standalone file),
    it is set to its explicit UNKNOWN sentinel, not a plausible-sounding value.
    """
    fragment_id:       str             # stable deterministic ID = "FRAG-" + sha256[:12]
    source_file:       str             # absolute path or "<bytes>" for in-memory input
    source_offset:     int             # byte offset in source; UNKNOWN_OFFSET (-1) if unavailable
    length:            int             # actual byte length of this fragment
    sha256:            str             # SHA-256 hex of fragment bytes
    md5:               str             # MD5 hex (useful for cross-referencing legacy tools)
    entropy:           float           # Shannon entropy H, bits/byte, range [0, 8]
    first_bytes:       str             # hex of first min(BOUNDARY_WINDOW, length) bytes
    last_bytes:        str             # hex of last min(BOUNDARY_WINDOW, length) bytes
    detected_type:     str             # from MAGIC_TABLE; "UNKNOWN" if no match
    detected_mime:     str             # MIME type from MAGIC_TABLE
    format_hint:       str             # "header_only", "footer_only", "header_and_footer",
                                       # "interior", "unknown"
    header_compatible: bool            # True if first bytes match a known magic header
    footer_compatible: bool            # True if last bytes contain a known footer marker
    internal_markers:  List[str]       # format marker names found in body bytes
    corruption_flags:  List[str]       # specific anomalies: "high_zero_ratio",
                                       # "entropy_anomaly", "truncated_header", etc.
    zero_byte_ratio:   float           # fraction of 0x00 bytes
    printable_ratio:   float           # fraction of bytes in printable ASCII range 0x20-0x7E
    byte_freq_summary: Dict[str, int]  # top-5 most frequent byte values {hex_byte: count}
    sector_hint:       Optional[int]   # nearest 512-byte sector boundary if source_offset known
    ingest_error:      Optional[str]   # non-None only if ingestion partially failed

    def to_dict(self) -> Dict:
        return asdict(self)


# =============================================================================
# Core computations
# =============================================================================

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def shannon_entropy(data: bytes) -> float:
    """
    Real Shannon entropy: H = -sum(p(x) * log2(p(x)))
    Returns bits/byte, range [0.0, 8.0].
    Returns 0.0 for empty input.
    """
    if not data:
        return 0.0
    freq = [0] * 256
    for b in data:
        freq[b] += 1
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in freq if c > 0)


def _zero_byte_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    return data.count(0x00) / len(data)


def _printable_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    return sum(1 for b in data if 0x20 <= b <= 0x7E) / len(data)


def _byte_freq_summary(data: bytes, top_n: int = 5) -> Dict[str, int]:
    """Top-N most frequent byte values, as {hex_string: count}."""
    if not data:
        return {}
    freq = [0] * 256
    for b in data:
        freq[b] += 1
    indexed = sorted(enumerate(freq), key=lambda x: -x[1])
    return {f"{v:02x}": cnt for v, cnt in indexed[:top_n] if cnt > 0}


def _detect_type(data: bytes) -> Tuple[str, str]:
    """
    Match data against MAGIC_TABLE using actual header bytes.
    Returns (detected_type, detected_mime).
    Filename is deliberately NOT used.

    Special case: MP4 "ftyp" atom sits at offset 4, not 0.
    """
    header = data[:32] if len(data) >= 32 else data

    # Standard header check
    for sig, dtype, mime in MAGIC_TABLE:
        if dtype == "MP4":
            continue  # handled separately below
        if header[:len(sig)] == sig:
            return dtype, mime

    # MP4: "ftyp" at bytes 4-8
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return "MP4", "video/mp4"

    return "UNKNOWN", "application/octet-stream"


def _detect_footer(data: bytes, detected_type: str) -> bool:
    """True if the last BOUNDARY_WINDOW*2 bytes contain a known footer for this type."""
    markers = FOOTER_TABLE.get(detected_type, [])
    tail = data[-(BOUNDARY_WINDOW * 2):] if len(data) >= BOUNDARY_WINDOW * 2 else data
    return any(m in tail for m in markers)


def _detect_internal_markers(data: bytes, detected_type: str) -> List[str]:
    """Return names of format-internal markers found in the body bytes."""
    found = []
    markers = INTERNAL_MARKERS.get(detected_type, [])
    for m in markers:
        if m in data:
            found.append(m.decode("latin-1", errors="replace"))
    return found


def _infer_format_hint(header_ok: bool, footer_ok: bool) -> str:
    if header_ok and footer_ok:
        return "header_and_footer"
    if header_ok:
        return "header_only"
    if footer_ok:
        return "footer_only"
    return "interior_or_unknown"


def _detect_corruption_flags(
    data: bytes,
    detected_type: str,
    entropy: float,
    zero_ratio: float,
    header_ok: bool,
) -> List[str]:
    """
    Emit specific, falsifiable corruption indicators based on actual measurements.
    Does NOT assume high entropy = valid or low entropy = invalid.
    """
    flags = []
    n = len(data)

    # High zero-byte ratio in compressed types is anomalous
    compressed_types = {"JPEG", "PNG", "PDF", "ZIP", "GZIP", "7ZIP", "RAR"}
    if zero_ratio > 0.90 and detected_type in compressed_types:
        flags.append("high_zero_ratio_in_compressed_type")
    if zero_ratio > 0.98:
        flags.append("near_total_zero_fill")

    # Entropy anomaly: compressed data should not be near 0
    if detected_type in compressed_types and entropy < 1.0 and n > 512:
        flags.append("suspiciously_low_entropy_for_compressed_type")

    # Truncated header: data starts with valid header but is very short
    if header_ok and n < 64:
        flags.append("truncated_header_fragment")

    # JPEG-specific: SOS marker expected but missing
    if detected_type == "JPEG" and header_ok:
        if b"\xff\xda" not in data:
            flags.append("jpeg_sos_marker_missing")
        if n > 32 and data[-2:] != b"\xff\xd9":
            flags.append("jpeg_eoi_marker_missing")

    # PNG-specific: IDAT data expected
    if detected_type == "PNG" and header_ok:
        if b"IDAT" not in data:
            flags.append("png_idat_chunk_missing")

    # PDF-specific: no objects found
    if detected_type == "PDF" and header_ok:
        if not re.search(rb"\d+ \d+ obj", data[:65536]):
            flags.append("pdf_no_objects_found")

    # Abrupt entropy pattern: uniform bytes (all same value)
    if len(set(data[:256])) == 1 and n >= 256:
        flags.append("uniform_byte_pattern")

    return flags


# =============================================================================
# Fragment record builder
# =============================================================================

def _make_fragment_record(
    data: bytes,
    source_file: str,
    source_offset: int,
) -> FragmentRecord:
    """
    Build a real FragmentRecord from raw bytes.
    All measurements are computed from actual bytes — nothing is fabricated.
    """
    sha = _sha256(data)
    md5 = _md5(data)
    frag_id = f"FRAG-{sha[:12].upper()}"

    entropy     = shannon_entropy(data)
    zero_ratio  = _zero_byte_ratio(data)
    print_ratio = _printable_ratio(data)
    freq_sum    = _byte_freq_summary(data)

    first_n = data[:BOUNDARY_WINDOW]
    last_n  = data[-BOUNDARY_WINDOW:] if len(data) >= BOUNDARY_WINDOW else data
    first_bytes_hex = first_n.hex()
    last_bytes_hex  = last_n.hex()

    detected_type, detected_mime = _detect_type(data)
    header_ok       = detected_type != "UNKNOWN"
    footer_ok       = _detect_footer(data, detected_type)
    format_hint     = _infer_format_hint(header_ok, footer_ok)
    internal_m      = _detect_internal_markers(data, detected_type)
    corruption_f    = _detect_corruption_flags(
        data, detected_type, entropy, zero_ratio, header_ok
    )

    # Sector hint: nearest 512-byte sector boundary
    sector_hint: Optional[int] = None
    if source_offset != UNKNOWN_OFFSET:
        sector_hint = (source_offset // 512) * 512

    return FragmentRecord(
        fragment_id       = frag_id,
        source_file       = source_file,
        source_offset     = source_offset,
        length            = len(data),
        sha256            = sha,
        md5               = md5,
        entropy           = round(entropy, 6),
        first_bytes       = first_bytes_hex,
        last_bytes        = last_bytes_hex,
        detected_type     = detected_type,
        detected_mime     = detected_mime,
        format_hint       = format_hint,
        header_compatible = header_ok,
        footer_compatible = footer_ok,
        internal_markers  = internal_m,
        corruption_flags  = corruption_f,
        zero_byte_ratio   = round(zero_ratio, 6),
        printable_ratio   = round(print_ratio, 6),
        byte_freq_summary = freq_sum,
        sector_hint       = sector_hint,
        ingest_error      = None,
    )


# =============================================================================
# Ingestion entry points
# =============================================================================

def ingest_bytes(
    data: bytes,
    label: str = "<bytes>",
    source_offset: int = UNKNOWN_OFFSET,
) -> FragmentRecord:
    """
    Ingest a single in-memory byte buffer.

    source_offset: if the caller knows the physical offset in the source
    image, pass it. Otherwise leave at UNKNOWN_OFFSET — do NOT guess.
    """
    return _make_fragment_record(data, label, source_offset)


def ingest_file(path: Path) -> FragmentRecord:
    """
    Ingest a single binary file as one fragment.

    The file is opened read-only. source_offset = UNKNOWN_OFFSET because
    we have no filesystem metadata linking this file to a disk offset.
    The file's path is used as source_file, but NOT as the type hint.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Fragment file not found: {path}")
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")

    # Open read-only — never write to source evidence
    with open(path, "rb") as fh:
        data = fh.read()

    rec = _make_fragment_record(data, str(path.resolve()), UNKNOWN_OFFSET)
    return rec


def ingest_directory(
    directory: Path,
    recursive: bool = False,
) -> List[FragmentRecord]:
    """
    Ingest every file in a directory as individual fragments.

    Files are processed in inode order (sorted by name) but the ORDER IS NOT
    USED to infer fragment sequence — filenames are arbitrary and may be
    shuffled. Each fragment stands alone; sequencing is a later-phase concern.

    Returns a list of FragmentRecord objects. If a single file fails to
    ingest, an error record is appended (ingest_error set) and ingestion
    continues for remaining files.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    pattern = "**/*" if recursive else "*"
    files = sorted(p for p in directory.glob(pattern) if p.is_file())

    records = []
    for fpath in files:
        try:
            rec = ingest_file(fpath)
            records.append(rec)
        except Exception as exc:
            # Build a minimal error record so the caller sees what failed
            error_rec = FragmentRecord(
                fragment_id       = f"FRAG-ERR-{fpath.name}",
                source_file       = str(fpath.resolve()),
                source_offset     = UNKNOWN_OFFSET,
                length            = 0,
                sha256            = "",
                md5               = "",
                entropy           = 0.0,
                first_bytes       = "",
                last_bytes        = "",
                detected_type     = "UNKNOWN",
                detected_mime     = "application/octet-stream",
                format_hint       = "unknown",
                header_compatible = False,
                footer_compatible = False,
                internal_markers  = [],
                corruption_flags  = [],
                zero_byte_ratio   = 0.0,
                printable_ratio   = 0.0,
                byte_freq_summary = {},
                sector_hint       = None,
                ingest_error      = str(exc),
            )
            records.append(error_rec)

    return records


def ingest_raw_image(
    image_path: Path,
    chunk_size: int = 4096,
) -> List[FragmentRecord]:
    """
    Slice a raw disk image / pendrive dump into cluster-aligned chunks and
    ingest each chunk as a separate fragment.

    source_offset IS known here (it equals chunk_index * chunk_size),
    so it is recorded accurately — not guessed.

    This is the primary path for real forensic inputs.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Raw image not found: {image_path}")

    records: List[FragmentRecord] = []
    source_label = str(image_path.resolve())

    # Open read-only — never write to source evidence
    with open(image_path, "rb") as fh:
        offset = 0
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            rec = _make_fragment_record(chunk, source_label, offset)
            records.append(rec)
            offset += len(chunk)

    return records


# =============================================================================
# Database persistence helpers
# =============================================================================

def _ensure_fragment_records_table(conn) -> None:
    """
    Create the fragment_records table if it doesn't exist.
    This is separate from the existing `fragments` FK table in integrity_pipeline.py
    which stores reconstruction metadata; fragment_records stores raw ingestion data.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fragment_records (
            fragment_id         TEXT,
            source_file         TEXT,
            source_offset       INTEGER,
            length              INTEGER,
            sha256              TEXT,
            md5                 TEXT,
            entropy             REAL,
            first_bytes         TEXT,
            last_bytes          TEXT,
            detected_type       TEXT,
            detected_mime       TEXT,
            format_hint         TEXT,
            header_compatible   INTEGER,
            footer_compatible   INTEGER,
            internal_markers    TEXT,
            corruption_flags    TEXT,
            zero_byte_ratio     REAL,
            printable_ratio     REAL,
            byte_freq_summary   TEXT,
            sector_hint         INTEGER,
            ingest_error        TEXT,
            ingested_at         TEXT DEFAULT CURRENT_TIMESTAMP,
            session_id          TEXT,
            PRIMARY KEY (fragment_id, session_id)
        )
    """)
    conn.commit()


def persist_records(
    records: List[FragmentRecord],
    conn,
    session_id: str,
) -> int:
    """
    Persist fragment records to the database.
    Returns the number of rows written.
    """
    _ensure_fragment_records_table(conn)
    written = 0
    for rec in records:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO fragment_records (
                    fragment_id, source_file, source_offset, length,
                    sha256, md5, entropy, first_bytes, last_bytes,
                    detected_type, detected_mime, format_hint,
                    header_compatible, footer_compatible,
                    internal_markers, corruption_flags,
                    zero_byte_ratio, printable_ratio,
                    byte_freq_summary, sector_hint, ingest_error,
                    session_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                rec.fragment_id,
                rec.source_file,
                rec.source_offset,
                rec.length,
                rec.sha256,
                rec.md5,
                rec.entropy,
                rec.first_bytes,
                rec.last_bytes,
                rec.detected_type,
                rec.detected_mime,
                rec.format_hint,
                int(rec.header_compatible),
                int(rec.footer_compatible),
                json.dumps(rec.internal_markers),
                json.dumps(rec.corruption_flags),
                rec.zero_byte_ratio,
                rec.printable_ratio,
                json.dumps(rec.byte_freq_summary),
                rec.sector_hint,
                rec.ingest_error,
                session_id,
            ))
            written += 1
        except Exception:
            pass
    conn.commit()
    return written
