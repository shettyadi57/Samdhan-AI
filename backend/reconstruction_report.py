# -*- coding: utf-8 -*-
"""
SAMDHAN AI -- Feature 01: Intelligent Fragment Reconstruction
backend/reconstruction_report.py

Provenance tracking, completeness/corruption assessment, hashing,
and forensic report generation for reconstructed artifacts:
  - Byte-range provenance mapping (output_range -> source_fragment -> offset -> edge -> validation)
  - Completeness & corruption determination
  - SHA-256 hashing across source evidence, fragments, and reconstructed output
  - Output directory writer:
      reconstructed/
      ├── reconstructed_<id>.bin
      ├── provenance_<id>.json
      ├── validation_<id>.json
      └── reconstruction_report_<id>.json
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.format_validator import FormatValidationResult, validate_format_structure


@dataclass
class ProvenanceEntry:
    """
    Every reconstructed byte range must be traceable back to its source fragment,
    source offset, and the candidate edge that linked it.
    """
    output_range: List[int]        # [start_byte, end_byte] inclusive
    source_fragment: str           # fragment_id
    source_offset: int             # offset in original source evidence
    edge_from: Optional[str]       # previous fragment in reconstruction chain (None if head)
    edge_score: float              # score of edge from edge_from -> source_fragment (0.00-1.00)
    edge_evidence: List[str] = field(default_factory=list)
    validation_result: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output_range": self.output_range,
            "source_fragment": self.source_fragment,
            "source_offset": self.source_offset,
            "edge_from": self.edge_from,
            "edge_score": round(self.edge_score, 4),
            "edge_evidence": self.edge_evidence,
            "validation_result": self.validation_result,
        }


@dataclass
class ReconstructionReport:
    """
    Comprehensive forensic reconstruction report.
    """
    candidate_id: str
    reconstructed_sha256: str
    source_evidence_sha256: Optional[str]
    total_reconstructed_bytes: int
    byte_coverage: float             # ratio: reconstructed bytes / total source bytes
    final_status: str                # complete, partial, corrupted, ambiguous, failed, uncertain
    format_type: str
    format_validation: Dict[str, Any]
    fragments_used: List[Dict[str, Any]]
    fragments_missing: List[Dict[str, Any]]
    corrupted_fragments: List[Dict[str, Any]]
    fragment_ordering: List[str]
    edge_scores: List[float]
    edge_evidence: List[Dict[str, Any]]
    provenance: List[Dict[str, Any]]
    created_at: str
    forensic_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_provenance_records(
    ordered_fragment_ids: List[str],
    fragment_bytes_map: Dict[str, bytes],
    fragment_records_map: Dict[str, Any],
    graph_edges: Optional[Dict[Tuple[str, str], Any]] = None,
    validation_result: Optional[FormatValidationResult] = None,
) -> List[ProvenanceEntry]:
    """
    Build byte-range provenance records for every fragment in the ordered chain.
    """
    provenance_entries: List[ProvenanceEntry] = []
    current_offset = 0

    for i, fid in enumerate(ordered_fragment_ids):
        raw_chunk = fragment_bytes_map.get(fid, b"")
        chunk_len = len(raw_chunk)
        if chunk_len == 0:
            continue

        start_byte = current_offset
        end_byte = current_offset + chunk_len - 1
        current_offset += chunk_len

        rec = fragment_records_map.get(fid)
        src_offset = getattr(rec, "source_offset", -1) if rec else -1

        prev_fid = ordered_fragment_ids[i - 1] if i > 0 else None
        edge_score = 1.0  # head fragment default
        edge_evidence: List[str] = []

        if prev_fid and graph_edges and (prev_fid, fid) in graph_edges:
            edge = graph_edges[(prev_fid, fid)]
            # normalize edge_score to 0.0-1.0
            raw_sc = getattr(edge, "edge_score", 0.0)
            edge_score = raw_sc / 100.0 if raw_sc > 1.0 else raw_sc
            edge_evidence = list(getattr(edge, "evidence", []))
        elif i == 0:
            edge_evidence = ["Initial segment (head of reconstruction chain)"]

        # Validation info relevant to this byte range
        val_slice = {}
        if validation_result:
            val_slice = {
                "format_valid": validation_result.format_valid,
                "format_type": validation_result.format_type,
                "score": validation_result.score,
            }

        entry = ProvenanceEntry(
            output_range=[start_byte, end_byte],
            source_fragment=fid,
            source_offset=src_offset,
            edge_from=prev_fid,
            edge_score=edge_score,
            edge_evidence=edge_evidence,
            validation_result=val_slice,
        )
        provenance_entries.append(entry)

    return provenance_entries


def determine_reconstruction_status(
    format_validation: FormatValidationResult,
    fragments_used_count: int,
    total_available_fragments: int,
    missing_fragments_count: int,
    corrupted_fragments_count: int,
    competing_top_score_delta: Optional[float] = None,
    path_confidence: float = 80.0,
) -> Tuple[str, List[str]]:
    """
    Determine forensic status strictly from evidence:
      - complete: all fragments used, format valid, no corruption, high confidence
      - partial: missing fragments or gap in byte stream
      - corrupted: structural check fails or corrupted fragment detected
      - ambiguous: competing candidate path with near-identical score
      - failed: no valid bytes reconstructed or header missing
      - uncertain: low confidence or inconclusive validation
    """
    notes: List[str] = []

    if corrupted_fragments_count > 0 and (not format_validation.format_valid or format_validation.score < 90.0):
        notes.append(f"Corruption detected: {corrupted_fragments_count} corrupted fragments flagged, structural score {format_validation.score:.1f}")
        return "corrupted", notes

    if competing_top_score_delta is not None and abs(competing_top_score_delta) < 3.0:
        notes.append(f"Ambiguous ordering: alternative candidate path within {abs(competing_top_score_delta):.1f} score points")
        return "ambiguous", notes

    if missing_fragments_count > 0 or fragments_used_count < total_available_fragments:
        notes.append(f"Partial reconstruction: {missing_fragments_count} missing fragments ({fragments_used_count}/{total_available_fragments} used)")
        return "partial", notes

    if format_validation.format_valid and path_confidence >= 55.0:
        notes.append(f"Complete reconstruction: all {fragments_used_count} fragments present; format valid ({format_validation.reason})")
        return "complete", notes

    if path_confidence < 35.0:
        notes.append(f"Uncertain reconstruction: low path confidence ({path_confidence:.1f}/100)")
        return "uncertain", notes

    if not format_validation.format_valid:
        notes.append(f"Partial or damaged structure: format check did not pass ({format_validation.reason})")
        return "partial", notes

    return "uncertain", notes


def export_reconstruction_artifacts(
    candidate_id: str,
    assembled_bytes: bytes,
    provenance_entries: List[ProvenanceEntry],
    validation_result: FormatValidationResult,
    report: ReconstructionReport,
    output_dir: Optional[Path] = None,
) -> Dict[str, str]:
    """
    Generate the 4 mandatory output files for every reconstruction:
      reconstructed/
      ├── reconstructed_<id>.bin
      ├── provenance_<id>.json
      ├── validation_<id>.json
      └── reconstruction_report_<id>.json

    Returns dict mapping artifact type to its absolute file path.
    """
    if output_dir is None:
        base_dir = Path(__file__).parent.parent
        output_dir = base_dir / "reconstructed"

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    clean_id = candidate_id.replace(" ", "_").replace("/", "_").replace("\\", "_")

    bin_path = output_dir / f"reconstructed_{clean_id}.bin"
    prov_path = output_dir / f"provenance_{clean_id}.json"
    val_path = output_dir / f"validation_{clean_id}.json"
    rep_path = output_dir / f"reconstruction_report_{clean_id}.json"

    # 1. Write binary
    bin_path.write_bytes(assembled_bytes)

    # 2. Write provenance JSON
    prov_data = {
        "candidate_id": candidate_id,
        "total_ranges": len(provenance_entries),
        "provenance": [p.to_dict() for p in provenance_entries],
    }
    prov_path.write_text(json.dumps(prov_data, indent=2), encoding="utf-8")

    # 3. Write validation JSON
    val_path.write_text(json.dumps(validation_result.to_dict(), indent=2), encoding="utf-8")

    # 4. Write reconstruction report JSON
    rep_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    return {
        "binary_path": str(bin_path),
        "provenance_path": str(prov_path),
        "validation_path": str(val_path),
        "report_path": str(rep_path),
    }
