"""
SAMDHAN AI — Module 01: Intelligent Fragment Reconstruction
engine/fragment_reconstructor.py

Core engine implementing:
  1. Signature-driven header scan          (config/signatures.json)
  2. Contiguous carve with multi-footer    validation (footer-collision fix)
  3. Greedy best-first fragment stitching  (entropy + n-gram, not next-block)
  4. Format-specific structural validation (Pillow real-decode for images)
  5. Honest confidence scoring             (never a silent 100% guess)
  6. Chain-of-custody: source bytes never  mutated; every result carries SHA-256

See docs/DDR.md for full design rationale, formulas, and limitations.
"""

import hashlib
import json
import math
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import List, Optional, Set, Tuple

# ── Optional Pillow (used for real JPEG/PNG decode validation) ────────────────
try:
    from PIL import Image as _PilImage
    import io as _pil_io
    _PILLOW_AVAILABLE = True
except ImportError:
    _PILLOW_AVAILABLE = False


# ═════════════════════════════════════════════════════════════════════════════
# §1  CONSTANTS
# ═════════════════════════════════════════════════════════════════════════════

CHUNK_SIZE      = 4096   # Default candidate stride — typical filesystem cluster
MAX_JOINS       = 8      # Max greedy stitching steps per file
STITCH_THRESHOLD = 50.0  # Minimum composite score (0–100) to accept a candidate


# ═════════════════════════════════════════════════════════════════════════════
# §2  DATA MODEL
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class RecoveredFile:
    """
    One file recovered from raw source bytes by the engine.

    Confidence formula (DDR §2.3):
      • footer confirmed + structural pass  → 100.0
      • stitched, no confirmed footer       → mean(stitch_scores) − join_penalty
      • no continuation located             → 25.0  (explicitly unresolved)

    This ensures we NEVER conflate "we produced some bytes" with "we
    produced the correct file."
    """
    file_type:               str
    category:                str
    data:                    bytes
    offset:                  int          # byte offset of header in source image
    is_fragmented:           bool
    footer_confirmed:        bool
    stitch_scores:           List[float]
    structural_check_passed: bool
    structural_check_reason: str
    sha256:                  str = field(init=False)
    confidence:              float = field(init=False)

    def __post_init__(self):
        # Source bytes are never passed here — we compute from a copy of data.
        # This is the chain-of-custody boundary.
        self.sha256     = hashlib.sha256(self.data).hexdigest()
        self.confidence = self._compute_confidence()

    def _compute_confidence(self) -> float:
        if self.footer_confirmed and self.structural_check_passed:
            return 100.0
        if self.stitch_scores:
            avg     = mean(self.stitch_scores)
            penalty = min(15.0, 3.0 * (len(self.stitch_scores) - 1))
            return max(5.0, avg - penalty)
        return 25.0


# ═════════════════════════════════════════════════════════════════════════════
# §3  SIGNATURE LOADING
# ═════════════════════════════════════════════════════════════════════════════

def load_signatures(config_path: str) -> List[dict]:
    """
    Parse config/signatures.json and precompute byte objects.
    Design intent: adding a new format requires only editing the JSON file.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    sigs = []
    for s in raw:
        sig = dict(s)
        sig["_header_bytes"] = bytes.fromhex(s["header"])
        sig["_footer_bytes"] = bytes.fromhex(s["footer"]) if s.get("footer") else None
        sig["_max_bytes"]    = int(s.get("max_size_mb", 50) * 1024 * 1024)
        sigs.append(sig)
    return sigs


# ═════════════════════════════════════════════════════════════════════════════
# §4  SCORING FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

def shannon_entropy(chunk: bytes) -> float:
    """
    Shannon entropy in bits/byte, range [0, 8].
      0 → uniform repetition (e.g. zero-fill, constant pattern)
      8 → maximal randomness (e.g. encrypted/compressed data)
    """
    if not chunk:
        return 0.0
    freq = [0] * 256
    for b in chunk:
        freq[b] += 1
    n = len(chunk)
    return -sum((c / n) * math.log2(c / n) for c in freq if c > 0)


def entropy_continuity_score(tail: bytes, head: bytes, window: int = 256) -> float:
    """
    Score 0–100 based on the entropy delta across a proposed fragment join.

    Formula (DDR §2.2):
        delta = |entropy(tail[-window:]) − entropy(head[:window])|
        score = max(0, 100 − (delta / 3.0) × 100)

    Rationale: legitimate content (e.g. consecutive JPEG scan data) shows
    smooth entropy transitions across true fragment boundaries; an unrelated
    block typically shows a much larger jump. The divisor 3.0 was chosen so
    that a full jump from text-like (~4.5 bits/byte) to compressed/random
    (~7.9 bits/byte) — delta ≈ 3.4 — scores near zero.
    """
    t_win = tail[-window:] if len(tail) >= window else tail
    h_win = head[:window]  if len(head) >= window else head
    delta = abs(shannon_entropy(t_win) - shannon_entropy(h_win))
    return max(0.0, 100.0 - (delta / 3.0) * 100.0)


def ngram_affinity_score(tail: bytes, head: bytes, n: int = 4, window: int = 128) -> float:
    """
    Score 0–100 based on shared n-gram overlap between tail and head windows.

    Formula (DDR §2.2):
        overlap_ratio = |shared 4-grams| / min(|tail 4-grams|, |head 4-grams|)
        score = min(100, overlap_ratio × 400)

    Rationale: n-gram overlap between genuinely related binary content is
    naturally sparse (unlike text); the ×400 scaling ensures a true
    continuation scores meaningfully above an unrelated block.
    """
    t = tail[-window:] if len(tail) >= window else tail
    h = head[:window]  if len(head) >= window else head
    if len(t) < n or len(h) < n:
        return 0.0
    t_grams = {t[i:i + n] for i in range(len(t) - n + 1)}
    h_grams = {h[i:i + n] for i in range(len(h) - n + 1)}
    if not t_grams or not h_grams:
        return 0.0
    overlap = len(t_grams & h_grams)
    ratio   = overlap / min(len(t_grams), len(h_grams))
    return min(100.0, ratio * 400.0)


def stitch_score(tail: bytes, head: bytes) -> float:
    """
    Composite stitching score 0–100 (DDR §2.2):
        score = 0.6 × entropy_continuity + 0.4 × ngram_affinity

    Weighted toward entropy continuity because it is format-agnostic and
    stable; n-gram affinity acts as a tie-breaker.
    """
    ec = entropy_continuity_score(tail, head)
    ng = ngram_affinity_score(tail, head)
    return 0.6 * ec + 0.4 * ng


# ═════════════════════════════════════════════════════════════════════════════
# §5  STRUCTURAL VALIDATORS
# ═════════════════════════════════════════════════════════════════════════════

def structural_check(file_type: str, data: bytes) -> Tuple[bool, str]:
    """
    Format-specific structural validation.

    Returns (passed: bool, reason: str).
    NEVER returns a bare True/False — the reason string is surfaced directly
    to the investigator in the JSON report.

    JPEG/PNG use a real Pillow decode attempt (when available) in addition to
    byte-marker checks. This is what catches "footer collision" false positives
    where random noise coincidentally contains a footer-like byte sequence.
    """
    ft = file_type.upper()

    # ── JPEG ──────────────────────────────────────────────────────────────────
    if ft == "JPEG":
        if data[:2] != b"\xff\xd8":
            return False, "Missing JPEG SOI marker (FFD8)"
        if b"\xff\xd9" not in data[-4:]:
            return False, "Missing JPEG EOI marker (FFD9) in final 4 bytes"
        if _PILLOW_AVAILABLE:
            try:
                img = _PilImage.open(_pil_io.BytesIO(data))
                img.verify()
                return True, "JPEG: SOI+EOI present; Pillow decode passed"
            except Exception as e:
                return False, f"JPEG: Pillow decode failed — {e}"
        return True, "JPEG: SOI+EOI markers present (Pillow not installed — deep decode skipped)"

    # ── PNG ───────────────────────────────────────────────────────────────────
    if ft == "PNG":
        PNG_SIG = b"\x89PNG\r\n\x1a\n"
        if data[:8] != PNG_SIG:
            return False, "Missing PNG 8-byte signature"
        if b"IEND" not in data[-16:]:
            return False, "Missing PNG IEND chunk"
        if _PILLOW_AVAILABLE:
            try:
                img = _PilImage.open(_pil_io.BytesIO(data))
                img.verify()
                return True, "PNG: signature+IEND present; Pillow decode passed"
            except Exception as e:
                return False, f"PNG: Pillow decode failed — {e}"
        return True, "PNG: signature and IEND chunk present"

    # ── PDF ───────────────────────────────────────────────────────────────────
    if ft == "PDF":
        if data[:4] != b"%PDF":
            return False, "Missing %PDF header"
        if b"%%EOF" not in data[-64:]:
            return False, "Missing %%EOF trailer (searched last 64 bytes)"
        return True, "PDF: %PDF header and %%EOF trailer present"

    # ── ZIP / OOXML (DOCX / XLSX / PPTX) ─────────────────────────────────────
    if ft in ("ZIP", "DOCX", "XLSX", "PPTX"):
        if data[:4] != b"PK\x03\x04":
            return False, "Missing ZIP local-file header (PK\\x03\\x04)"
        # EOCD can have a variable-length comment; search broadly
        if b"PK\x05\x06" not in data:
            return False, "Missing ZIP End-of-Central-Directory (PK\\x05\\x06)"
        return True, "ZIP/OOXML: local-file header and EOCD record both present"

    # ── SQLite ────────────────────────────────────────────────────────────────
    if ft == "SQLITE":
        MAGIC = b"SQLite format 3\x00"
        if data[:16] != MAGIC:
            return False, "Missing SQLite 3 header magic (first 16 bytes)"
        if len(data) < 100:
            return False, f"Too short for SQLite header: {len(data)} bytes (need ≥100)"
        return True, "SQLite: 16-byte magic string present, length ≥ 100 bytes"

    # ── PCAP (libpcap LE) ────────────────────────────────────────────────────
    if ft == "PCAP":
        if data[:4] not in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4"):
            return False, "Missing libpcap magic bytes"
        if len(data) < 24:
            return False, "Too short for libpcap global header"
        return True, "PCAP: magic bytes and global header present"

    # ── EVTX ────────────────────────────────────────────────────────────────
    if ft == "EVTX":
        if data[:8] != b"ElfFile\x00":
            return False, "Missing EVTX ElfFile signature"
        return True, "EVTX: ElfFile signature present"

    # ── Unknown / no validator ───────────────────────────────────────────────
    return True, f"No structural validator registered for '{file_type}' — accepted without format check"


# ═════════════════════════════════════════════════════════════════════════════
# §6  INTERNAL HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _find_all(source: bytes, pattern: bytes) -> List[int]:
    """Return byte offsets of every non-overlapping occurrence of pattern in source."""
    offsets, start = [], 0
    while True:
        idx = source.find(pattern, start)
        if idx == -1:
            break
        offsets.append(idx)
        start = idx + 1
    return offsets


def _build_candidate_pool(
    source:       bytes,
    exclude:      Set[int],
    chunk_size:   int = CHUNK_SIZE,
) -> List[int]:
    """
    Every chunk-aligned offset in source that is NOT in the exclude set.

    KEY DESIGN DECISION (DDR §2.2, _stitch_fragmented §2):
    We build from ALL unallocated chunk-aligned offsets, not just the
    immediately-next sequential block. Assuming next = continuation is
    *undelete*, not reconstruction of a *scattered* file.
    """
    return sorted(
        off for off in range(0, len(source) - chunk_size + 1, chunk_size)
        if off not in exclude
    )


# ═════════════════════════════════════════════════════════════════════════════
# §7  FRAGMENT STITCHING
# ═════════════════════════════════════════════════════════════════════════════

def _stitch_fragmented(
    source:      bytes,
    sig:         dict,
    header_pos:  int,
    used_offsets: Set[int],
    chunk_size:  int   = CHUNK_SIZE,
    max_joins:   int   = MAX_JOINS,
    threshold:   float = STITCH_THRESHOLD,
) -> RecoveredFile:
    """
    Greedy best-first fragment stitching (DDR §2.2, _stitch_fragmented).

    1. Start with the cluster at header_pos.
    2. Build the full candidate pool (ALL unused chunk-aligned offsets).
    3. At each step: score every remaining candidate against the current tail,
       append the highest-scoring one if it exceeds threshold.
    4. If footer appears in the accumulated chain: truncate and structural-check.
    5. Halt at max_joins or when no candidate exceeds threshold.
    """
    footer_bytes  = sig["_footer_bytes"]
    file_type     = sig["type"]
    category      = sig["category"]

    # ── Initialise chain with first cluster at header ─────────────────────
    first_chunk   = source[header_pos : header_pos + chunk_size]
    chain         = [first_chunk]
    stitch_log:   List[float] = []
    footer_confirmed = False

    def _make_result(assembled: bytes, footer_ok: bool, scores: List[float], frag: bool) -> RecoveredFile:
        passed, reason = structural_check(file_type, assembled)
        return RecoveredFile(
            file_type=file_type, category=category,
            data=assembled, offset=header_pos,
            is_fragmented=frag, footer_confirmed=footer_ok,
            stitch_scores=scores,
            structural_check_passed=passed, structural_check_reason=reason,
        )

    # ── Quick check: footer already in first chunk ────────────────────────
    if footer_bytes and footer_bytes in first_chunk:
        end_idx   = first_chunk.index(footer_bytes) + len(footer_bytes)
        candidate = first_chunk[:end_idx]
        passed, reason = structural_check(file_type, candidate)
        return RecoveredFile(
            file_type=file_type, category=category,
            data=candidate, offset=header_pos,
            is_fragmented=False, footer_confirmed=passed,
            stitch_scores=[],
            structural_check_passed=passed, structural_check_reason=reason,
        )

    # ── Build candidate pool ───────────────────────────────────────────────
    excluded = used_offsets | {header_pos}
    candidate_pool = _build_candidate_pool(source, excluded, chunk_size)

    for _join in range(max_joins):
        assembled_so_far = b"".join(chain)

        if not candidate_pool:
            break

        # Score every remaining candidate against the tail of the current chain
        scored = []
        for cand_off in candidate_pool:
            cand_chunk = source[cand_off : cand_off + chunk_size]
            if not cand_chunk:
                continue
            sc = stitch_score(assembled_so_far, cand_chunk)
            scored.append((sc, cand_off, cand_chunk))

        if not scored:
            break

        scored.sort(key=lambda x: -x[0])
        best_score, best_off, best_chunk = scored[0]

        if best_score < threshold:
            # No plausible continuation — halt stitching
            break

        stitch_log.append(best_score)
        chain.append(best_chunk)
        candidate_pool.remove(best_off)

        # ── Check if the footer now appears in the accumulated chain ───────
        assembled = b"".join(chain)
        if footer_bytes and footer_bytes in assembled:
            end_idx   = assembled.index(footer_bytes) + len(footer_bytes)
            truncated = assembled[:end_idx]
            passed, reason = structural_check(file_type, truncated)
            return RecoveredFile(
                file_type=file_type, category=category,
                data=truncated, offset=header_pos,
                is_fragmented=True, footer_confirmed=passed,
                stitch_scores=stitch_log,
                structural_check_passed=passed, structural_check_reason=reason,
            )

    # ── Footer never located — return what we have with explicit low confidence
    assembled = b"".join(chain)
    passed, reason = structural_check(file_type, assembled)
    return RecoveredFile(
        file_type=file_type, category=category,
        data=assembled, offset=header_pos,
        is_fragmented=True, footer_confirmed=False,
        stitch_scores=stitch_log,
        structural_check_passed=passed,
        structural_check_reason=reason + " [WARNING: footer not located — low confidence]",
    )


# ═════════════════════════════════════════════════════════════════════════════
# §8  CONTIGUOUS CARVE
# ═════════════════════════════════════════════════════════════════════════════

def _carve_one(
    source:       bytes,
    sig:          dict,
    header_pos:   int,
    used_offsets: Set[int],
) -> Optional[RecoveredFile]:
    """
    Attempt to carve one file starting at header_pos.

    Fast path (DDR §2.2, _carve_one):
      Iterate every footer occurrence within max_size_mb in order.
      For EACH occurrence run structural_check — do NOT accept the first
      byte-match blindly (this catches "footer collision" false positives
      where random noise coincidentally matches the footer pattern but the
      assembled blob is structurally invalid).

    Fallback: _stitch_fragmented().
    """
    footer_bytes = sig["_footer_bytes"]
    file_type    = sig["type"]
    category     = sig["category"]
    max_bytes    = sig["_max_bytes"]

    # ── Contiguous fast path ──────────────────────────────────────────────
    if footer_bytes:
        search_window  = source[header_pos : header_pos + max_bytes]
        footer_offsets = _find_all(search_window, footer_bytes)
        footer_len     = len(footer_bytes)

        for rel_off in footer_offsets:
            end       = header_pos + rel_off + footer_len
            candidate = source[header_pos:end]
            passed, reason = structural_check(file_type, candidate)
            if passed:
                return RecoveredFile(
                    file_type=file_type, category=category,
                    data=candidate, offset=header_pos,
                    is_fragmented=False, footer_confirmed=True,
                    stitch_scores=[],
                    structural_check_passed=True, structural_check_reason=reason,
                )
            # Footer collision — this footer occurrence is invalid; try the next one.

    # ── Fragmented stitching fallback ─────────────────────────────────────
    return _stitch_fragmented(source, sig, header_pos, used_offsets)


# ═════════════════════════════════════════════════════════════════════════════
# §9  MAIN SCANNER
# ═════════════════════════════════════════════════════════════════════════════

class FragmentReconstructor:
    """
    Scan raw source bytes for every recoverable file using the configured
    signature database.

    Chain-of-custody guarantees (DDR §3):
      • source bytes are NEVER mutated (read via slicing only).
      • all mutation happens on copies inside RecoveredFile.data.
      • every result carries a SHA-256 computed from the recovered bytes,
        enabling independent re-verification against the same image.
    """

    def __init__(self, config_path: str):
        self.signatures = load_signatures(config_path)

    def scan(self, source: bytes) -> List[RecoveredFile]:
        """
        Find and return every recoverable file in source.
        Results are sorted by confidence (descending).
        """
        results: List[RecoveredFile] = []
        used_offsets: Set[int]       = set()   # chunk-aligned offsets already claimed

        for sig in self.signatures:
            header_bytes  = sig["_header_bytes"]
            header_offset = sig.get("header_offset", 0)

            header_positions = _find_all(source, header_bytes)

            for raw_pos in header_positions:
                actual_start = raw_pos - header_offset
                if actual_start < 0:
                    continue
                # Skip if the first cluster of this file was already claimed
                first_cluster = (actual_start // CHUNK_SIZE) * CHUNK_SIZE
                if first_cluster in used_offsets:
                    continue

                result = _carve_one(source, sig, actual_start, used_offsets)
                if result is None:
                    continue

                results.append(result)

                # Mark every chunk-aligned block covered by this result as used
                for off in range(actual_start,
                                 actual_start + len(result.data),
                                 CHUNK_SIZE):
                    used_offsets.add(off)

        results.sort(key=lambda r: r.confidence, reverse=True)
        return results


# ═════════════════════════════════════════════════════════════════════════════
# §10 PUBLIC API
# ═════════════════════════════════════════════════════════════════════════════

def reconstruct(source_bytes: bytes, config_path: str) -> List[RecoveredFile]:
    """
    Main entry point.

    Args:
        source_bytes: raw bytes of disk image / pendrive dump / unallocated space.
        config_path:  path to config/signatures.json.

    Returns:
        List[RecoveredFile] sorted by reconstruction_confidence (descending).

    Recommended workflow (DDR §3):
        1. dd / ddrescue the physical media to an image file.
        2. SHA-256 the image immediately after imaging.
        3. Pass the image bytes to this function — never the original media.
    """
    return FragmentReconstructor(config_path).scan(source_bytes)


def summarize(results: List[RecoveredFile]) -> List[str]:
    """
    Return human-readable summary lines for a list of RecoveredFile objects.
    """
    lines = []
    for i, r in enumerate(results, 1):
        status = "PASS ✓" if r.structural_check_passed else "FAIL ✗"
        mode   = "FRAGMENTED" if r.is_fragmented else "CONTIGUOUS"
        lines.append(
            f"[{i}] {r.file_type:<8} @ offset {r.offset:>8,}  │  "
            f"{mode:<10} │  conf={r.confidence:5.1f}%  │  "
            f"{status}  │  {len(r.data):>9,} bytes  │  SHA256={r.sha256[:16]}…"
        )
        lines.append(f"     └─ {r.structural_check_reason}")
        if r.stitch_scores:
            scores_str = ", ".join(f"{s:.1f}" for s in r.stitch_scores)
            lines.append(f"     └─ stitch scores: [{scores_str}]")
    return lines
