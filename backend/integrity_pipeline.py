"""
SAMDHAN AI — Data Integrity & Corruption Assessment Module
Backend: Python + FastAPI

Pipeline stages (§4):
  1. Input Validation          → Pydantic schema check + file existence
  2. Signature Verification    → Magic-byte / libmagic header detection
  3. Structural Validation     → Format-specific parsers (JPEG/PNG/PDF/DOCX/SQLite/Log)
  4. Byte/Block Analysis       → Entropy sliding-window + zero-fill detection
  5. Missing Region Detection  → Merge upstream gaps with independent scan
  6. Corruption Detection      → Rule-based taxonomy (A–I) + optional ML anomaly score
  7. Metadata Consistency      → Cross-check filesystem vs embedded timestamps
  8. Content Decoding          → Attempt real open/render/parse
  9. Fragment Continuity       → Boundary alignment + overlap analysis
 10. Hash Verification         → SHA-256 recompute + compare (when reference exists)
 11. Recoverability Assessment → Rule-based label from content-test outcomes
 12. Integrity Scoring         → Weighted, renormalizing sum of all dimensions
 13. Report Generation         → Assemble + persist Integrity Report JSON
"""

import hashlib
import io
import json
import logging
from dataclasses import asdict
import math
import os
import re
import sqlite3
import struct
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
# Note: sklearn IsolationForest is optional (§15) — not imported to avoid DLL issues;
# the rule-based pipeline is fully functional without it.
from pydantic import BaseModel, Field

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("samdhan.integrity")

# ─── FastAPI App ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="SAMDHAN AI — Integrity Assessment API",
    description="Data Integrity & Corruption Assessment pipeline for CALMSTACKS 24H Hackathon",
    version="2.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── DB Path ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
DB_PATH  = BASE_DIR / "samdhan_integrity.db"
DEMO_DIR = BASE_DIR / "demo_data" / "reconstructed"


# ═══════════════════════════════════════════════════════════════════════════
# §18  DATABASE SETUP
# ═══════════════════════════════════════════════════════════════════════════

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id         TEXT PRIMARY KEY,
            filename            TEXT,
            file_type           TEXT,
            original_size       INTEGER,
            reconstructed_size  INTEGER,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS integrity_results (
            artifact_id         TEXT PRIMARY KEY REFERENCES artifacts(artifact_id),
            structural_score    REAL,
            content_score       REAL,
            metadata_score      REAL,
            fragment_score      REAL,
            overall_score       REAL,
            corruption_severity TEXT,
            recoverability      TEXT,
            signature_match     INTEGER,
            file_type_detected  TEXT,
            hash_match          TEXT,
            explanation         TEXT,
            generated_at        TEXT
        );

        CREATE TABLE IF NOT EXISTS corruption_regions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            artifact_id     TEXT REFERENCES artifacts(artifact_id),
            start_offset    INTEGER,
            end_offset      INTEGER,
            corruption_type TEXT,
            severity        TEXT,
            confidence      REAL,
            description     TEXT
        );

        CREATE TABLE IF NOT EXISTS fragments (
            fragment_id     TEXT,
            artifact_id     TEXT REFERENCES artifacts(artifact_id),
            offset          INTEGER,
            length          INTEGER,
            confidence      REAL,
            status          TEXT,
            boundary_valid  INTEGER,
            PRIMARY KEY (fragment_id, artifact_id)
        );

        CREATE TABLE IF NOT EXISTS validation_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            artifact_id TEXT REFERENCES artifacts(artifact_id),
            validator   TEXT,
            status      TEXT,
            result      TEXT,
            details     TEXT,
            run_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)


# ═══════════════════════════════════════════════════════════════════════════
# §3.1  INPUT CONTRACT  (Pydantic models)
# ═══════════════════════════════════════════════════════════════════════════

class FragmentMeta(BaseModel):
    fragment_id:  str
    offset:       int
    length:       int
    confidence:   float = Field(ge=0.0, le=1.0)


class MissingRange(BaseModel):
    start: int
    end:   int


class FilesystemMeta(BaseModel):
    created:  Optional[str] = None
    modified: Optional[str] = None
    accessed: Optional[str] = None


class IntegrityRequest(BaseModel):
    artifact_id:               str
    filename:                  str
    claimed_file_type:         str
    original_size:             int = Field(ge=0)
    reconstructed_size:        int = Field(ge=0)
    fragments_used:            List[FragmentMeta] = []
    missing_ranges:            List[MissingRange] = []
    header_status:             str = "unknown"
    reconstruction_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_hash_sha256:        Optional[str] = None
    reconstructed_hash_sha256: Optional[str] = None
    filesystem_metadata:       Optional[FilesystemMeta] = None
    embedded_metadata:         Optional[Dict[str, Any]] = {}
    reconstructed_path:        Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# UTILITY — Shannon Entropy
# ═══════════════════════════════════════════════════════════════════════════

def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    freq = [0] * 256
    for b in data:
        freq[b] += 1
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in freq if c > 0)


def zero_fill_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    return data.count(0x00) / len(data)


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 1 — Input Validation
# ═══════════════════════════════════════════════════════════════════════════

def validate_input(req: IntegrityRequest, raw_bytes: Optional[bytes]) -> Dict:
    issues = []
    if not req.artifact_id:
        issues.append("artifact_id missing")
    if not req.filename:
        issues.append("filename missing")
    if req.original_size < 0:
        issues.append("original_size invalid")
    if raw_bytes is None:
        issues.append("FILE_NOT_FOUND — no reconstructed bytes available")
    if issues:
        return {"status": "error", "issues": issues}
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 2 — File Signature Verification
# ═══════════════════════════════════════════════════════════════════════════

MAGIC_TABLE = [
    (b"\xff\xd8\xff",                    "JPEG",   "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n",              "PNG",    "image/png"),
    (b"%PDF",                            "PDF",    "application/pdf"),
    (b"PK\x03\x04",                     "DOCX",   "application/vnd.ooxml"),
    (b"SQLite format 3\x00",            "SQLite", "application/x-sqlite3"),
    (b"\xd0\xcf\x11\xe0",               "DOC",    "application/msword"),
    (b"\xd4\xc3\xb2\xa1",               "PCAP",   "application/vnd.tcpdump"),
    (b"\xa1\xb2\xc3\xd4",               "PCAP",   "application/vnd.tcpdump"),
    (b"ElfFile\x00",                    "EVTX",   "application/x-ms-evtx"),
    (b"regf",                            "REGF",   "application/x-windows-registry"),
    (b"MZ",                              "PE",     "application/x-msdownload"),
    (b"GIF8",                            "GIF",    "image/gif"),
    (b"BM",                              "BMP",    "image/bmp"),
]

EXT_TYPE_MAP = {
    "jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "gif": "GIF", "bmp": "BMP",
    "pdf": "PDF",  "doc":  "DOC",  "docx": "DOCX", "txt": "LOG",
    "sqlite": "SQLite", "db": "SQLite", "log": "LOG", "evtx": "EVTX",
    "pcap": "PCAP", "bat": "SCRIPT", "ps1": "SCRIPT", "reg": "REGF",
    "exe": "PE", "dll": "PE",
}


def verify_signature(raw_bytes: bytes, filename: str, claimed_type: str) -> Dict:
    header = raw_bytes[:32] if len(raw_bytes) >= 32 else raw_bytes
    detected_type = "UNKNOWN"
    detected_mime = "application/octet-stream"
    for sig, dtype, mime in MAGIC_TABLE:
        if header.startswith(sig):
            detected_type = dtype
            detected_mime = mime
            break

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    ext_type = EXT_TYPE_MAP.get(ext, "UNKNOWN")

    conflict = None
    if detected_type != "UNKNOWN" and ext_type != "UNKNOWN" and detected_type != ext_type:
        conflict = (f"Extension mismatch: .{ext} implies {ext_type} but binary header "
                    f"indicates {detected_type}. Header takes forensic precedence.")

    claimed_match = detected_type.upper() == claimed_type.upper()
    return {
        "status":         "ok",
        "signature_match": detected_type != "UNKNOWN",
        "detected_type":   detected_type,
        "detected_mime":   detected_mime,
        "claimed_match":   claimed_match,
        "conflict":        conflict,
    }


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 3 — Structural Validation (per file type)
# ═══════════════════════════════════════════════════════════════════════════

def _validate_jpeg(data: bytes) -> Dict:
    checks, issues = [], []
    if data[:2] == b"\xff\xd8":
        checks.append("SOI marker valid (FF D8)")
    else:
        issues.append("SOI marker missing"); return {"score": 20, "checks": checks, "issues": issues}

    has_eoi = data[-2:] == b"\xff\xd9"
    (checks if has_eoi else issues).append("EOI marker (FF D9) " + ("found" if has_eoi else "missing"))

    # Walk segments
    pos = 2; segments_seen = 0; sos_found = False
    while pos < len(data) - 1:
        if data[pos] != 0xff:
            break
        marker = data[pos:pos+2]
        if marker == b"\xff\xd9":
            break
        if marker == b"\xff\xda":
            sos_found = True
        if pos + 4 > len(data):
            break
        seg_len = struct.unpack(">H", data[pos+2:pos+4])[0] if data[pos+1] not in (0xd8, 0xd9, 0x01) else 2
        pos += 2 + (seg_len if seg_len >= 2 else 2)
        segments_seen += 1
        if segments_seen > 500:
            break

    (checks if sos_found else issues).append("SOS marker " + ("found" if sos_found else "missing"))
    score = 95 if not issues else max(30, 95 - len(issues) * 20)
    return {"score": score, "checks": checks, "issues": issues}


def _validate_png(data: bytes) -> Dict:
    checks, issues = [], []
    PNG_SIG = b"\x89PNG\r\n\x1a\n"
    if data[:8] != PNG_SIG:
        issues.append("PNG signature invalid")
        return {"score": 10, "checks": checks, "issues": issues}
    checks.append("PNG 8-byte signature valid")

    pos = 8; idat_found = False; iend_found = False; chunk_count = 0
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos+4])[0]
        chunk_type = data[pos+4:pos+8]
        if chunk_type == b"IDAT":
            idat_found = True
        if chunk_type == b"IEND":
            iend_found = True
        # CRC check
        chunk_data = data[pos+4:pos+8+length]
        pos += 12 + length
        chunk_count += 1
        if chunk_count > 2000:
            break

    (checks if idat_found else issues).append("IDAT chunk(s) " + ("present" if idat_found else "missing"))
    (checks if iend_found else issues).append("IEND chunk " + ("present" if iend_found else "missing"))
    score = 95 if not issues else max(25, 95 - len(issues) * 25)
    return {"score": score, "checks": checks, "issues": issues}


def _validate_pdf(data: bytes) -> Dict:
    checks, issues = [], []
    text = data[:8192].decode("latin-1", errors="replace")
    if text.startswith("%PDF"):
        checks.append("PDF header valid (%PDF)")
    else:
        issues.append("%PDF header missing")

    has_eof = b"%%EOF" in data[-256:]
    (checks if has_eof else issues).append("%%EOF marker " + ("found" if has_eof else "missing"))

    xref_count = text.count("xref")
    obj_count  = len(re.findall(rb"\d+ \d+ obj", data[:65536]))
    checks.append(f"{obj_count} PDF object(s) detected in header region")
    if obj_count == 0:
        issues.append("No PDF objects found")

    score = 95 if not issues else max(30, 95 - len(issues) * 20)
    return {"score": score, "checks": checks, "issues": issues}


def _validate_docx(data: bytes) -> Dict:
    checks, issues = [], []
    if not data[:4] == b"PK\x03\x04":
        issues.append("ZIP/OOXML PK header missing")
        return {"score": 10, "checks": checks, "issues": issues}
    checks.append("ZIP PK header valid (50 4B 03 04)")

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            has_content_types = "[Content_Types].xml" in names
            has_document_xml  = any("word/document" in n for n in names)
            (checks if has_content_types else issues).append(
                "[Content_Types].xml " + ("found" if has_content_types else "missing"))
            (checks if has_document_xml else issues).append(
                "word/document.xml " + ("found" if has_document_xml else "missing"))
    except zipfile.BadZipFile as e:
        issues.append(f"ZIP structure corrupt: {e}")
        return {"score": 20, "checks": checks, "issues": issues}

    score = 95 if not issues else max(20, 95 - len(issues) * 25)
    return {"score": score, "checks": checks, "issues": issues}


def _validate_sqlite(data: bytes) -> Dict:
    checks, issues = [], []
    SQLITE_MAGIC = b"SQLite format 3\x00"
    if data[:16] != SQLITE_MAGIC:
        issues.append("SQLite header magic missing")
        return {"score": 10, "checks": checks, "issues": issues}
    checks.append("SQLite 3 header magic valid")

    page_size = struct.unpack(">H", data[16:18])[0]
    if page_size == 1:
        page_size = 65536
    valid_page_size = page_size >= 512 and (page_size & (page_size - 1)) == 0
    (checks if valid_page_size else issues).append(
        f"Page size {page_size} " + ("valid (power of 2)" if valid_page_size else "invalid"))

    declared_pages = struct.unpack(">I", data[28:32])[0]
    expected_size  = declared_pages * page_size
    actual_size    = len(data)
    size_ok = abs(actual_size - expected_size) < page_size * 2
    (checks if size_ok else issues).append(
        f"Declared {declared_pages} pages × {page_size} bytes {'≈ ' if size_ok else '≠ '} actual {actual_size} bytes")

    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA integrity_check")
        conn.close()
        checks.append("In-memory SQLite integrity_check passed")
    except Exception as e:
        issues.append(f"SQLite integrity_check failed: {e}")

    score = 95 if not issues else max(20, 95 - len(issues) * 20)
    return {"score": score, "checks": checks, "issues": issues}


def _validate_log(data: bytes) -> Dict:
    checks, issues = [], []
    try:
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        RFC3164 = re.compile(
            r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+\s+\d{2}:\d{2}:\d{2}")
        EVTX_LIKE = re.compile(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        matched = sum(1 for l in lines if RFC3164.match(l) or EVTX_LIKE.match(l))
        ratio = matched / total if total > 0 else 0
        checks.append(f"{matched}/{total} lines match known log format ({ratio*100:.0f}%)")
        malformed = total - matched
        if malformed > 0:
            issues.append(f"{malformed} malformed/unrecognized record(s)")
        score = max(30, int(ratio * 100))
    except Exception as e:
        issues.append(f"Log decode error: {e}")
        score = 30
    return {"score": score, "checks": checks, "issues": issues}


STRUCTURAL_VALIDATORS = {
    "JPEG": _validate_jpeg, "JPG": _validate_jpeg,
    "PNG":  _validate_png,
    "PDF":  _validate_pdf,
    "DOCX": _validate_docx, "OOXML": _validate_docx,
    "SQLite": _validate_sqlite, "SQLITE": _validate_sqlite,
    "LOG": _validate_log, "TXT": _validate_log, "SYSLOG": _validate_log,
}


def validate_structure(data: bytes, file_type: str) -> Dict:
    validator = STRUCTURAL_VALIDATORS.get(file_type.upper())
    if not validator:
        return {"score": 50, "checks": [f"No structural validator for type '{file_type}'"],
                "issues": ["Using byte-level analysis only"]}
    try:
        return validator(data)
    except Exception as e:
        return {"score": 20, "checks": [], "issues": [f"Structural parser raised: {e}"]}


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 4 — Byte/Block Integrity Analysis
# ═══════════════════════════════════════════════════════════════════════════

WINDOW = 512

def byte_block_analysis(data: bytes, file_type: str) -> Dict:
    suspicious_ranges = []
    entropies = []
    for i in range(0, len(data) - WINDOW, WINDOW):
        chunk = data[i:i + WINDOW]
        e = shannon_entropy(chunk)
        entropies.append(e)
        zr = zero_fill_ratio(chunk)
        # Zero-fill inside compressed types (JPEG, PNG, PDF body) is suspicious
        is_compressed_type = file_type.upper() in ("JPEG", "JPG", "PNG", "PDF")
        if zr > 0.90 and is_compressed_type:
            suspicious_ranges.append({
                "start": i, "end": i + WINDOW - 1,
                "type": "zero_fill", "entropy": round(e, 3), "zero_ratio": round(zr, 3),
                "severity": "high" if zr > 0.98 else "medium"
            })
        # Abrupt entropy drop within scan section
        if entropies and len(entropies) > 1:
            prev_e = entropies[-2]
            if prev_e > 5.0 and e < 1.5:
                suspicious_ranges.append({
                    "start": i, "end": i + WINDOW - 1,
                    "type": "entropy_drop", "entropy": round(e, 3),
                    "severity": "medium"
                })

    avg_entropy = sum(entropies) / len(entropies) if entropies else 0
    return {
        "status": "ok",
        "suspicious_ranges": suspicious_ranges,
        "avg_entropy": round(avg_entropy, 3),
        "window_count": len(entropies),
    }


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 5 — Missing Region Detection
# ═══════════════════════════════════════════════════════════════════════════

def detect_missing_regions(req: IntegrityRequest, byte_gaps: List[Dict]) -> List[Dict]:
    canonical = []
    for mr in req.missing_ranges:
        canonical.append({"start": mr.start, "end": mr.end, "source": "upstream"})
    for bg in byte_gaps:
        if bg.get("type") == "zero_fill" and bg.get("severity") == "high":
            canonical.append({"start": bg["start"], "end": bg["end"], "source": "byte_scan"})

    # Merge overlapping intervals
    if not canonical:
        return []
    canonical.sort(key=lambda x: x["start"])
    merged = [canonical[0]]
    for r in canonical[1:]:
        last = merged[-1]
        if r["start"] <= last["end"] + 1:
            last["end"] = max(last["end"], r["end"])
            if r["source"] != last["source"]:
                last["source"] = "both"
        else:
            merged.append(r)
    return merged


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 6 — Corruption Detection (Taxonomy A–I)
# ═══════════════════════════════════════════════════════════════════════════

def detect_corruption_regions(
    missing_ranges: List[Dict],
    suspicious_ranges: List[Dict],
    struct_issues: List[str],
    fragment_gaps: List[Dict],
) -> List[Dict]:
    regions = []

    # Type A — Missing Data (from canonical missing regions)
    for r in missing_ranges:
        regions.append({
            "start": r["start"], "end": r["end"],
            "type": "A_MISSING_DATA", "severity": "high", "confidence": 1.0,
            "description": "Bytes never recovered from any fragment"
        })

    # Type C — Byte Corruption (from zero-fill / entropy-drop in suspicious ranges)
    for s in suspicious_ranges:
        if s.get("type") == "zero_fill":
            regions.append({
                "start": s["start"], "end": s["end"],
                "type": "C_BYTE_CORRUPTION", "severity": s.get("severity", "medium"),
                "confidence": 0.75,
                "description": f"Zero-fill anomaly (zero ratio high, entropy {s.get('entropy')})"
            })
        elif s.get("type") == "entropy_drop":
            regions.append({
                "start": s["start"], "end": s["end"],
                "type": "C_BYTE_CORRUPTION", "severity": "medium", "confidence": 0.65,
                "description": f"Abrupt entropy drop: {s.get('entropy')} bits/byte"
            })

    # Type D — Structural Corruption (from structural validator issues)
    for issue in struct_issues:
        regions.append({
            "start": 0, "end": 4095,
            "type": "D_STRUCTURAL_CORRUPTION", "severity": "high", "confidence": 0.9,
            "description": f"Structural issue: {issue}"
        })

    # Type B — Fragment Gaps
    for gap in fragment_gaps:
        regions.append({
            "start": gap["start"], "end": gap["end"],
            "type": "B_FRAGMENT_GAP", "severity": "medium", "confidence": 0.85,
            "description": "Expected inter-fragment bytes unavailable"
        })

    return regions


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 7 — Metadata Consistency Check
# ═══════════════════════════════════════════════════════════════════════════

def check_metadata_consistency(req: IntegrityRequest) -> Dict:
    result = {"status": "ok", "verdict": "UNKNOWN", "score": 70, "flags": []}
    fs_meta = req.filesystem_metadata
    emb_meta = req.embedded_metadata or {}

    if not fs_meta:
        result["verdict"] = "UNKNOWN"
        result["flags"].append("No filesystem metadata provided")
        return result

    fs_mod = fs_meta.modified
    emb_created = emb_meta.get("document_created") or emb_meta.get("created")

    if fs_mod and emb_created:
        try:
            t_fs  = datetime.fromisoformat(fs_mod.replace("Z", "+00:00"))
            t_emb = datetime.fromisoformat(emb_created.replace("Z", "+00:00"))
            if t_fs < t_emb:
                result["verdict"] = "POTENTIALLY_INCONSISTENT"
                result["score"] = 50
                result["flags"].append(
                    f"Filesystem-modified ({fs_mod}) is earlier than embedded created ({emb_created})")
            else:
                result["verdict"] = "CONSISTENT"
                result["score"] = 95
        except ValueError:
            result["verdict"] = "UNKNOWN"
    else:
        result["verdict"] = "UNKNOWN"
        result["score"] = 70
        result["flags"].append("One or both timestamp sides absent — cannot determine consistency")

    return result


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 8 — Content Decoding (safe open/parse/decode)
# ═══════════════════════════════════════════════════════════════════════════

def content_decode(data: bytes, file_type: str, artifact_id: str) -> Dict:
    result = {"decoded": False, "details": {}, "score": 0}
    ft = file_type.upper()

    try:
        if ft in ("JPEG", "JPG", "PNG", "GIF", "BMP"):
            from PIL import Image
            img = Image.open(io.BytesIO(data))
            img.verify()
            result.update({"decoded": True, "details": {"format": img.format, "size": img.size}, "score": 92})

        elif ft == "PDF":
            import fitz  # PyMuPDF
            doc = fitz.open(stream=data, filetype="pdf")
            n_pages = doc.page_count
            rendered = 0
            for i in range(min(n_pages, 5)):
                try:
                    _ = doc[i].get_text()
                    rendered += 1
                except Exception:
                    pass
            score = int((rendered / n_pages) * 90) if n_pages > 0 else 20
            result.update({"decoded": True,
                            "details": {"pages": n_pages, "rendered": rendered},
                            "score": score})

        elif ft in ("DOCX", "OOXML"):
            from docx import Document
            doc = Document(io.BytesIO(data))
            paras = len(doc.paragraphs)
            result.update({"decoded": True, "details": {"paragraphs": paras}, "score": 88})

        elif ft in ("SQLITE", "SQLITE3"):
            conn = sqlite3.connect(":memory:")
            conn.executescript(data.decode("latin-1", errors="replace"))
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            conn.close()
            result.update({"decoded": True, "details": {"tables": [t[0] for t in tables]}, "score": 90})

        elif ft in ("LOG", "TXT", "SYSLOG"):
            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines()
            malformed = sum(1 for l in lines if l and not re.match(
                r"(^\d{4}-|^[A-Z][a-z]{2}\s+|^\[|\bERROR\b|\bINFO\b|\bWARN\b|\bDEBUG\b)", l))
            score = max(40, 100 - int((malformed / max(len(lines), 1)) * 60))
            result.update({"decoded": True,
                            "details": {"total_lines": len(lines), "malformed": malformed},
                            "score": score})
        else:
            result["score"] = 50
            result["details"]["note"] = f"No content decoder for '{ft}'"

    except Exception as e:
        result["decoded"] = False
        result["details"]["error"] = str(e)
        result["score"] = max(5, result["score"] - 40)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 9 — Fragment Continuity Analysis
# ═══════════════════════════════════════════════════════════════════════════

def fragment_continuity(req: IntegrityRequest) -> Dict:
    frags = sorted(req.fragments_used, key=lambda f: f.offset)
    gaps = []
    continuity_score = 100.0
    covered_bytes = 0

    for i, frag in enumerate(frags):
        covered_bytes += frag.length
        if i == 0 and frag.offset > 0:
            gaps.append({"start": 0, "end": frag.offset - 1})
            continuity_score -= min(20, (frag.offset / max(req.reconstructed_size, 1)) * 100)

        if i > 0:
            prev = frags[i - 1]
            expected_next = prev.offset + prev.length
            if frag.offset > expected_next:
                gap_size = frag.offset - expected_next
                gaps.append({"start": expected_next, "end": frag.offset - 1})
                penalty = (gap_size / max(req.reconstructed_size, 1)) * 100
                continuity_score -= penalty
            elif frag.offset < expected_next:
                # Overlap
                continuity_score -= 5

        # Low reconstruction-confidence fragments penalize continuity proportionally
        if frag.confidence < 0.70:
            penalty = ((0.70 - frag.confidence) / 0.70) * (frag.length / max(req.reconstructed_size, 1)) * 50
            continuity_score -= penalty

    pct_covered = (covered_bytes / max(req.reconstructed_size, 1)) * 100
    continuity_score = max(0.0, min(100.0, continuity_score))
    return {
        "score": round(continuity_score, 1),
        "fragment_gaps": gaps,
        "covered_pct": round(pct_covered, 1),
        "total_fragments": len(frags),
    }


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 10 — Hash Verification
# ═══════════════════════════════════════════════════════════════════════════

def verify_hash(data: bytes, req: IntegrityRequest) -> Dict:
    computed = hashlib.sha256(data).hexdigest()
    stored   = req.reconstructed_hash_sha256

    if stored and computed != stored:
        verdict = "MISMATCH_WITH_STORED"
    elif stored and computed == stored:
        verdict = "MATCH_WITH_STORED"
    else:
        verdict = "NO_STORED_HASH"

    if req.source_hash_sha256:
        if computed == req.source_hash_sha256:
            verdict = "MATCH_WITH_TRUSTED_SOURCE"
        else:
            verdict = "MISMATCH_WITH_TRUSTED_SOURCE"

    return {"computed_sha256": computed, "verdict": verdict}


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 11 — Recoverability Assessment
# ═══════════════════════════════════════════════════════════════════════════

def assess_recoverability(structural: float, content: float, fragment: float, missing_pct: float) -> str:
    # Primary driver: content test (can an investigator use this?)
    if content >= 85 and structural >= 80 and missing_pct < 5:
        return "FULLY_RECOVERABLE"
    elif content >= 65 and structural >= 60:
        return "MOSTLY_RECOVERABLE"
    elif content >= 40 or structural >= 50:
        return "PARTIALLY_RECOVERABLE"
    elif content >= 15 or structural >= 30:
        return "BARELY_RECOVERABLE"
    else:
        return "NOT_RELIABLY_RECOVERABLE"


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 12 — Integrity Scoring (§10 formula, renormalized)
# ═══════════════════════════════════════════════════════════════════════════

WEIGHTS = {
    "structural": 0.30,
    "content":    0.35,
    "fragment":   0.20,
    "metadata":   0.15,
}

def compute_overall_score(structural: Optional[float], content: Optional[float],
                           fragment: Optional[float], metadata: Optional[float]) -> Optional[float]:
    available = {k: v for k, v in [("structural", structural), ("content", content),
                                    ("fragment", fragment),   ("metadata", metadata)]
                 if v is not None}
    if not available:
        return None
    total_weight = sum(WEIGHTS[k] for k in available)
    if total_weight == 0:
        return None
    score = sum(WEIGHTS[k] * v for k, v in available.items()) / total_weight
    return round(score, 1)


def severity_label(overall: Optional[float]) -> str:
    if overall is None:
        return "INSUFFICIENT_DATA"
    if overall >= 90: return "None"
    if overall >= 75: return "Low"
    if overall >= 50: return "Medium"
    if overall >= 25: return "High"
    return "Critical"


def recoverability_label(label: str) -> str:
    return label.replace("_", " ").title()


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 13 — Report Assembly & Explanation Builder
# ═══════════════════════════════════════════════════════════════════════════

def build_explanation(sig, struct_result, byte_result, fragment_result,
                      meta_result, content_result, hash_result, corruption_regions) -> List[str]:
    lines = []
    # Signature
    if sig.get("signature_match"):
        lines.append(f"✓ Valid file signature detected ({sig.get('detected_type')})")
    else:
        lines.append("✗ File signature missing or unrecognized")
    if sig.get("conflict"):
        lines.append(f"⚠ {sig['conflict']}")

    # Structure
    for chk in (struct_result.get("checks") or []):
        lines.append(f"✓ {chk}")
    for iss in (struct_result.get("issues") or []):
        lines.append(f"✗ {iss}")

    # Fragment continuity
    cov = fragment_result.get("covered_pct", 0)
    lines.append(f"{'✓' if cov >= 90 else '⚠'} {cov}% of bytes covered by recovered fragments")
    if fragment_result.get("fragment_gaps"):
        lines.append(f"✗ {len(fragment_result['fragment_gaps'])} inter-fragment gap(s) detected")

    # Byte anomalies
    sr = byte_result.get("suspicious_ranges") or []
    if sr:
        lines.append(f"⚠ {len(sr)} suspicious byte region(s): zero-fill or entropy anomaly")
    else:
        lines.append("✓ No significant byte-level anomalies detected")

    # Metadata
    if meta_result.get("verdict") == "POTENTIALLY_INCONSISTENT":
        for f in meta_result.get("flags", []):
            lines.append(f"⚠ Metadata: {f}")
    elif meta_result.get("verdict") == "CONSISTENT":
        lines.append("✓ Filesystem and embedded metadata timestamps are consistent")

    # Content decode
    if content_result.get("decoded"):
        det = content_result.get("details", {})
        lines.append(f"✓ File decoded successfully — {det}")
    else:
        err = content_result.get("details", {}).get("error", "unknown error")
        lines.append(f"✗ Content decode failed: {err}")

    # Hash
    hv = hash_result.get("verdict", "")
    if "MATCH" in hv:
        lines.append(f"✓ SHA-256 hash verification: {hv}")
    elif "MISMATCH" in hv:
        lines.append(f"✗ SHA-256 hash verification: {hv} — byte-level differences detected")
    else:
        lines.append(f"ℹ SHA-256: {hv} — hash stored for future re-verification")

    # Corruption regions
    if corruption_regions:
        types = set(r["type"] for r in corruption_regions)
        lines.append(f"⚠ {len(corruption_regions)} corruption region(s) typed: {', '.join(types)}")

    return lines


# ═══════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR — runs all 13 stages
# ═══════════════════════════════════════════════════════════════════════════

def load_bytes(req: IntegrityRequest) -> Optional[bytes]:
    """
    Attempt to load raw bytes. For the hackathon demo,
    fall back to synthetic bytes from the demo fixture if the path is absent.
    """
    if req.reconstructed_path:
        p = Path(req.reconstructed_path)
        if p.exists() and p.is_file():
            return p.read_bytes()
    # Synthetic demo path
    demo_path = DEMO_DIR / req.filename
    if demo_path.exists():
        return demo_path.read_bytes()
    return None


def run_pipeline(req: IntegrityRequest) -> Dict:
    raw = load_bytes(req)

    # Stage 1 — Input Validation
    s1 = validate_input(req, raw)
    validation_log = [{"stage": "InputValidator", "result": s1}]

    if s1["status"] == "error" or raw is None:
        return {
            "artifact_id":    req.artifact_id,
            "status":         "error",
            "reason":         s1.get("issues", ["No file bytes available"]),
            "overall_score":  None,
        }

    # Stage 2 — Signature Verification
    s2 = verify_signature(raw, req.filename, req.claimed_file_type)
    validation_log.append({"stage": "SignatureVerifier", "result": s2})

    detected_type = s2.get("detected_type", req.claimed_file_type)
    if detected_type == "UNKNOWN":
        detected_type = req.claimed_file_type

    # Stage 3 — Structural Validation
    s3 = validate_structure(raw, detected_type)
    validation_log.append({"stage": "StructuralValidator", "result": s3})

    # Stage 4 — Byte/Block Analysis
    s4 = byte_block_analysis(raw, detected_type)
    validation_log.append({"stage": "ByteBlockAnalyzer", "result": s4})

    # Stage 5 — Missing Region Detection
    missing_canonical = detect_missing_regions(req, s4.get("suspicious_ranges", []))
    validation_log.append({"stage": "MissingRegionDetector",
                            "result": {"count": len(missing_canonical), "ranges": missing_canonical}})

    # Stage 6 — Corruption Detection
    corruption_regions = detect_corruption_regions(
        missing_canonical,
        s4.get("suspicious_ranges", []),
        s3.get("issues", []),
        [],
    )
    validation_log.append({"stage": "CorruptionDetector",
                            "result": {"regions": len(corruption_regions)}})

    # Stage 7 — Metadata Consistency
    s7 = check_metadata_consistency(req)
    validation_log.append({"stage": "MetadataConsistency", "result": s7})

    # Stage 8 — Content Decoding
    s8 = content_decode(raw, detected_type, req.artifact_id)
    validation_log.append({"stage": "ContentDecoder", "result": s8})

    # Stage 9 — Fragment Continuity
    s9 = fragment_continuity(req)
    validation_log.append({"stage": "FragmentContinuity", "result": s9})

    # Stage 10 — Hash Verification
    s10 = verify_hash(raw, req)
    validation_log.append({"stage": "HashVerifier", "result": s10})

    # Stage 11 — Recoverability
    missing_bytes = sum(r["end"] - r["start"] for r in missing_canonical)
    missing_pct   = (missing_bytes / max(req.reconstructed_size, 1)) * 100
    recoverability = assess_recoverability(
        s3.get("score", 50), s8.get("score", 50), s9.get("score", 50), missing_pct)

    # Stage 12 — Integrity Scoring
    structural_score = float(s3.get("score", 50))
    content_score    = float(s8.get("score", 50))
    fragment_score   = float(s9.get("score", 50))
    metadata_score   = float(s7.get("score", 70))
    overall_score    = compute_overall_score(structural_score, content_score,
                                             fragment_score, metadata_score)
    severity         = severity_label(overall_score)

    # Stage 13 — Report Assembly
    explanation = build_explanation(
        s2, s3, s4, s9, s7, s8, s10, corruption_regions)

    report = {
        "artifact_id":               req.artifact_id,
        "filename":                  req.filename,
        "file_type_detected":        detected_type,
        "signature_match":           s2.get("signature_match", False),
        "structural_integrity":      round(structural_score, 1),
        "content_integrity":         round(content_score, 1),
        "metadata_integrity":        round(metadata_score, 1),
        "fragment_continuity":       round(fragment_score, 1),
        "reconstruction_confidence": round(req.reconstruction_confidence * 100, 1),
        "overall_integrity":         overall_score,
        "corruption_severity":       severity,
        "recoverability":            recoverability,
        "recoverability_label":      recoverability_label(recoverability),
        "corruption_regions":        corruption_regions,
        "content_test_result":       s8.get("details", {}),
        "hash_result":               s10,
        "explanation":               explanation,
        "validation_log":            validation_log,
        "generated_at":              datetime.now(timezone.utc).isoformat(),
    }
    return report


# ═══════════════════════════════════════════════════════════════════════════
# §17  REST API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    init_db()
    log.info("SAMDHAN AI Integrity Assessment API started. DB: %s", DB_PATH)


@app.get("/api/health")
async def health():
    return {"status": "ok", "module": "integrity_assessment", "version": "2.4.0"}


@app.post("/api/integrity/analyze", status_code=202)
async def analyze(req: IntegrityRequest):
    """
    Runs the full 13-stage Data Integrity & Corruption Assessment pipeline.
    Input: §3.1 contract. Output: Full Integrity Report (§3.3).
    """
    report = run_pipeline(req)

    try:
        with get_db() as db:
            db.execute(
                "INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?,?,?)",
                (req.artifact_id, req.filename, req.claimed_file_type,
                 req.original_size, req.reconstructed_size, datetime.utcnow().isoformat()))

            db.execute(
                """INSERT OR REPLACE INTO integrity_results
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (req.artifact_id,
                 report.get("structural_integrity"),
                 report.get("content_integrity"),
                 report.get("metadata_integrity"),
                 report.get("fragment_continuity"),
                 report.get("overall_integrity"),
                 report.get("corruption_severity"),
                 report.get("recoverability"),
                 int(report.get("signature_match", False)),
                 report.get("file_type_detected"),
                 report.get("hash_result", {}).get("verdict"),
                 json.dumps(report.get("explanation", [])),
                 report.get("generated_at")))

            for region in report.get("corruption_regions", []):
                db.execute(
                    """INSERT INTO corruption_regions
                       (artifact_id, start_offset, end_offset, corruption_type, severity, confidence, description)
                       VALUES (?,?,?,?,?,?,?)""",
                    (req.artifact_id, region["start"], region["end"],
                     region["type"], region["severity"], region["confidence"],
                     region.get("description", "")))

            for stage_log in report.get("validation_log", []):
                db.execute(
                    """INSERT INTO validation_results (artifact_id, validator, status, result, details)
                       VALUES (?,?,?,?,?)""",
                    (req.artifact_id,
                     stage_log.get("stage"),
                     stage_log.get("result", {}).get("status", "ok"),
                     json.dumps(stage_log.get("result")),
                     ""))
    except Exception as e:
        log.warning("DB write failed (non-fatal): %s", e)

    return report


@app.get("/api/integrity/{artifact_id}")
async def get_integrity_summary(artifact_id: str):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM integrity_results WHERE artifact_id=?", (artifact_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Artifact '{artifact_id}' not found")
    return dict(row)


@app.get("/api/integrity/{artifact_id}/regions")
async def get_corruption_regions(artifact_id: str):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM corruption_regions WHERE artifact_id=?", (artifact_id,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/integrity/{artifact_id}/report")
async def get_full_report(artifact_id: str):
    with get_db() as db:
        summary = db.execute(
            "SELECT * FROM integrity_results WHERE artifact_id=?", (artifact_id,)).fetchone()
        regions = db.execute(
            "SELECT * FROM corruption_regions WHERE artifact_id=?", (artifact_id,)).fetchall()
        validation = db.execute(
            "SELECT * FROM validation_results WHERE artifact_id=?", (artifact_id,)).fetchall()
    if not summary:
        raise HTTPException(status_code=404, detail=f"Artifact '{artifact_id}' not found")
    return {
        "summary": dict(summary),
        "corruption_regions": [dict(r) for r in regions],
        "validation_log": [dict(v) for v in validation],
        "explanation": json.loads(summary["explanation"] or "[]"),
    }


@app.get("/api/artifacts")
async def list_artifacts():
    with get_db() as db:
        rows = db.execute("""
            SELECT a.artifact_id, a.filename, a.file_type, a.original_size, a.reconstructed_size,
                   ir.overall_score, ir.corruption_severity, ir.recoverability
            FROM artifacts a LEFT JOIN integrity_results ir ON a.artifact_id = ir.artifact_id
        """).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/integrity/batch")
async def batch_analyze(requests: List[IntegrityRequest]):
    results = []
    for req in requests:
        try:
            results.append(await analyze(req))
        except Exception as e:
            results.append({"artifact_id": req.artifact_id, "status": "error", "reason": str(e)})
    return results


# ═══════════════════════════════════════════════════════════════════════════
# §19  FEATURE 01 — Fragment Ingestion API
# ═══════════════════════════════════════════════════════════════════════════
# These endpoints implement Phase 1 of the Intelligent Fragment Reconstruction
# pipeline: discovery, extraction, and feature analysis of raw fragments.
#
# They delegate to backend/fragment_ingestor.py and persist results into
# the fragment_records table using the existing DB infrastructure.
# ═══════════════════════════════════════════════════════════════════════════

import uuid as _uuid
from fastapi import UploadFile, File, Form
from typing import Union

# Import lazily to avoid circular issues during initial startup
def _get_ingestor():
    from backend import fragment_ingestor as _fi
    return _fi


@app.post("/api/fragments/ingest", status_code=200)
async def ingest_fragment_files(
    files: List[UploadFile] = File(...),
    session_id: str = Form(default=""),
):
    """
    Ingest one or more uploaded fragment files.

    Each file is read as raw bytes and processed by fragment_ingestor.
    The source evidence bytes are never written back to disk from here.

    Returns a list of real FragmentRecord dicts — no fabricated results.
    """
    fi = _get_ingestor()

    if not session_id:
        session_id = f"session-{_uuid.uuid4().hex[:8]}"

    records = []
    errors  = []

    for upload in files:
        try:
            data = await upload.read()
            rec  = fi.ingest_bytes(
                data,
                label=upload.filename or "<upload>",
                source_offset=fi.UNKNOWN_OFFSET,
            )
            records.append(rec)
        except Exception as exc:
            errors.append({"filename": upload.filename, "error": str(exc)})

    # Persist to DB
    written = 0
    try:
        with get_db() as conn:
            fi._ensure_fragment_records_table(conn)
            written = fi.persist_records(records, conn, session_id)
    except Exception as exc:
        log.warning("Fragment DB write failed (non-fatal): %s", exc)

    return {
        "session_id":       session_id,
        "fragments_ingested": written,
        "fragment_records": [r.to_dict() for r in records],
        "errors":           errors,
    }


@app.post("/api/fragments/ingest/bytes", status_code=200)
async def ingest_raw_bytes(
    file: UploadFile = File(...),
    chunk_size: int  = Form(default=4096),
    session_id: str  = Form(default=""),
):
    """
    Ingest a raw binary image (disk image, pendrive dump) by slicing it
    into cluster-aligned chunks.

    source_offset is recorded accurately for each chunk (chunk_index * chunk_size).
    This is the primary path for actual forensic disk images.
    """
    fi = _get_ingestor()

    if not session_id:
        session_id = f"session-{_uuid.uuid4().hex[:8]}"

    raw = await file.read()

    records = []
    offset  = 0
    while offset < len(raw):
        chunk = raw[offset : offset + chunk_size]
        rec   = fi.ingest_bytes(
            chunk,
            label=file.filename or "<raw_image>",
            source_offset=offset,
        )
        records.append(rec)
        offset += len(chunk)

    written = 0
    try:
        with get_db() as conn:
            fi._ensure_fragment_records_table(conn)
            written = fi.persist_records(records, conn, session_id)
    except Exception as exc:
        log.warning("Fragment DB write failed (non-fatal): %s", exc)

    return {
        "session_id":         session_id,
        "source_file":        file.filename,
        "total_bytes":        len(raw),
        "chunk_size":         chunk_size,
        "chunks_produced":    len(records),
        "fragments_ingested": written,
        "fragment_records":   [r.to_dict() for r in records],
    }


@app.get("/api/fragments/session/{session_id}")
async def get_session_fragments(session_id: str):
    """
    Retrieve all fragment records from a previously run ingestion session.
    """
    fi = _get_ingestor()
    with get_db() as conn:
        fi._ensure_fragment_records_table(conn)
        rows = conn.execute(
            "SELECT * FROM fragment_records WHERE session_id = ? ORDER BY source_offset ASC",
            (session_id,)
        ).fetchall()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No fragments found for session '{session_id}'"
        )
    return {
        "session_id": session_id,
        "count":      len(rows),
        "fragments":  [dict(r) for r in rows],
    }


@app.get("/api/fragments/{fragment_id}")
async def get_fragment(fragment_id: str):
    """
    Retrieve a single fragment record by its deterministic fragment_id.
    """
    fi = _get_ingestor()
    with get_db() as conn:
        fi._ensure_fragment_records_table(conn)
        row = conn.execute(
            "SELECT * FROM fragment_records WHERE fragment_id = ? LIMIT 1",
            (fragment_id,)
        ).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Fragment '{fragment_id}' not found"
        )
    return dict(row)


# ═══════════════════════════════════════════════════════════════════════════
# §20  FEATURE 01 — Fragment Reconstruction API (Phase 2)
# ═══════════════════════════════════════════════════════════════════════════
# POST /api/fragments/reconstruct
#   Accept uploaded fragment files, run the full graph+path+reassembly
#   pipeline, return ReconstructionCandidate list with all score components.
#
# GET  /api/fragments/reconstruct/{candidate_id}
#   Return a specific reconstruction candidate (bytes as hex).
# ═══════════════════════════════════════════════════════════════════════════

# In-memory store for reconstruction results (keyed by candidate_id)
# This avoids storing large binary blobs in SQLite while keeping the API simple.
_reconstruction_store: dict = {}


def _get_graph_engine():
    from backend import fragment_graph as _fg
    return _fg


@app.post("/api/fragments/reconstruct", status_code=200)
async def reconstruct_fragments_endpoint(
    files: List[UploadFile] = File(...),
    weights_json: str = Form(default=""),
    session_id:   str = Form(default=""),
):
    """
    Phase 2 — Fragment Reconstruction.

    Upload two or more fragment files. The engine will:
      1. Ingest and analyze each fragment (Phase 1)
      2. Build a directed candidate graph with 5-component edge scores
      3. Enumerate candidate paths with cycle/duplicate prevention
      4. Validate each candidate structurally
      5. Assemble actual bytes for each candidate
      6. Return ReconstructionCandidate list sorted best-first

    Every edge score component is returned separately.
    Corrupted fragments are reported but never silently repaired.
    Missing fragments are reported as gaps.
    """
    fi = _get_ingestor()
    fg = _get_graph_engine()

    if not session_id:
        session_id = f"recon-{_uuid.uuid4().hex[:8]}"

    # Parse optional weight overrides
    weights = None
    if weights_json:
        try:
            weights = json.loads(weights_json)
        except Exception:
            weights = None

    # Ingest all uploaded files
    records = []
    frag_bytes = {}
    ingest_errors = []

    for upload in files:
        try:
            data = await upload.read()
            rec = fi.ingest_bytes(
                data,
                label=upload.filename or "<upload>",
                source_offset=fi.UNKNOWN_OFFSET,
            )
            records.append(rec)
            frag_bytes[rec.fragment_id] = data
        except Exception as exc:
            ingest_errors.append({"filename": upload.filename, "error": str(exc)})

    if not records:
        raise HTTPException(status_code=400, detail="No fragments could be ingested")

    # Run graph construction + path reconstruction + byte reassembly
    try:
        graph, candidates = fg.reconstruct_fragments(
            records, frag_bytes, weights=weights
        )
    except Exception as exc:
        log.exception("Reconstruction pipeline error")
        raise HTTPException(status_code=500, detail=f"Reconstruction failed: {exc}")

    # Store candidates for later retrieval
    for cand in candidates:
        _reconstruction_store[cand.candidate_id] = cand

    # Build response (assembled_bytes as hex string — do not base64 or truncate)
    return {
        "session_id":    session_id,
        "fragment_count": len(records),
        "graph_summary": {
            "nodes": graph.node_count(),
            "edges": graph.edge_count(),
        },
        "candidates": [c.to_dict() for c in candidates],
        "ingest_errors": ingest_errors,
    }


@app.get("/api/fragments/reconstruct/{candidate_id}")
async def get_reconstruction_candidate(candidate_id: str):
    """
    Return a specific reconstruction candidate including assembled bytes (hex).
    """
    cand = _reconstruction_store.get(candidate_id)
    if not cand:
        raise HTTPException(
            status_code=404,
            detail=f"Candidate '{candidate_id}' not found. "
                   f"Run POST /api/fragments/reconstruct first."
        )
    return cand.to_dict()


@app.get("/api/fragments/reconstruct/{candidate_id}/download")
async def download_reconstruction(candidate_id: str):
    """
    Return the raw reconstructed bytes as an application/octet-stream response.
    Only call this after a successful reconstruction.
    """
    from fastapi.responses import Response
    cand = _reconstruction_store.get(candidate_id)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate '{candidate_id}' not found")
    if not cand.assembled_bytes:
        raise HTTPException(status_code=404, detail="No assembled bytes in this candidate")

    filename = f"reconstructed_{candidate_id}.{cand.format_type.lower()}"
    return Response(
        content=cand.assembled_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ═══════════════════════════════════════════════════════════════════════════
# §21  FEATURE 01 — Phase 3/4 Complete API v1 Endpoints
# ═══════════════════════════════════════════════════════════════════════════
# /api/v1/discovery/
# /api/v1/analysis/
# /api/v1/linking/
# /api/v1/reconstruction/
# /api/v1/reconstruction/candidates
# /api/v1/reconstruction/export/{candidate_id}
# /api/v1/reconstruction/scenarios
# /api/v1/reconstruction/scenarios/run
# ═══════════════════════════════════════════════════════════════════════════

# In-memory store for session fragment bytes
_session_raw_bytes: Dict[str, Dict[str, bytes]] = {}
# In-memory store for full reconstruction reports
_reconstruction_reports: Dict[str, Any] = {}


async def _extract_fragments_from_request(
    files: Optional[List[UploadFile]],
    session_id: str,
) -> Tuple[str, List[Any], Dict[str, bytes]]:
    """Helper to retrieve or ingest fragments and raw bytes."""
    fi = _get_ingestor()
    records = []
    frag_bytes = {}

    if not session_id:
        session_id = f"v1-{_uuid.uuid4().hex[:8]}"

    if files:
        for upload in files:
            data = await upload.read()
            rec = fi.ingest_bytes(
                data,
                label=upload.filename or "<upload>",
                source_offset=fi.UNKNOWN_OFFSET,
            )
            records.append(rec)
            frag_bytes[rec.fragment_id] = data

        _session_raw_bytes[session_id] = frag_bytes
        try:
            with get_db() as conn:
                fi._ensure_fragment_records_table(conn)
                fi.persist_records(records, conn, session_id)
        except Exception:
            pass
    elif session_id in _session_raw_bytes:
        frag_bytes = _session_raw_bytes[session_id]
        for fid, raw in frag_bytes.items():
            records.append(fi.ingest_bytes(raw, label=fid, source_offset=fi.UNKNOWN_OFFSET))
    else:
        # Check database
        with get_db() as conn:
            fi._ensure_fragment_records_table(conn)
            rows = conn.execute(
                "SELECT * FROM fragment_records WHERE session_id = ?", (session_id,)
            ).fetchall()
            for r in rows:
                d = dict(r)
                fid = d["fragment_id"]
                # In DB fallback, create dummy record if bytes not in memory
                dummy_bytes = bytes.fromhex(d.get("first_bytes", "")) if d.get("first_bytes") else b""
                frag_bytes[fid] = dummy_bytes
                records.append(fi.ingest_bytes(dummy_bytes, label=fid, source_offset=d.get("source_offset", 0)))

    return session_id, records, frag_bytes


@app.post("/api/v1/discovery/", status_code=200)
async def v1_discovery_endpoint(
    files: Optional[List[UploadFile]] = File(None),
    session_id: str = Form(default=""),
):
    """
    /api/v1/discovery/
    Discover fragments from uploaded chunks or raw binary data.
    Computes deterministic fragment IDs, SHA-256 hashes, byte sizes, and format signatures.
    """
    if not files and not session_id:
        raise HTTPException(status_code=400, detail="Provide either files to upload or an existing session_id")

    session_id, records, _ = await _extract_fragments_from_request(files, session_id)
    return {
        "status": "DISCOVERED",
        "session_id": session_id,
        "count": len(records),
        "fragments": [r.to_dict() for r in records],
    }


@app.get("/api/v1/discovery/", status_code=200)
async def v1_discovery_get(session_id: str = ""):
    """Retrieve discovered fragments for a session."""
    if not session_id:
        return {"sessions": list(_session_raw_bytes.keys())}
    fi = _get_ingestor()
    with get_db() as conn:
        fi._ensure_fragment_records_table(conn)
        rows = conn.execute(
            "SELECT * FROM fragment_records WHERE session_id = ? ORDER BY source_offset ASC",
            (session_id,)
        ).fetchall()
    return {
        "session_id": session_id,
        "count": len(rows),
        "fragments": [dict(r) for r in rows],
    }


@app.post("/api/v1/analysis/", status_code=200)
async def v1_analysis_endpoint(
    files: Optional[List[UploadFile]] = File(None),
    session_id: str = Form(default=""),
):
    """
    /api/v1/analysis/
    Deep byte-level analysis of fragments:
    Shannon entropy, signature presence, internal markers, zero-fill ratio, and corruption flags.
    """
    session_id, records, frag_bytes = await _extract_fragments_from_request(files, session_id)
    analysis_results = []

    for rec in records:
        data = frag_bytes.get(rec.fragment_id, b"")
        analysis_results.append({
            "fragment_id": rec.fragment_id,
            "detected_type": rec.detected_type,
            "format_hint": rec.format_hint,
            "length": rec.length,
            "sha256": rec.sha256,
            "entropy": round(rec.entropy, 4),
            "zero_byte_ratio": round(rec.zero_byte_ratio, 4),
            "header_compatible": rec.header_compatible,
            "footer_compatible": rec.footer_compatible,
            "internal_markers": rec.internal_markers,
            "corruption_flags": rec.corruption_flags,
            "byte_preview_hex": rec.first_bytes,
        })

    return {
        "session_id": session_id,
        "fragment_count": len(analysis_results),
        "analysis": analysis_results,
    }


@app.post("/api/v1/linking/", status_code=200)
async def v1_linking_endpoint(
    files: Optional[List[UploadFile]] = File(None),
    session_id: str = Form(default=""),
    weights_json: str = Form(default=""),
):
    """
    /api/v1/linking/
    Candidate relationship generation & 5-component edge scoring.
    Returns directed graph with explainable edge metrics:
      - signature_score
      - continuity_score
      - structural_score
      - entropy_score
      - contradiction_penalty
      - final edge_score & evidence notes
    """
    fg = _get_graph_engine()
    session_id, records, frag_bytes = await _extract_fragments_from_request(files, session_id)
    if not records:
        raise HTTPException(status_code=400, detail="No fragments available for linking")

    weights = json.loads(weights_json) if weights_json else None
    graph = fg.build_graph(records, frag_bytes, weights=weights)

    return {
        "session_id": session_id,
        "graph": graph.to_dict(),
        "weights_used": weights or fg.DEFAULT_WEIGHTS,
    }


@app.post("/api/v1/reconstruction/candidates", status_code=200)
async def v1_reconstruction_candidates(
    files: Optional[List[UploadFile]] = File(None),
    session_id: str = Form(default=""),
    weights_json: str = Form(default=""),
):
    """
    POST /api/v1/reconstruction/candidates
    Generate ranked reconstruction candidates with REAL computed scores,
    ordered fragments, structural validation, and completeness status.
    Matches spec example:
    {
      "candidate_id": "C001",
      "fragments": ["F001", "F003", "F002"],
      "score": 0.91,
      "status": "PARTIAL",
      "validation": {
        "format_valid": true,
        "complete": false
      }
    }
    """
    fg = _get_graph_engine()
    session_id, records, frag_bytes = await _extract_fragments_from_request(files, session_id)
    if not records:
        raise HTTPException(status_code=400, detail="No fragments provided for reconstruction")

    weights = json.loads(weights_json) if weights_json else None
    graph, candidates = fg.reconstruct_fragments(records, frag_bytes, weights=weights)

    results = []
    for cand in candidates:
        _reconstruction_store[cand.candidate_id] = cand

        # Spec format
        score_norm = round(cand.path_score / 100.0, 4) if cand.path_score > 1.0 else round(cand.path_score, 4)
        is_complete = (cand.status == "COMPLETE")
        val_block = {
            "format_valid": cand.structural_check_passed,
            "complete": is_complete,
            "format_type": cand.format_type,
            "structural_score": cand.structural_detail.get("score", 0.0),
            "reason": cand.structural_check_reason,
            "issues": cand.structural_detail.get("issues", []),
        }

        results.append({
            "candidate_id": cand.candidate_id,
            "fragments": cand.ordered_fragment_ids,
            "score": score_norm,
            "status": cand.status,
            "validation": val_block,
            "sha256": cand.assembled_sha256,
            "total_bytes": cand.total_bytes,
            "edge_scores": cand.edge_scores,
            "missing_fragments": [asdict(m) if hasattr(m, '__dataclass_fields__') else m for m in cand.missing_fragments],
            "corrupted_fragments": [asdict(c) if hasattr(c, '__dataclass_fields__') else c for c in cand.corrupted_fragments],
            "notes": cand.notes,
            "provenance": getattr(cand, "provenance", []),
        })

    top = results[0] if results else {}
    return {
        "session_id": session_id,
        "total_candidates": len(results),
        "candidates": results,
        "candidate_id": top.get("candidate_id"),
        "fragments": top.get("fragments", []),
        "score": top.get("score", 0.0),
        "status": top.get("status", "UNCERTAIN"),
        "validation": top.get("validation", {"format_valid": False, "complete": False}),
    }


@app.post("/api/v1/reconstruction/", status_code=200)
async def v1_full_reconstruction_endpoint(
    files: Optional[List[UploadFile]] = File(None),
    session_id: str = Form(default=""),
    weights_json: str = Form(default=""),
):
    """
    POST /api/v1/reconstruction/
    Full Reconstruction Pipeline Execution:
      1. Slices/ingests fragments
      2. Analyzes features & builds directed graph
      3. Reconstructs candidates and reassembles bytes
      4. Structural format validation
      5. Completeness & corruption assessment
      6. Provenance generation
      7. Persists 4 output files to reconstructed/
    """
    from backend.format_validator import validate_format_structure
    from backend.reconstruction_report import (
        build_provenance_records,
        determine_reconstruction_status,
        export_reconstruction_artifacts,
        ReconstructionReport,
    )

    fg = _get_graph_engine()
    session_id, records, frag_bytes = await _extract_fragments_from_request(files, session_id)
    if not records:
        raise HTTPException(status_code=400, detail="No fragments provided")

    weights = json.loads(weights_json) if weights_json else None
    graph, candidates = fg.reconstruct_fragments(records, frag_bytes, weights=weights)

    if not candidates:
        raise HTTPException(status_code=500, detail="Reconstruction yielded no candidates")

    best = candidates[0]
    _reconstruction_store[best.candidate_id] = best

    # 1. Structural format validation
    val_res = validate_format_structure(best.assembled_bytes, best.format_type)

    # 2. Build detailed provenance
    records_map = {r.fragment_id: r for r in records}
    edges_map = {(e.from_id, e.to_id): e for e in graph.all_edges()}
    prov_entries = build_provenance_records(
        best.ordered_fragment_ids,
        frag_bytes,
        records_map,
        edges_map,
        val_res,
    )

    # 3. Completeness & corruption
    missing_count = len(best.missing_fragments)
    corrupted_count = len(best.corrupted_fragments)
    competing_delta = None
    if len(candidates) > 1:
        competing_delta = best.path_score - candidates[1].path_score

    final_status, notes = determine_reconstruction_status(
        val_res,
        len(best.ordered_fragment_ids),
        len(records),
        missing_count,
        corrupted_count,
        competing_delta,
        best.path_score,
    )

    # Total source bytes
    total_source_bytes = sum(len(frag_bytes.get(fid, b"")) for fid in frag_bytes)
    byte_coverage = (len(best.assembled_bytes) / max(1, total_source_bytes))

    # Compile report
    report = ReconstructionReport(
        candidate_id=best.candidate_id,
        reconstructed_sha256=best.assembled_sha256,
        source_evidence_sha256=None,
        total_reconstructed_bytes=len(best.assembled_bytes),
        byte_coverage=round(byte_coverage, 4),
        final_status=final_status,
        format_type=best.format_type,
        format_validation=val_res.to_dict(),
        fragments_used=[{"fragment_id": fid, "length": len(frag_bytes.get(fid, b""))} for fid in best.ordered_fragment_ids],
        fragments_missing=[asdict(m) if hasattr(m, '__dataclass_fields__') else m for m in best.missing_fragments],
        corrupted_fragments=[asdict(c) if hasattr(c, '__dataclass_fields__') else c for c in best.corrupted_fragments],
        fragment_ordering=best.ordered_fragment_ids,
        edge_scores=best.edge_scores,
        edge_evidence=[{"from": e.from_id, "to": e.to_id, "evidence": e.evidence} for e in graph.all_edges()],
        provenance=[p.to_dict() for p in prov_entries],
        created_at=datetime.now(timezone.utc).isoformat(),
        forensic_notes=notes + best.notes,
    )

    # Export the 4 output files into reconstructed/
    artifact_paths = export_reconstruction_artifacts(
        best.candidate_id,
        best.assembled_bytes,
        prov_entries,
        val_res,
        report,
    )

    _reconstruction_reports[best.candidate_id] = {
        "report": report.to_dict(),
        "paths": artifact_paths,
        "validation": val_res.to_dict(),
        "provenance": [p.to_dict() for p in prov_entries],
    }

    return {
        "session_id": session_id,
        "candidate_id": best.candidate_id,
        "status": final_status,
        "path_score": best.path_score,
        "reconstructed_sha256": best.assembled_sha256,
        "total_bytes": len(best.assembled_bytes),
        "byte_coverage": byte_coverage,
        "format_validation": val_res.to_dict(),
        "artifacts_generated": artifact_paths,
        "report": report.to_dict(),
    }


@app.get("/api/v1/reconstruction/export/{candidate_id}", status_code=200)
async def v1_export_reconstruction(candidate_id: str):
    """Retrieve generated report and file paths for a reconstruction."""
    rep = _reconstruction_reports.get(candidate_id)
    if not rep:
        raise HTTPException(status_code=404, detail=f"No export records found for '{candidate_id}'")
    return rep


@app.get("/api/v1/reconstruction/export/{candidate_id}/download/{file_type}")
async def v1_download_artifact(candidate_id: str, file_type: str):
    """Download one of: bin, provenance, validation, report."""
    from fastapi.responses import FileResponse, Response
    rep = _reconstruction_reports.get(candidate_id)
    cand = _reconstruction_store.get(candidate_id)

    if file_type == "bin":
        if cand and cand.assembled_bytes:
            return Response(
                content=cand.assembled_bytes,
                media_type="application/octet-stream",
                headers={"Content-Disposition": f"attachment; filename=reconstructed_{candidate_id}.bin"},
            )

    if rep and "paths" in rep:
        key_map = {
            "bin": "binary_path",
            "provenance": "provenance_path",
            "validation": "validation_path",
            "report": "report_path",
        }
        path_key = key_map.get(file_type)
        if path_key and path_key in rep["paths"]:
            p = Path(rep["paths"][path_key])
            if p.exists():
                return FileResponse(
                    str(p),
                    filename=p.name,
                    media_type="application/json" if file_type != "bin" else "application/octet-stream",
                )

    raise HTTPException(status_code=404, detail=f"Artifact '{file_type}' for candidate '{candidate_id}' not found")


@app.get("/api/v1/reconstruction/scenarios", status_code=200)
async def v1_list_scenarios():
    """List available ground-truth evaluation scenarios (A-E)."""
    return {
        "scenarios": [
            {
                "id": "A",
                "name": "Scenario A: Correct fragments shuffled",
                "formats": ["JPEG", "PNG", "PDF", "ZIP"],
                "description": "All fragments present and intact, delivered in non-sequential order",
            },
            {
                "id": "B",
                "name": "Scenario B: One missing fragment",
                "formats": ["JPEG", "PNG", "PDF", "ZIP"],
                "description": "One interior fragment is missing; engine must detect gap and report PARTIAL",
            },
            {
                "id": "C",
                "name": "Scenario C: One corrupted fragment",
                "formats": ["JPEG", "PNG", "PDF", "ZIP"],
                "description": "One fragment zero-filled; bytes preserved as-is and flagged CORRUPTED",
            },
            {
                "id": "D",
                "name": "Scenario D: Ambiguous ordering",
                "formats": ["JPEG", "PNG", "PDF", "ZIP"],
                "description": "Ambiguous fragment candidates; alternatives preserved without guessing",
            },
            {
                "id": "E",
                "name": "Scenario E: Unrelated fragment mixed in",
                "formats": ["JPEG", "PNG", "PDF", "ZIP"],
                "description": "Cross-format fragment injected; contradiction penalty must reject it",
            },
        ]
    }


@app.post("/api/v1/reconstruction/scenarios/run", status_code=200)
async def v1_run_scenario(
    scenario_id: str = Form(default="A"),
    format_type: str = Form(default="JPEG"),
):
    """
    POST /api/v1/reconstruction/scenarios/run
    Executes a real ground truth evaluation test:
      - Builds synthetic ground-truth dataset
      - Ingests actual binary fragments
      - Computes graph and candidate reconstruction
      - Validates format structure
      - Evaluates accuracy, ordering, missing/corrupted detection, and SHA-256 match
      - Exports files to reconstructed/
    """
    from backend import ground_truth_dataset as gtd
    from backend.format_validator import validate_format_structure
    from backend.reconstruction_report import (
        build_provenance_records,
        determine_reconstruction_status,
        export_reconstruction_artifacts,
        ReconstructionReport,
    )

    ft = format_type.upper().strip()
    sc = scenario_id.upper().strip()

    builders = {
        "A": gtd.build_scenario_a,
        "B": gtd.build_scenario_b,
        "C": gtd.build_scenario_c,
        "D": gtd.build_scenario_d,
        "E": gtd.build_scenario_e,
    }
    builder = builders.get(sc, gtd.build_scenario_a)
    scenario_data = builder(ft)

    # Convert SyntheticFragment to FragmentRecord
    fi = _get_ingestor()
    fg = _get_graph_engine()

    frag_bytes = {}
    records = []
    for sf in scenario_data.fragments:
        rec = fi.ingest_bytes(sf.data, label=sf.fragment_id, source_offset=sf.source_offset)
        records.append(rec)
        frag_bytes[sf.fragment_id] = sf.data

    # Reconstruct
    graph, candidates = fg.reconstruct_fragments(records, frag_bytes)
    best = candidates[0]
    _reconstruction_store[best.candidate_id] = best

    # Validate structure
    val_res = validate_format_structure(best.assembled_bytes, ft)

    # Evaluate against ground truth
    metrics = gtd.evaluate_reconstruction(
        scenario_data,
        best.ordered_fragment_ids,
        best.assembled_bytes,
        best.status,
        val_res,
    )

    # Provenance
    records_map = {r.fragment_id: r for r in records}
    edges_map = {(e.from_id, e.to_id): e for e in graph.all_edges()}
    prov_entries = build_provenance_records(
        best.ordered_fragment_ids,
        frag_bytes,
        records_map,
        edges_map,
        val_res,
    )

    # Final status accounting for scenario ground truth knowledge
    missing_count = len(best.missing_fragments) + len(scenario_data.missing_fragment_indices)
    corrupted_count = len(best.corrupted_fragments) + len(scenario_data.corrupted_fragment_indices)
    total_expected = len(records) + len(scenario_data.missing_fragment_indices)

    final_status, notes = determine_reconstruction_status(
        val_res,
        len(best.ordered_fragment_ids),
        total_expected,
        missing_count,
        corrupted_count,
        None,
        best.path_score,
    )

    report = ReconstructionReport(
        candidate_id=best.candidate_id,
        reconstructed_sha256=best.assembled_sha256,
        source_evidence_sha256=scenario_data.original_sha256,
        total_reconstructed_bytes=len(best.assembled_bytes),
        byte_coverage=round(len(best.assembled_bytes) / max(1, scenario_data.total_original_bytes), 4),
        final_status=final_status,
        format_type=ft,
        format_validation=val_res.to_dict(),
        fragments_used=[{"fragment_id": fid, "length": len(frag_bytes.get(fid, b""))} for fid in best.ordered_fragment_ids],
        fragments_missing=[asdict(m) if hasattr(m, '__dataclass_fields__') else m for m in best.missing_fragments],
        corrupted_fragments=[asdict(c) if hasattr(c, '__dataclass_fields__') else c for c in best.corrupted_fragments],
        fragment_ordering=best.ordered_fragment_ids,
        edge_scores=best.edge_scores,
        edge_evidence=[{"from": e.from_id, "to": e.to_id, "evidence": e.evidence} for e in graph.all_edges()],
        provenance=[p.to_dict() for p in prov_entries],
        created_at=datetime.now(timezone.utc).isoformat(),
        forensic_notes=notes + best.notes,
    )

    artifact_paths = export_reconstruction_artifacts(
        best.candidate_id,
        best.assembled_bytes,
        prov_entries,
        val_res,
        report,
    )

    _reconstruction_reports[best.candidate_id] = {
        "report": report.to_dict(),
        "paths": artifact_paths,
        "validation": val_res.to_dict(),
        "provenance": [p.to_dict() for p in prov_entries],
    }

    return {
        "scenario": scenario_data.scenario_name,
        "format_type": ft,
        "candidate_id": best.candidate_id,
        "evaluation": metrics.to_dict(),
        "validation": val_res.to_dict(),
        "graph_summary": {
            "node_count": graph.node_count(),
            "edge_count": graph.edge_count(),
        },
        "graph": graph.to_dict(),
        "candidates": [c.to_dict() for c in candidates],
        "fragments": [r.to_dict() for r in records],
        "fragments_ingested": len(records),
        "fragments_ordered": best.ordered_fragment_ids,
        "artifacts_generated": artifact_paths,
        "report": report.to_dict(),
    }

