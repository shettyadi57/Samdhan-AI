# -*- coding: utf-8 -*-
"""
SAMDHAN AI -- Feature 01: Intelligent Fragment Reconstruction
backend/ground_truth_dataset.py

Deterministic synthetic ground-truth dataset generator and evaluation engine:
  - Generates verifiable originals for JPEG, PNG, PDF, ZIP
  - Programmatically slices originals into deterministic fragments
  - Implements Scenarios A-E:
      Scenario A: Correct fragments shuffled
      Scenario B: One missing fragment
      Scenario C: One corrupted fragment
      Scenario D: Ambiguous ordering
      Scenario E: Unrelated fragment mixed into dataset
  - Stores ground-truth originals separately
  - Evaluates reconstruction against ground truth:
      - byte_level_accuracy
      - fragment_ordering_accuracy
      - missing_fragment_detection
      - corruption_detection
      - structural_validation
      - reconstructed_sha256_match
"""

from __future__ import annotations

import copy
import hashlib
import io
import math
import random
import struct
import zipfile
import zlib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# 1. Ground Truth Binary Creators
# =============================================================================

def generate_ground_truth_jpeg() -> bytes:
    """Generate a clean, structurally valid JPEG with JFIF APP0, DQT, SOF0, DHT, SOS, and EOI."""
    soi = b"\xff\xd8"
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    dqt = b"\xff\xdb\x00\x43\x00" + bytes([(i * 3 + 1) % 255 for i in range(64)])
    sof0 = b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", 64, 64) + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    # Huffman table
    dht_bits = bytes([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0])
    dht_vals = bytes(range(len(dht_bits)))
    dht = b"\xff\xc4" + struct.pack(">H", 2 + 1 + len(dht_bits) + len(dht_vals)) + b"\x00" + dht_bits + dht_vals
    sos = b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    
    # Generate realistic pseudo-entropy scan bytes with proper byte stuffing (FF 00)
    raw_scan = bytearray()
    for i in range(1024):
        val = (i * 7 + 13) % 256
        raw_scan.append(val)
        if val == 0xff:
            raw_scan.append(0x00)  # escape FF with 00 in entropy scan

    eoi = b"\xff\xd9"
    return soi + app0 + dqt + sof0 + dht + sos + bytes(raw_scan) + eoi


def generate_ground_truth_png() -> bytes:
    """Generate a clean, structurally valid PNG with IHDR, IDAT, and IEND chunks with verified CRC32."""
    PNG_SIG = b"\x89PNG\r\n\x1a\n"

    def make_chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
        length_bytes = struct.pack(">I", len(chunk_data))
        crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        crc_bytes = struct.pack(">I", crc)
        return length_bytes + chunk_type + chunk_data + crc_bytes

    # IHDR: 16x16, 8-bit truecolor RGB
    ihdr_payload = struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0)
    ihdr = make_chunk(b"IHDR", ihdr_payload)

    # Scanlines: filter byte 0 followed by 16 * 3 bytes of RGB data per row
    raw_scanlines = bytearray()
    for y in range(16):
        raw_scanlines.append(0)  # filter type None
        for x in range(16):
            raw_scanlines.extend([(x * 15) % 256, (y * 15) % 256, ((x + y) * 8) % 256])

    compressed_idat = zlib.compress(bytes(raw_scanlines))
    idat = make_chunk(b"IDAT", compressed_idat)
    iend = make_chunk(b"IEND", b"")

    return PNG_SIG + ihdr + idat + iend


def generate_ground_truth_pdf() -> bytes:
    """Generate a clean, structurally valid PDF with objects, xref, trailer, and %%EOF."""
    pdf_content = (
        b"%PDF-1.7\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 44 >>\nstream\nBT /F1 12 Tf 72 712 Td (SAMDHAN FORENSIC EVIDENCE) Tj ET\nendstream\nendobj\n"
    )
    xref_offset = len(pdf_content)
    xref = (
        b"xref\n"
        b"0 5\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000212 00000 n \n"
    )
    trailer = (
        b"trailer\n"
        b"<< /Size 5 /Root 1 0 R >>\n"
        b"startxref\n"
        + str(xref_offset).encode("ascii") + b"\n"
        b"%%EOF\n"
    )
    return pdf_content + xref + trailer


def generate_ground_truth_zip() -> bytes:
    """Generate a clean, structurally valid ZIP file with entries, central directory, and EOCD."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("evidence_01.txt", "Forensic fragment analysis audit log record A-101\n")
        zf.writestr("evidence_02.bin", bytes(range(128)))
        zf.writestr("manifest.json", '{"case": "SAMDHAN-01", "classification": "CONFIDENTIAL"}\n')
    return buf.getvalue()


# =============================================================================
# 2. Fragment Slicing & Scenario Dataclasses
# =============================================================================

@dataclass
class SyntheticFragment:
    fragment_id: str
    original_index: int
    source_offset: int
    length: int
    sha256: str
    data: bytes
    is_corrupted: bool = False
    is_foreign: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fragment_id": self.fragment_id,
            "original_index": self.original_index,
            "source_offset": self.source_offset,
            "length": self.length,
            "sha256": self.sha256,
            "is_corrupted": self.is_corrupted,
            "is_foreign": self.is_foreign,
        }


@dataclass
class ScenarioDataset:
    scenario_name: str          # A, B, C, D, or E
    scenario_description: str
    format_type: str            # JPEG, PNG, PDF, ZIP
    original_bytes: bytes
    original_sha256: str
    total_original_bytes: int
    fragments: List[SyntheticFragment]
    missing_fragment_indices: List[int] = field(default_factory=list)
    corrupted_fragment_indices: List[int] = field(default_factory=list)
    ambiguous_fragment_indices: List[int] = field(default_factory=list)
    unrelated_fragment_ids: List[str] = field(default_factory=list)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario_name,
            "description": self.scenario_description,
            "format_type": self.format_type,
            "original_sha256": self.original_sha256,
            "original_bytes": self.total_original_bytes,
            "fragment_count": len(self.fragments),
            "missing_count": len(self.missing_fragment_indices),
            "corrupted_count": len(self.corrupted_fragment_indices),
            "unrelated_count": len(self.unrelated_fragment_ids),
        }


def slice_into_fragments(
    raw_data: bytes,
    num_chunks: int = 4,
    prefix: str = "F",
) -> List[SyntheticFragment]:
    """Deterministically slice raw data into cluster-aligned or equal chunks."""
    chunk_size = math.ceil(len(raw_data) / num_chunks)
    fragments: List[SyntheticFragment] = []
    offset = 0

    for i in range(num_chunks):
        if offset >= len(raw_data):
            break
        chunk = raw_data[offset : offset + chunk_size]
        h = hashlib.sha256(chunk).hexdigest()
        fid = f"FRAG-{h[:12].upper()}"
        fragments.append(SyntheticFragment(
            fragment_id=fid,
            original_index=i,
            source_offset=offset,
            length=len(chunk),
            sha256=h,
            data=chunk,
        ))
        offset += len(chunk)

    return fragments


# =============================================================================
# 3. Scenario Builders (A, B, C, D, E)
# =============================================================================

def build_scenario_a(format_type: str = "JPEG") -> ScenarioDataset:
    """
    Scenario A: Correct fragments shuffled.
    All fragments present and pristine, but provided in non-sequential order.
    """
    orig = get_ground_truth_bytes(format_type)
    frags = slice_into_fragments(orig, num_chunks=4, prefix="FA")
    
    # Shuffle deterministically
    shuffled = copy.copy(frags)
    # deterministic permutation e.g. [2, 0, 3, 1]
    if len(shuffled) == 4:
        shuffled = [frags[2], frags[0], frags[3], frags[1]]
    else:
        rnd = random.Random(42)
        rnd.shuffle(shuffled)

    return ScenarioDataset(
        scenario_name="Scenario A",
        scenario_description="Correct fragments shuffled; all pieces present and intact",
        format_type=format_type,
        original_bytes=orig,
        original_sha256=hashlib.sha256(orig).hexdigest(),
        total_original_bytes=len(orig),
        fragments=shuffled,
    )


def build_scenario_b(format_type: str = "PNG") -> ScenarioDataset:
    """
    Scenario B: One missing fragment.
    Fragment #2 (interior) is missing from the dataset.
    """
    orig = get_ground_truth_bytes(format_type)
    frags = slice_into_fragments(orig, num_chunks=4, prefix="FB")
    
    # Remove fragment at index 1 (the 2nd fragment)
    kept = [frags[0], frags[2], frags[3]]
    # Shuffle remaining
    shuffled = [kept[1], kept[0], kept[2]]

    return ScenarioDataset(
        scenario_name="Scenario B",
        scenario_description="One interior fragment missing; reconstructor must detect gap (PARTIAL)",
        format_type=format_type,
        original_bytes=orig,
        original_sha256=hashlib.sha256(orig).hexdigest(),
        total_original_bytes=len(orig),
        fragments=shuffled,
        missing_fragment_indices=[1],
    )


def build_scenario_c(format_type: str = "JPEG") -> ScenarioDataset:
    """
    Scenario C: One corrupted fragment.
    Fragment #2 is zero-filled / bit-flipped; reconstructor must preserve bytes as-is and report CORRUPTED.
    """
    orig = get_ground_truth_bytes(format_type)
    frags = slice_into_fragments(orig, num_chunks=4, prefix="FC")

    # Corrupt fragment at index 1
    target = frags[1]
    corrupted_data = b"\x00" * len(target.data)
    c_hash = hashlib.sha256(corrupted_data).hexdigest()
    corrupted_frag = SyntheticFragment(
        fragment_id=f"FRAG-{c_hash[:12].upper()}",
        original_index=target.original_index,
        source_offset=target.source_offset,
        length=len(corrupted_data),
        sha256=c_hash,
        data=corrupted_data,
        is_corrupted=True,
    )

    dataset_frags = [frags[0], corrupted_frag, frags[2], frags[3]]
    # Shuffle
    shuffled = [dataset_frags[2], dataset_frags[0], dataset_frags[3], dataset_frags[1]]

    return ScenarioDataset(
        scenario_name="Scenario C",
        scenario_description="One fragment zero-fill corrupted; must report corruption without silent repair",
        format_type=format_type,
        original_bytes=orig,
        original_sha256=hashlib.sha256(orig).hexdigest(),
        total_original_bytes=len(orig),
        fragments=shuffled,
        corrupted_fragment_indices=[1],
    )


def build_scenario_d(format_type: str = "PDF") -> ScenarioDataset:
    """
    Scenario D: Ambiguous ordering.
    Two interior chunks have similar boundary profiles or competing edge candidates.
    """
    orig = get_ground_truth_bytes(format_type)
    frags = slice_into_fragments(orig, num_chunks=4, prefix="FD")
    
    # Shuffle
    shuffled = [frags[1], frags[2], frags[0], frags[3]]

    return ScenarioDataset(
        scenario_name="Scenario D",
        scenario_description="Ambiguous candidate paths; system must flag ambiguity or preserve alternatives",
        format_type=format_type,
        original_bytes=orig,
        original_sha256=hashlib.sha256(orig).hexdigest(),
        total_original_bytes=len(orig),
        fragments=shuffled,
        ambiguous_fragment_indices=[1, 2],
    )


def build_scenario_e(format_type: str = "ZIP") -> ScenarioDataset:
    """
    Scenario E: Unrelated fragment mixed into the dataset.
    A foreign fragment (e.g. from a JPEG) is injected into the ZIP fragment pool.
    """
    orig = get_ground_truth_bytes(format_type)
    frags = slice_into_fragments(orig, num_chunks=4, prefix="FE")

    foreign_data = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00FOREIGN_JPEG_PAYLOAD"
    foreign_hash = hashlib.sha256(foreign_data).hexdigest()
    foreign_frag = SyntheticFragment(
        fragment_id=f"FRAG-{foreign_hash[:12].upper()}",
        original_index=-1,
        source_offset=999999,
        length=len(foreign_data),
        sha256=foreign_hash,
        data=foreign_data,
        is_foreign=True,
    )

    mixed = [frags[2], foreign_frag, frags[0], frags[3], frags[1]]

    return ScenarioDataset(
        scenario_name="Scenario E",
        scenario_description="Foreign fragment injected into dataset; engine must prune it via contradiction penalty",
        format_type=format_type,
        original_bytes=orig,
        original_sha256=hashlib.sha256(orig).hexdigest(),
        total_original_bytes=len(orig),
        fragments=mixed,
        unrelated_fragment_ids=[foreign_frag.fragment_id],
    )


def get_ground_truth_bytes(format_type: str) -> bytes:
    """Retrieve raw ground truth bytes for a specific format."""
    ft = format_type.upper().strip()
    if ft in ("JPEG", "JPG"):
        return generate_ground_truth_jpeg()
    elif ft == "PNG":
        return generate_ground_truth_png()
    elif ft == "PDF":
        return generate_ground_truth_pdf()
    elif ft in ("ZIP", "DOCX"):
        return generate_ground_truth_zip()
    else:
        raise ValueError(f"Unsupported ground truth format: {format_type}")


# =============================================================================
# 4. Evaluation Engine
# =============================================================================

@dataclass
class EvaluationMetrics:
    scenario: str
    format_type: str
    byte_level_accuracy: float           # 0.0 to 1.0 (exact byte matching ratio)
    fragment_ordering_accuracy: float    # 0.0 to 1.0 (correct relative sequence ratio)
    missing_fragment_detected: bool      # True if missing fragments correctly flagged
    corruption_detected: bool            # True if corruption correctly flagged
    structural_validation_passed: bool   # Structural check outcome
    structural_score: float              # 0 to 100
    reconstructed_sha256: str
    ground_truth_sha256: str
    sha256_match: bool                   # True only if reconstructed SHA-256 matches ground truth exactly
    reconstructed_bytes: int
    ground_truth_bytes: int
    final_status: str                    # COMPLETE, PARTIAL, CORRUPTED, AMBIGUOUS, UNCERTAIN
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario,
            "format_type": self.format_type,
            "byte_level_accuracy": round(self.byte_level_accuracy, 4),
            "fragment_ordering_accuracy": round(self.fragment_ordering_accuracy, 4),
            "missing_fragment_detected": self.missing_fragment_detected,
            "corruption_detected": self.corruption_detected,
            "structural_validation_passed": self.structural_validation_passed,
            "structural_score": round(self.structural_score, 2),
            "reconstructed_sha256": self.reconstructed_sha256,
            "ground_truth_sha256": self.ground_truth_sha256,
            "sha256_match": self.sha256_match,
            "reconstructed_bytes": self.reconstructed_bytes,
            "ground_truth_bytes": self.ground_truth_bytes,
            "final_status": self.final_status,
            "details": self.details,
        }


def evaluate_reconstruction(
    scenario: ScenarioDataset,
    candidate_ordered_fragment_ids: List[str],
    assembled_bytes: bytes,
    candidate_status: str,
    structural_validation: Any,
) -> EvaluationMetrics:
    """
    Compare reconstructed result against ground truth.
    Calculates exact metrics without fabrication.
    """
    gt_bytes = scenario.original_bytes
    gt_sha256 = scenario.original_sha256
    rec_sha256 = hashlib.sha256(assembled_bytes).hexdigest()
    sha256_match = (rec_sha256 == gt_sha256)

    # 1. Byte-level accuracy
    min_len = min(len(gt_bytes), len(assembled_bytes))
    max_len = max(len(gt_bytes), len(assembled_bytes))
    if max_len == 0:
        byte_acc = 1.0
    else:
        matching_bytes = sum(1 for i in range(min_len) if gt_bytes[i] == assembled_bytes[i])
        byte_acc = matching_bytes / float(max_len)

    # 2. Fragment ordering accuracy
    # Map fragment_id to its true original index
    frag_map = {f.fragment_id: f.original_index for f in scenario.fragments}
    ordered_indices = [frag_map.get(fid, -99) for fid in candidate_ordered_fragment_ids]

    correct_pairs = 0
    total_pairs = max(1, len(ordered_indices) - 1)
    for i in range(len(ordered_indices) - 1):
        idx_a = ordered_indices[i]
        idx_b = ordered_indices[i + 1]
        if idx_a >= 0 and idx_b >= 0 and idx_b > idx_a:
            correct_pairs += 1

    ordering_acc = (correct_pairs / float(total_pairs)) if len(ordered_indices) > 1 else 1.0

    # 3. Missing-fragment detection
    has_missing_in_scenario = len(scenario.missing_fragment_indices) > 0
    reported_as_partial_or_missing = (
        candidate_status.upper() in ("PARTIAL", "UNCERTAIN") or
        len(candidate_ordered_fragment_ids) < len([f for f in scenario.fragments if not f.is_foreign])
    )
    missing_detected = (has_missing_in_scenario == reported_as_partial_or_missing) if has_missing_in_scenario else True

    # 4. Corruption detection
    has_corrupt_in_scenario = len(scenario.corrupted_fragment_indices) > 0
    reported_corrupt = (candidate_status.upper() in ("CORRUPTED", "UNCERTAIN") or
                        (not getattr(structural_validation, "format_valid", True)))
    corruption_detected = (has_corrupt_in_scenario == reported_corrupt) if has_corrupt_in_scenario else True

    struct_passed = getattr(structural_validation, "format_valid", False)
    struct_score = getattr(structural_validation, "score", 0.0)

    return EvaluationMetrics(
        scenario=scenario.scenario_name,
        format_type=scenario.format_type,
        byte_level_accuracy=byte_acc,
        fragment_ordering_accuracy=ordering_acc,
        missing_fragment_detected=missing_detected,
        corruption_detected=corruption_detected,
        structural_validation_passed=struct_passed,
        structural_score=struct_score,
        reconstructed_sha256=rec_sha256,
        ground_truth_sha256=gt_sha256,
        sha256_match=sha256_match,
        reconstructed_bytes=len(assembled_bytes),
        ground_truth_bytes=len(gt_bytes),
        final_status=candidate_status,
        details={
            "ordered_indices": ordered_indices,
            "total_pairs": total_pairs,
            "correct_pairs": correct_pairs,
        },
    )
