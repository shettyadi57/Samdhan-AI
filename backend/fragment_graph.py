# -*- coding: utf-8 -*-
"""
SAMDHAN AI -- Feature 01: Intelligent Fragment Reconstruction
backend/fragment_graph.py

Phase 2 of 4:
    ANALYZED FRAGMENT DATA
            |
    CANDIDATE RELATIONSHIPS   <- CandidateEdge generation
            |
    EDGE SCORING              <- 5-component weighted formula
            |
    DIRECTED GRAPH            <- FragmentGraph (adjacency dict)
            |
    RECONSTRUCTION CANDIDATES <- path enumeration, cycle/duplicate guards
            |
    ORDERED FRAGMENT CHAINS   <- validated chains with status
            |
    BYTE REASSEMBLY           <- actual concatenation, no fabrication

Design rules:
  - Every edge carries ALL 5 score components separately (never a mystery number).
  - Score weights are configurable; defaults follow the spec.
  - Filenames are NEVER used for ordering or type detection.
  - Source evidence bytes are NEVER modified.
  - Corrupted fragments are preserved as-is; corruption is annotated, not hidden.
  - Missing fragments produce status=PARTIAL with explicit gap records.
  - All fabrication is explicitly prohibited; UNCERTAIN is a valid status.

Reuses without modification:
  - FragmentRecord            (backend/fragment_ingestor.py)
  - shannon_entropy           (backend/fragment_ingestor.py)
  - structural_check          (fragrecon/engine/fragment_reconstructor.py)
  - entropy_continuity_score  (fragrecon/engine/fragment_reconstructor.py)
  - ngram_affinity_score      (fragrecon/engine/fragment_reconstructor.py)
  - validate_structure        (backend/integrity_pipeline.py)
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import struct
import sys
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Re-use Phase 1 + existing engine functions — no rewriting
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.fragment_ingestor import (
    FragmentRecord,
    shannon_entropy,
    FOOTER_TABLE,
    INTERNAL_MARKERS,
    _detect_type,
    UNKNOWN_OFFSET,
)

# Reuse the existing scoring functions from fragrecon/engine
from fragrecon.engine.fragment_reconstructor import (
    entropy_continuity_score,
    ngram_affinity_score,
    structural_check as _fragrecon_structural_check,
)

# Reuse format_validator for format-specific structural validation
from backend.format_validator import validate_format_structure

# Reuse the richer structural validators from integrity_pipeline
# (these return {score, checks, issues} dicts — more detailed than fragrecon's bool)
try:
    from backend.integrity_pipeline import validate_structure as _pipeline_validate
    _PIPELINE_AVAILABLE = True
except Exception:
    _PIPELINE_AVAILABLE = False


# =============================================================================
# Constants
# =============================================================================

# Default edge score weights (spec §2)
DEFAULT_WEIGHTS: Dict[str, float] = {
    "signature":     0.25,
    "continuity":    0.20,
    "structural":    0.30,
    "entropy":       0.15,
    "contradiction": 0.10,   # applied as penalty (subtracted)
}

# Minimum edge_score to include an edge in the graph (0-100 scale)
MIN_EDGE_SCORE: float = 15.0

# How many top-K candidates to keep per source node (limits O(N^2) explosion)
MAX_EDGES_PER_NODE: int = 8

# Maximum path length to enumerate during reconstruction
MAX_PATH_LENGTH: int = 32

# Maximum number of candidate paths to return per reconstruction
MAX_CANDIDATE_PATHS: int = 10

# Boundary window for entropy/ngram scoring (bytes)
SCORE_WINDOW: int = 256


# =============================================================================
# Status labels
# =============================================================================

class ReconstructionStatus:
    COMPLETE   = "COMPLETE"    # all fragments present, structural check passes
    PARTIAL    = "PARTIAL"     # one or more fragments missing or gaps detected
    CORRUPTED  = "CORRUPTED"   # structural check fails on final assembly
    AMBIGUOUS  = "AMBIGUOUS"   # multiple equally-scored candidate paths
    UNCERTAIN  = "UNCERTAIN"   # insufficient evidence to determine ordering
    FAILED     = "FAILED"      # no valid path could be constructed


# =============================================================================
# Data models
# =============================================================================

@dataclass
class CandidateEdge:
    """
    A directed candidate relationship: fragment A -> fragment B.

    Every scoring component is stored separately so investigators can see
    WHY the engine believes B follows A, not just a mysterious final score.
    """
    from_id:              str    # fragment_id of A
    to_id:                str    # fragment_id of B
    # ---- individual score components (all 0-100 range) ----
    signature_score:      float  # type-compatibility between A and B
    continuity_score:     float  # boundary entropy continuity (tail of A vs head of B)
    structural_score:     float  # combined assembly A+B passes structural validation
    entropy_score:        float  # entropy delta at the boundary (lower delta = higher score)
    contradiction_penalty: float  # evidence that B cannot follow A (0 = no contradiction)
    # ---- final weighted score ----
    edge_score:           float  # weighted combination (see compute_edge_score)
    # ---- evidence notes ----
    evidence:             List[str] = field(default_factory=list)
    weights_used:         Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class FragmentGap:
    """Records a position in a reconstruction chain where a fragment is missing."""
    position:         int     # index in chain where gap occurs
    after_fragment_id: str    # fragment preceding the gap
    gap_size_hint:    int     # estimated bytes missing (-1 if unknown)
    reason:           str


@dataclass
class CorruptedFragmentRecord:
    """Records a corrupted fragment found in a chain. Bytes are preserved as-is."""
    fragment_id:      str
    corruption_flags: List[str]
    affected_bytes:   str     # hex of first 32 bytes of corrupted region
    repair_performed: bool = False   # always False — we never silently repair


@dataclass
class ReconstructionCandidate:
    """
    One complete candidate reconstruction path.

    Contains the actual assembled bytes from the ordered fragments.
    Status is derived from evidence, not assumed.
    """
    candidate_id:       str
    ordered_fragment_ids: List[str]
    assembled_bytes:    bytes
    assembled_sha256:   str
    status:             str           # ReconstructionStatus constant
    path_score:         float         # mean edge score along the path (0-100)
    structural_check_passed: bool
    structural_check_reason: str
    structural_detail:  Dict          # {score, checks, issues} from validate_structure
    missing_fragments:  List[FragmentGap]
    corrupted_fragments: List[CorruptedFragmentRecord]
    format_type:        str
    total_bytes:        int
    fragment_count:     int
    edge_scores:        List[float]   # score for each edge in the chain
    notes:              List[str]     # human-readable explanation of decisions
    provenance:         List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["assembled_bytes"] = self.assembled_bytes.hex()  # bytes -> hex for JSON
        return d


# =============================================================================
# Structural validation (delegates to format_validator)
# =============================================================================

def _validate(data: bytes, file_type: str) -> Tuple[bool, str, Dict]:
    """
    Run byte-level structural validation on assembled bytes.
    Uses format_validator for thorough format-specific rules.
    Returns (passed, reason, detail_dict).
    """
    ft = file_type.upper()
    try:
        val_res = validate_format_structure(data, ft)
        return val_res.format_valid, val_res.reason, val_res.to_dict()
    except Exception:
        pass

    if _PIPELINE_AVAILABLE:
        try:
            detail = _pipeline_validate(data, ft)
            score  = detail.get("score", 0)
            issues = detail.get("issues", [])
            checks = detail.get("checks", [])
            passed = score >= 60 and len(issues) == 0
            reason = "; ".join(checks[:3]) if checks else ("; ".join(issues[:2]) if issues else "no detail")
            return passed, reason, detail
        except Exception:
            pass

    # Fallback
    passed, reason = _fragrecon_structural_check(ft, data)
    return passed, reason, {"score": 95 if passed else 20, "checks": [], "issues": [] if passed else [reason]}


# =============================================================================
# Edge scoring functions
# =============================================================================

def _signature_score(frag_a: FragmentRecord, frag_b: FragmentRecord) -> Tuple[float, List[str]]:
    """
    Score 0-100 based on format-signature compatibility between A and B.

    Rules:
    - If A has a known type and B has a different known type → low score
      (different-format fragments don't naturally follow each other)
    - If A is header_only or interior and B's type matches A → high score
    - If A has footer_compatible=True it is a natural terminal → B following it is penalised
    - If B is header_compatible=True it is a natural start → only valid as first fragment
    """
    evidence = []
    score = 50.0  # neutral baseline

    type_a = frag_a.detected_type
    type_b = frag_b.detected_type

    # Both types are known and consistent
    if type_a != "UNKNOWN" and type_b != "UNKNOWN":
        if type_a == type_b:
            score += 20.0
            evidence.append(f"Both fragments detected as {type_a}")
        else:
            score -= 35.0
            evidence.append(f"Type mismatch: A={type_a}, B={type_b} — unlikely continuation")

    # A already has a footer: it should terminate, not continue
    if frag_a.footer_compatible:
        score -= 30.0
        evidence.append("Fragment A contains a footer marker — unlikely to have a continuation")

    # B has a header marker: B is a start, not a continuation
    if frag_b.header_compatible and not frag_b.footer_compatible:
        if type_b != "UNKNOWN":
            # B looks like a standalone file start, not a mid-sequence fragment
            score -= 20.0
            evidence.append("Fragment B starts with a format header — may be independent file, not continuation")

    # A is header_only (no footer) — actively needs a continuation
    if frag_a.format_hint == "header_only":
        score += 15.0
        evidence.append("Fragment A is header_only — actively seeking continuation")

    # B looks like an interior or tail fragment
    if frag_b.format_hint in ("interior_or_unknown",):
        score += 10.0
        evidence.append("Fragment B has no format header — consistent with interior/tail position")

    return max(0.0, min(100.0, score)), evidence


def _continuity_score(frag_a: FragmentRecord, frag_b: FragmentRecord,
                      data_a: bytes, data_b: bytes) -> Tuple[float, str]:
    """
    Entropy continuity across the A→B boundary (0-100).
    Delegates to the existing entropy_continuity_score from fragrecon.
    """
    score = entropy_continuity_score(data_a, data_b, window=SCORE_WINDOW)
    reason = f"entropy delta boundary score: {score:.1f}/100"
    return score, reason


def _ngram_continuity_score(data_a: bytes, data_b: bytes) -> float:
    """N-gram affinity across the boundary. Reuses existing ngram_affinity_score."""
    return ngram_affinity_score(data_a, data_b)


def _structural_score(frag_a: FragmentRecord, frag_b: FragmentRecord,
                      data_a: bytes, data_b: bytes) -> Tuple[float, str, Dict]:
    """
    Score 0-100 based on whether concatenating A+B produces a structurally
    plausible partial assembly.

    If A's type is UNKNOWN or interior, we test B alone.
    If A has a header and B has content, we test A+B concatenated.
    """
    type_a = frag_a.detected_type
    type_b = frag_b.detected_type

    candidate_type = type_a if type_a != "UNKNOWN" else type_b
    if candidate_type == "UNKNOWN":
        return 40.0, "no type detected on either fragment — structural test skipped", {}

    combined = data_a + data_b
    passed, reason, detail = _validate(combined, candidate_type)
    score = float(detail.get("score", 50))

    # If the combined assembly FAILS but individual components are plausible:
    # give partial credit — partial assemblies won't be structurally complete yet
    if not passed and frag_a.header_compatible:
        # Header fragment combined with next chunk — incomplete is expected
        # Give credit proportional to how many internal markers are present
        markers_a = set(frag_a.internal_markers)
        markers_b = set(frag_b.internal_markers)
        all_markers = markers_a | markers_b
        if all_markers:
            score = max(score, 35.0 + len(all_markers) * 5.0)
            reason = f"partial assembly ({len(all_markers)} internal markers found; full validation deferred)"

    return max(0.0, min(100.0, score)), reason, detail


def _entropy_boundary_score(data_a: bytes, data_b: bytes) -> Tuple[float, str]:
    """
    Score 0-100 based on entropy delta at the boundary.
    Small delta → smooth transition → higher score.
    This is complementary to continuity_score (uses a different window).
    """
    tail = data_a[-64:] if len(data_a) >= 64 else data_a
    head = data_b[:64]  if len(data_b) >= 64 else data_b

    e_tail = shannon_entropy(tail)
    e_head = shannon_entropy(head)
    delta  = abs(e_tail - e_head)

    # Score: delta of 0 → 100; delta of 4+ → 0 (full range of practical deltas)
    score = max(0.0, 100.0 - (delta / 4.0) * 100.0)
    reason = f"entropy tail={e_tail:.3f}, head={e_head:.3f}, delta={delta:.3f}"
    return score, reason


def _contradiction_penalty(frag_a: FragmentRecord, frag_b: FragmentRecord,
                           data_a: bytes, data_b: bytes) -> Tuple[float, List[str]]:
    """
    Penalty 0-100 for specific contradictions that make A→B impossible or unlikely.

    Returns (penalty_score, reasons).
    penalty_score is subtracted in the final formula.
    """
    penalty = 0.0
    reasons = []

    # A already has a complete format structure (header + footer) → no continuation needed
    if frag_a.format_hint == "header_and_footer":
        penalty += 60.0
        reasons.append("Fragment A is structurally complete (header+footer) — B cannot follow")

    # B starts with a known header of a DIFFERENT type → B is independent
    type_a = frag_a.detected_type
    type_b = frag_b.detected_type
    if (frag_b.header_compatible and type_b != "UNKNOWN"
            and type_a != "UNKNOWN" and type_a != type_b):
        penalty += 50.0
        reasons.append(f"Fragment B has {type_b} header but A is {type_a} — cross-format continuation impossible")

    # Physical offset contradiction: if both offsets are known and B comes before A
    if (frag_a.source_offset != UNKNOWN_OFFSET
            and frag_b.source_offset != UNKNOWN_OFFSET
            and frag_b.source_offset < frag_a.source_offset):
        # In a linearly written file, B cannot be at a lower offset than A
        penalty += 25.0
        reasons.append(
            f"Physical offset contradiction: A at {frag_a.source_offset}, "
            f"B at {frag_b.source_offset} — B predates A in source"
        )

    # B is pure zero-fill — unlikely to be a meaningful continuation
    if frag_b.zero_byte_ratio > 0.95:
        penalty += 30.0
        reasons.append("Fragment B is near-total zero-fill — unlikely meaningful continuation")

    # A has corruption_flags that make it an invalid basis for stitching
    critical = {"near_total_zero_fill", "uniform_byte_pattern"}
    if critical.intersection(frag_a.corruption_flags):
        penalty += 40.0
        reasons.append(f"Fragment A has critical corruption flags: {frag_a.corruption_flags}")

    return min(100.0, penalty), reasons


def compute_edge_score(
    frag_a: FragmentRecord,
    frag_b: FragmentRecord,
    data_a: bytes,
    data_b: bytes,
    weights: Optional[Dict[str, float]] = None,
) -> CandidateEdge:
    """
    Compute a fully-documented CandidateEdge for the A→B relationship.

    edge_score = w_sig * sig_score
               + w_cont * cont_score
               + w_struct * struct_score
               + w_ent * entropy_score
               - w_contra * contradiction_penalty

    All components stored separately. Weights are configurable.
    """
    w = weights or DEFAULT_WEIGHTS

    sig_sc,   sig_ev   = _signature_score(frag_a, frag_b)
    cont_sc,  cont_ev  = _continuity_score(frag_a, frag_b, data_a, data_b)
    struct_sc, struct_ev, struct_detail = _structural_score(frag_a, frag_b, data_a, data_b)
    ent_sc,   ent_ev   = _entropy_boundary_score(data_a, data_b)
    contra,   contra_ev = _contradiction_penalty(frag_a, frag_b, data_a, data_b)

    edge_sc = (
        w["signature"]     * sig_sc
        + w["continuity"]  * cont_sc
        + w["structural"]  * struct_sc
        + w["entropy"]     * ent_sc
        - w["contradiction"] * contra
    )
    edge_sc = max(0.0, min(100.0, edge_sc))

    evidence = sig_ev + [cont_ev, struct_ev, ent_ev] + contra_ev

    return CandidateEdge(
        from_id               = frag_a.fragment_id,
        to_id                 = frag_b.fragment_id,
        signature_score       = round(sig_sc,   2),
        continuity_score      = round(cont_sc,  2),
        structural_score      = round(struct_sc, 2),
        entropy_score         = round(ent_sc,   2),
        contradiction_penalty = round(contra,   2),
        edge_score            = round(edge_sc,  2),
        evidence              = evidence,
        weights_used          = dict(w),
    )


# =============================================================================
# Graph construction
# =============================================================================

class FragmentGraph:
    """
    Directed graph where nodes are FragmentRecord objects and edges are
    CandidateEdge objects with full evidence.

        F1 --0.91--> F3
        |
        +--0.42--> F4
        |
        +--0.18--> F2

    Edges are filtered by MIN_EDGE_SCORE and capped per node at MAX_EDGES_PER_NODE
    to keep the search space tractable for large fragment sets.
    """

    def __init__(self):
        # fragment_id -> FragmentRecord
        self._nodes: Dict[str, FragmentRecord] = {}
        # fragment_id -> list of CandidateEdge (outgoing)
        self._edges: Dict[str, List[CandidateEdge]] = {}
        # fragment_id -> raw bytes
        self._data:  Dict[str, bytes] = {}

    def add_node(self, rec: FragmentRecord, raw_bytes: bytes) -> None:
        self._nodes[rec.fragment_id] = rec
        self._data[rec.fragment_id]  = raw_bytes
        if rec.fragment_id not in self._edges:
            self._edges[rec.fragment_id] = []

    def add_edge(self, edge: CandidateEdge) -> None:
        self._edges.setdefault(edge.from_id, []).append(edge)

    def node(self, fid: str) -> Optional[FragmentRecord]:
        return self._nodes.get(fid)

    def data(self, fid: str) -> bytes:
        return self._data.get(fid, b"")

    def out_edges(self, fid: str) -> List[CandidateEdge]:
        return sorted(self._edges.get(fid, []), key=lambda e: -e.edge_score)

    def all_nodes(self) -> List[FragmentRecord]:
        return list(self._nodes.values())

    def all_edges(self) -> List[CandidateEdge]:
        return [e for edges in self._edges.values() for e in edges]

    def node_count(self) -> int:
        return len(self._nodes)

    def edge_count(self) -> int:
        return sum(len(v) for v in self._edges.values())

    def to_dict(self) -> Dict:
        return {
            "node_count": self.node_count(),
            "edge_count": self.edge_count(),
            "nodes": [
                {
                    "fragment_id":   n.fragment_id,
                    "detected_type": n.detected_type,
                    "format_hint":   n.format_hint,
                    "length":        n.length,
                    "entropy":       n.entropy,
                    "corruption_flags": n.corruption_flags,
                }
                for n in self.all_nodes()
            ],
            "edges": [e.to_dict() for e in self.all_edges()],
        }


def build_graph(
    fragments: List[FragmentRecord],
    fragment_bytes: Dict[str, bytes],
    weights: Optional[Dict[str, float]] = None,
    min_edge_score: float = MIN_EDGE_SCORE,
    max_edges_per_node: int = MAX_EDGES_PER_NODE,
) -> FragmentGraph:
    """
    Build a directed fragment graph from a list of FragmentRecord objects.

    Format-signature constraints reduce the search space:
    - If fragment A has format_hint = "header_and_footer" (self-contained):
      it generates no outgoing edges (it needs no continuation).
    - Fragments of definitively different types don't generate edges
      (strong contradiction_penalty handles residual cross-type noise).
    - Every edge is scored with the full 5-component formula.

    O(N^2) worst case, but pruned by:
    1. Type-compatibility pre-filter (skip obviously incompatible pairs)
    2. max_edges_per_node cap (keep only top-K per source node)
    """
    g = FragmentGraph()

    for rec in fragments:
        raw = fragment_bytes.get(rec.fragment_id, b"")
        if not raw and rec.ingest_error:
            continue  # skip fragments that failed ingestion entirely
        g.add_node(rec, raw)

    node_ids = [rec.fragment_id for rec in fragments
                if rec.fragment_id in g._nodes]

    for fid_a in node_ids:
        frag_a = g.node(fid_a)
        data_a = g.data(fid_a)
        candidate_edges: List[CandidateEdge] = []

        # A self-contained fragment (header+footer) has no outgoing edges
        if frag_a.format_hint == "header_and_footer":
            continue

        for fid_b in node_ids:
            if fid_a == fid_b:
                continue

            frag_b = g.node(fid_b)
            data_b = g.data(fid_b)

            # Fast pre-filter: skip pairs where types are confirmed different
            type_a = frag_a.detected_type
            type_b = frag_b.detected_type
            if (type_a != "UNKNOWN" and type_b != "UNKNOWN"
                    and type_a != type_b
                    and frag_b.header_compatible):
                # B is a confirmed different-type start — definitely not a continuation
                continue

            edge = compute_edge_score(frag_a, frag_b, data_a, data_b, weights)

            if edge.edge_score >= min_edge_score:
                candidate_edges.append(edge)

        # Keep only top-K outgoing edges per node
        candidate_edges.sort(key=lambda e: -e.edge_score)
        for edge in candidate_edges[:max_edges_per_node]:
            g.add_edge(edge)

    return g


# =============================================================================
# Path reconstruction
# =============================================================================

def _find_start_candidates(g: FragmentGraph) -> List[str]:
    """
    Identify fragments that are plausible reconstruction starting points.

    A fragment is a plausible start if:
    1. It has header_compatible = True (starts with a known format header)
    2. OR no other fragment has a high-scoring edge TO it
       (i.e. it is not a plausible continuation of anything)

    This is a heuristic — multiple starts may be returned.
    """
    # Fragments that have high-confidence incoming edges
    has_strong_predecessor: Set[str] = set()
    for edge in g.all_edges():
        if edge.edge_score >= 55.0:
            has_strong_predecessor.add(edge.to_id)

    starts = []
    for frag in g.all_nodes():
        if frag.header_compatible:
            starts.append(frag.fragment_id)
        elif frag.fragment_id not in has_strong_predecessor:
            # No strong predecessor — may be a start
            starts.append(frag.fragment_id)

    # De-duplicate, prefer header_compatible ones first
    seen = set()
    ordered = []
    for fid in starts:
        if fid not in seen:
            seen.add(fid)
            ordered.append(fid)

    # Sort: header_compatible first
    ordered.sort(
        key=lambda fid: (0 if g.node(fid).header_compatible else 1,
                         -g.node(fid).entropy)
    )
    return ordered


def _is_valid_end(frag: FragmentRecord, assembled: bytes) -> bool:
    """
    True if frag looks like a valid terminal fragment:
    - footer_compatible flag set, OR
    - assembled bytes pass structural validation
    """
    if frag.footer_compatible:
        return True
    ft = frag.detected_type
    if ft == "UNKNOWN":
        return False
    passed, _, _ = _validate(assembled, ft)
    return passed


def _enumerate_paths(
    g: FragmentGraph,
    start_id: str,
    max_length: int = MAX_PATH_LENGTH,
    max_paths: int = MAX_CANDIDATE_PATHS,
) -> List[List[str]]:
    """
    Enumerate candidate paths starting from start_id using DFS with
    cycle prevention and duplicate-fragment prevention.

    Returns at most max_paths complete paths (those that end at a valid
    terminal fragment) plus partial paths if no terminal is found.

    Cycle prevention: each fragment_id can appear at most once in a path.
    Duplicate prevention: same guarantee (fragment_id uniqueness in path).
    """
    complete_paths: List[List[str]] = []
    partial_paths:  List[List[str]] = []

    # DFS stack: (current_path, visited_set)
    stack: List[Tuple[List[str], Set[str]]] = [([start_id], {start_id})]

    while stack and len(complete_paths) + len(partial_paths) < max_paths * 3:
        path, visited = stack.pop()
        current_id = path[-1]
        current_frag = g.node(current_id)

        # Check termination
        assembled = b"".join(g.data(fid) for fid in path)
        if _is_valid_end(current_frag, assembled):
            complete_paths.append(list(path))
            if len(complete_paths) >= max_paths:
                break
            continue

        # Max depth reached without terminal
        if len(path) >= max_length:
            partial_paths.append(list(path))
            continue

        out = g.out_edges(current_id)
        if not out:
            # Dead end — record as partial
            partial_paths.append(list(path))
            continue

        # Push continuations in reverse order (so best score is popped first)
        pushed_any = False
        for edge in reversed(out):
            next_id = edge.to_id
            if next_id in visited:
                continue  # cycle or duplicate prevention
            new_visited = visited | {next_id}
            stack.append((path + [next_id], new_visited))
            pushed_any = True

        if not pushed_any:
            partial_paths.append(list(path))

    # Return complete paths first, then partial, up to max_paths total
    result = complete_paths
    if len(result) < max_paths:
        result = result + partial_paths[: max_paths - len(result)]
    return result[:max_paths]


def _path_score(g: FragmentGraph, path: List[str]) -> Tuple[float, List[float]]:
    """
    Mean edge score along a path, plus list of individual edge scores.
    Returns (mean_score, [edge_scores]).
    """
    if len(path) < 2:
        return 0.0, []
    edge_scores = []
    for i in range(len(path) - 1):
        fid_a = path[i]
        fid_b = path[i + 1]
        outgoing = {e.to_id: e for e in g.out_edges(fid_a)}
        edge = outgoing.get(fid_b)
        edge_scores.append(edge.edge_score if edge else 0.0)
    mean_sc = sum(edge_scores) / len(edge_scores)
    return mean_sc, edge_scores


# =============================================================================
# Byte reassembly
# =============================================================================

def _assemble_bytes(g: FragmentGraph, path: List[str]) -> bytes:
    """
    Concatenate actual fragment bytes in path order.
    This is REAL byte reassembly — no fabrication, no padding, no guessing.
    The bytes come directly from the source evidence via the graph's data store.
    """
    return b"".join(g.data(fid) for fid in path)


def _detect_status(
    path: List[str],
    all_node_ids: Set[str],
    assembled: bytes,
    format_type: str,
    struct_passed: bool,
    struct_score: float,
    path_sc: float,
    competing_path_score: Optional[float],
) -> Tuple[str, List[str]]:
    """
    Determine reconstruction status from evidence. Never guesses.
    """
    notes: List[str] = []

    # Any fragments NOT in this path
    missing = all_node_ids - set(path)

    if struct_passed and not missing and path_sc >= 60.0:
        status = ReconstructionStatus.COMPLETE
        notes.append(f"Structural check passed; all {len(path)} fragments present; path score {path_sc:.1f}")

    elif struct_passed and missing:
        status = ReconstructionStatus.PARTIAL
        notes.append(f"{len(missing)} fragment(s) not included in this path")

    elif not struct_passed and missing:
        status = ReconstructionStatus.PARTIAL
        notes.append(f"Structural check did not pass AND {len(missing)} fragment(s) absent")

    elif not struct_passed:
        # We have all fragments but assembly is structurally invalid
        if struct_score < 30:
            status = ReconstructionStatus.CORRUPTED
            notes.append(f"All fragments present but structural validation failed (score={struct_score:.0f})")
        else:
            status = ReconstructionStatus.UNCERTAIN
            notes.append(f"Structural check inconclusive (score={struct_score:.0f}) — ordering may be incomplete")

    elif path_sc < 30.0:
        status = ReconstructionStatus.UNCERTAIN
        notes.append(f"Low path confidence ({path_sc:.1f}) — insufficient evidence for reliable ordering")

    else:
        status = ReconstructionStatus.UNCERTAIN
        notes.append("Status could not be determined from available evidence")

    # Ambiguous: competing path within 5 points
    if (competing_path_score is not None
            and status == ReconstructionStatus.COMPLETE
            and abs(path_sc - competing_path_score) < 5.0):
        status = ReconstructionStatus.AMBIGUOUS
        notes.append(
            f"Competing candidate path within {abs(path_sc - competing_path_score):.1f} "
            f"score points — ordering is ambiguous"
        )

    return status, notes


# =============================================================================
# Main reconstruction entry point
# =============================================================================

def reconstruct_fragments(
    fragments: List[FragmentRecord],
    fragment_bytes: Dict[str, bytes],
    weights: Optional[Dict[str, float]] = None,
    min_edge_score: float = MIN_EDGE_SCORE,
    max_candidates: int = MAX_CANDIDATE_PATHS,
) -> Tuple[FragmentGraph, List[ReconstructionCandidate]]:
    """
    Full Phase 2 pipeline:
        fragments + raw bytes
            -> graph
            -> candidate paths
            -> scored + validated candidates
            -> byte-assembled ReconstructionCandidate objects

    Returns (graph, candidates) where candidates are sorted best-first.

    Args:
        fragments:       List of FragmentRecord from Phase 1 ingestion
        fragment_bytes:  {fragment_id: raw_bytes} mapping
        weights:         Override default score weights (optional)
        min_edge_score:  Minimum edge score to include in graph (default 15.0)
        max_candidates:  Maximum reconstruction candidates to return

    Chain-of-custody:
        - Source bytes in fragment_bytes are read but never modified.
        - assembled_bytes in each ReconstructionCandidate is a new allocation.
        - Corrupted fragments are included as-is with corruption annotated.
    """
    # Step 1 — Build graph
    g = build_graph(fragments, fragment_bytes, weights, min_edge_score)

    all_node_ids = {rec.fragment_id for rec in fragments if not rec.ingest_error}

    # Step 2 — Detect format type from fragment set
    # Use the most common non-UNKNOWN type across all fragments
    type_counts: Dict[str, int] = {}
    for rec in fragments:
        t = rec.detected_type
        if t != "UNKNOWN":
            type_counts[t] = type_counts.get(t, 0) + 1
    format_type = max(type_counts, key=lambda t: type_counts[t]) if type_counts else "UNKNOWN"

    # Step 3 — Find start candidates
    start_candidates = _find_start_candidates(g)

    if not start_candidates:
        # No plausible start — return FAILED
        failed = ReconstructionCandidate(
            candidate_id             = "CAND-FAILED-NO-START",
            ordered_fragment_ids     = [],
            assembled_bytes          = b"",
            assembled_sha256         = hashlib.sha256(b"").hexdigest(),
            status                   = ReconstructionStatus.FAILED,
            path_score               = 0.0,
            structural_check_passed  = False,
            structural_check_reason  = "No plausible starting fragment found",
            structural_detail        = {},
            missing_fragments        = [],
            corrupted_fragments      = [],
            format_type              = format_type,
            total_bytes              = 0,
            fragment_count           = 0,
            edge_scores              = [],
            notes                    = ["No fragment had a recognizable header or was reachable as a start node"],
        )
        return g, [failed]

    # Step 4 — Enumerate paths from each start candidate
    all_paths: List[Tuple[List[str], float, List[float]]] = []
    seen_path_keys: Set[str] = set()

    for start_id in start_candidates[:4]:  # limit start expansion
        paths = _enumerate_paths(g, start_id, max_paths=max_candidates * 2)
        for path in paths:
            key = ",".join(path)
            if key in seen_path_keys:
                continue
            seen_path_keys.add(key)
            sc, edge_scores = _path_score(g, path)
            all_paths.append((path, sc, edge_scores))

    if not all_paths:
        # Single-fragment case (no edges at all)
        for fid in list(all_node_ids)[:1]:
            all_paths.append(([fid], 0.0, []))

    # Sort paths by score descending
    all_paths.sort(key=lambda x: -x[1])

    # Step 5 — Build ReconstructionCandidate for top-N paths
    candidates: List[ReconstructionCandidate] = []
    competing_score: Optional[float] = all_paths[1][1] if len(all_paths) > 1 else None

    for i, (path, path_sc, edge_scores) in enumerate(all_paths[:max_candidates]):
        assembled  = _assemble_bytes(g, path)
        sha256_hex = hashlib.sha256(assembled).hexdigest()

        # Structural validation on full assembly
        struct_passed, struct_reason, struct_detail = _validate(assembled, format_type)
        struct_score = float(struct_detail.get("score", 0))

        # Status determination
        comp = competing_score if i == 0 else None
        status, notes = _detect_status(
            path, all_node_ids, assembled, format_type,
            struct_passed, struct_score, path_sc, comp
        )

        # Identify corrupted fragments in this path
        corrupted_in_path: List[CorruptedFragmentRecord] = []
        for fid in path:
            frag = g.node(fid)
            if frag and frag.corruption_flags:
                corrupted_in_path.append(CorruptedFragmentRecord(
                    fragment_id      = fid,
                    corruption_flags = frag.corruption_flags,
                    affected_bytes   = g.data(fid)[:32].hex(),
                    repair_performed = False,
                ))

        # Identify missing fragments (fragments NOT in this path)
        missing_ids = all_node_ids - set(path)
        missing_gaps: List[FragmentGap] = []
        for mid in sorted(missing_ids):
            missing_gaps.append(FragmentGap(
                position          = -1,  # position within the path not determinable
                after_fragment_id = path[-1] if path else "",
                gap_size_hint     = g.node(mid).length if g.node(mid) else -1,
                reason            = f"Fragment {mid} not included in this candidate path",
            ))

        # Build provenance records
        from backend.reconstruction_report import build_provenance_records
        records_map = {fid: g.node(fid) for fid in path}
        bytes_map = {fid: g.data(fid) for fid in path}
        edges_map = {(e.from_id, e.to_id): e for e in g.all_edges()}
        provenance_entries = build_provenance_records(
            path, bytes_map, records_map, edges_map
        )

        cand_id = f"CAND-{i+1:02d}-{sha256_hex[:8].upper()}"

        candidates.append(ReconstructionCandidate(
            candidate_id             = cand_id,
            ordered_fragment_ids     = path,
            assembled_bytes          = assembled,
            assembled_sha256         = sha256_hex,
            status                   = status,
            path_score               = round(path_sc, 2),
            structural_check_passed  = struct_passed,
            structural_check_reason  = struct_reason,
            structural_detail        = struct_detail,
            missing_fragments        = missing_gaps,
            corrupted_fragments      = corrupted_in_path,
            format_type              = format_type,
            total_bytes              = len(assembled),
            fragment_count           = len(path),
            edge_scores              = [round(s, 2) for s in edge_scores],
            notes                    = notes,
            provenance               = [p.to_dict() for p in provenance_entries],
        ))

    return g, candidates


# =============================================================================
# Convenience wrappers
# =============================================================================

def reconstruct_from_files(
    file_paths: List[Path],
    weights: Optional[Dict[str, float]] = None,
) -> Tuple[FragmentGraph, List[ReconstructionCandidate]]:
    """
    High-level convenience: ingest a list of files and reconstruct.
    Files are read read-only. No ordering assumption from filenames.
    """
    from backend.fragment_ingestor import ingest_file

    records: List[FragmentRecord] = []
    frag_bytes: Dict[str, bytes] = {}

    for path in file_paths:
        rec = ingest_file(Path(path))
        raw = Path(path).read_bytes()   # read separately — ingest is already read-only
        records.append(rec)
        frag_bytes[rec.fragment_id] = raw

    return reconstruct_fragments(records, frag_bytes, weights)


def reconstruct_from_directory(
    directory: Path,
    weights: Optional[Dict[str, float]] = None,
) -> Tuple[FragmentGraph, List[ReconstructionCandidate]]:
    """
    Ingest all files in directory and reconstruct.
    File order is determined by the graph, NOT by filename or directory listing order.
    """
    directory = Path(directory)
    files = sorted(p for p in directory.iterdir() if p.is_file())
    return reconstruct_from_files(files, weights)
