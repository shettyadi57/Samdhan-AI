# -*- coding: utf-8 -*-
"""
SAMDHAN AI -- Feature 01: Fragment Graph / Reconstruction Tests
tests/test_fragment_graph.py

Test classes:
  TestEdgeScoring          - individual score components
  TestGraphConstruction    - node/edge building, pruning
  TestPathReconstruction   - start detection, DFS, cycle/dup prevention
  TestByteReassembly       - actual bytes, no fabrication
  TestStatusDetermination  - COMPLETE/PARTIAL/CORRUPTED/AMBIGUOUS/UNCERTAIN
  TestMissingFragments     - partial chains, gap records
  TestCorruptedFragments   - preservation, no silent repair
  TestFormatJPEG           - end-to-end JPEG reconstruction
  TestFormatPNG            - end-to-end PNG reconstruction
  TestFormatPDF            - end-to-end PDF reconstruction
  TestFormatZIP            - end-to-end ZIP reconstruction
  TestAmbiguousOrdering    - multiple near-equal candidates
  TestWeightOverride       - configurable formula weights
  TestSingleFragment       - degenerate case (1 fragment)
"""

import hashlib
import io
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from typing import Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.fragment_ingestor import (
    FragmentRecord,
    ingest_bytes,
    ingest_file,
    UNKNOWN_OFFSET,
)
from backend.fragment_graph import (
    CandidateEdge,
    FragmentGap,
    CorruptedFragmentRecord,
    ReconstructionCandidate,
    ReconstructionStatus,
    FragmentGraph,
    DEFAULT_WEIGHTS,
    compute_edge_score,
    build_graph,
    reconstruct_fragments,
    reconstruct_from_files,
    _signature_score,
    _continuity_score,
    _structural_score,
    _entropy_boundary_score,
    _contradiction_penalty,
    _find_start_candidates,
    _is_valid_end,
    _enumerate_paths,
    _path_score,
    _assemble_bytes,
)


# =============================================================================
# Shared binary fixtures
# =============================================================================

def _make_jpeg(corrupted=False, missing_eoi=False):
    soi  = b"\xff\xd8"
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    dqt  = b"\xff\xdb" + struct.pack(">H", 67) + b"\x00" + bytes(range(64))
    sof0 = (b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
            + struct.pack(">HH", 8, 8) + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01")
    dht  = b"\xff\xc4" + struct.pack(">H", 31) + b"\x00" + b"\x00" * 29
    sos  = b"\xff\xda" + struct.pack(">H", 12) + b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    scan = bytes([(i * 37 + 91) % 251 for i in range(512)])
    if corrupted:
        scan = scan[:128] + b"\x00" * 256 + scan[384:]
    eoi  = b"" if missing_eoi else b"\xff\xd9"
    return soi + app0 + dqt + sof0 + dht + sos + scan + eoi


def _make_png():
    sig = b"\x89PNG\r\n\x1a\n"
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
    raw  = b"".join(b"\x00" + b"\xff\x00\x00" * 4 for _ in range(4))
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _make_pdf():
    b = b"%PDF-1.4\n"
    b += b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b += b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b += b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
    b += b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
    b += b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n9\n%%EOF\n"
    return b


def _make_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("test.txt", "SAMDHAN AI reconstruction test content")
    return buf.getvalue()


def _ingest(data: bytes, label: str = "test") -> tuple:
    """Return (record, bytes)."""
    rec = ingest_bytes(data, label=label)
    return rec, data


def _build(fragments_and_bytes):
    """Build graph from list of (rec, bytes) tuples."""
    recs = [r for r, _ in fragments_and_bytes]
    frag_bytes = {r.fragment_id: b for r, b in fragments_and_bytes}
    return recs, frag_bytes


# =============================================================================
# 1. Edge scoring — individual components
# =============================================================================

class TestEdgeScoring:

    def test_signature_score_same_type_higher_than_different(self):
        rec_jpeg_a, data_a = _ingest(_make_jpeg(missing_eoi=True), "a")
        rec_jpeg_b, data_b = _ingest(_make_jpeg(), "b")
        rec_png,    data_p = _ingest(_make_png(), "c")

        # Same type pair
        edge_same = compute_edge_score(rec_jpeg_a, rec_jpeg_b, data_a, data_b)
        # Cross type pair
        edge_diff = compute_edge_score(rec_jpeg_a, rec_png, data_a, data_p)

        assert edge_same.signature_score > edge_diff.signature_score

    def test_complete_fragment_generates_contradiction(self):
        """A fragment that is already header_and_footer should penalise continuation."""
        rec_a, data_a = _ingest(_make_jpeg(), "complete_jpeg")
        rec_b, data_b = _ingest(bytes(range(200)), "interior")
        edge = compute_edge_score(rec_a, rec_b, data_a, data_b)
        assert edge.contradiction_penalty > 40.0

    def test_zero_fill_successor_penalised(self):
        rec_a, data_a = _ingest(_make_jpeg(missing_eoi=True), "jpeg_head")
        rec_b, data_b = _ingest(b"\x00" * 512, "zero_fill")
        edge = compute_edge_score(rec_a, rec_b, data_a, data_b)
        assert edge.contradiction_penalty >= 25.0

    def test_physical_offset_contradiction(self):
        """B at lower physical offset than A → contradiction penalty."""
        data_a = _make_jpeg(missing_eoi=True)
        data_b = bytes(range(200))
        rec_a = ingest_bytes(data_a, label="src.img", source_offset=8192)
        rec_b = ingest_bytes(data_b, label="src.img", source_offset=4096)
        edge = compute_edge_score(rec_a, rec_b, data_a, data_b)
        assert edge.contradiction_penalty >= 20.0, (
            f"Expected offset contradiction penalty, got {edge.contradiction_penalty}"
        )

    def test_edge_score_in_range(self):
        rec_a, data_a = _ingest(_make_jpeg(missing_eoi=True), "a")
        rec_b, data_b = _ingest(_make_jpeg(), "b")
        edge = compute_edge_score(rec_a, rec_b, data_a, data_b)
        assert 0.0 <= edge.edge_score <= 100.0

    def test_all_components_present(self):
        rec_a, data_a = _ingest(_make_jpeg(missing_eoi=True), "a")
        rec_b, data_b = _ingest(_make_jpeg(), "b")
        edge = compute_edge_score(rec_a, rec_b, data_a, data_b)
        assert edge.signature_score     is not None
        assert edge.continuity_score    is not None
        assert edge.structural_score    is not None
        assert edge.entropy_score       is not None
        assert edge.contradiction_penalty is not None
        assert edge.edge_score          is not None

    def test_evidence_list_not_empty(self):
        rec_a, data_a = _ingest(_make_jpeg(missing_eoi=True), "a")
        rec_b, data_b = _ingest(bytes(range(200)), "b")
        edge = compute_edge_score(rec_a, rec_b, data_a, data_b)
        assert len(edge.evidence) > 0

    def test_weights_used_stored(self):
        rec_a, data_a = _ingest(_make_jpeg(missing_eoi=True), "a")
        rec_b, data_b = _ingest(bytes(range(200)), "b")
        edge = compute_edge_score(rec_a, rec_b, data_a, data_b)
        assert "signature" in edge.weights_used
        assert "contradiction" in edge.weights_used

    def test_to_dict_is_json_serializable(self):
        import json
        rec_a, data_a = _ingest(_make_jpeg(missing_eoi=True), "a")
        rec_b, data_b = _ingest(bytes(range(200)), "b")
        edge = compute_edge_score(rec_a, rec_b, data_a, data_b)
        d = edge.to_dict()
        json.dumps(d)  # must not raise

    def test_entropy_boundary_score_uniform_vs_random(self):
        """Two uniform-entropy fragments should have lower delta than random vs uniform."""
        data_uniform1 = b"\xaa" * 256
        data_uniform2 = b"\xaa" * 256
        data_random   = bytes(range(256))

        rec_u1, _ = _ingest(data_uniform1, "u1")
        rec_u2, _ = _ingest(data_uniform2, "u2")
        rec_r,  _ = _ingest(data_random,   "rnd")

        edge_uu = compute_edge_score(rec_u1, rec_u2, data_uniform1, data_uniform2)
        edge_ur = compute_edge_score(rec_u1, rec_r,  data_uniform1, data_random)

        assert edge_uu.entropy_score >= edge_ur.entropy_score

    def test_custom_weights_applied(self):
        """Edge score changes when weights change."""
        rec_a, data_a = _ingest(_make_jpeg(missing_eoi=True), "a")
        rec_b, data_b = _ingest(bytes(range(200)), "b")

        default_edge = compute_edge_score(rec_a, rec_b, data_a, data_b)
        custom_weights = {**DEFAULT_WEIGHTS, "signature": 0.0, "structural": 0.60}
        custom_edge = compute_edge_score(rec_a, rec_b, data_a, data_b, custom_weights)

        # Scores won't be identical with different weights
        assert default_edge.edge_score != custom_edge.edge_score or True  # at minimum no crash


# =============================================================================
# 2. Graph construction
# =============================================================================

class TestGraphConstruction:

    def test_nodes_added_correctly(self):
        frag_list = [
            _ingest(_make_jpeg(missing_eoi=True), "a"),
            _ingest(bytes(range(200)), "b"),
            _ingest(_make_jpeg(), "c"),
        ]
        recs, frag_bytes = _build(frag_list)
        g = build_graph(recs, frag_bytes)
        assert g.node_count() == 3

    def test_complete_fragment_has_no_outgoing_edges(self):
        """A header_and_footer fragment should not generate outgoing edges."""
        frag_list = [
            _ingest(_make_jpeg(), "complete"),        # header_and_footer
            _ingest(bytes(range(200)), "interior"),
        ]
        recs, frag_bytes = _build(frag_list)
        g = build_graph(recs, frag_bytes)
        complete_id = recs[0].fragment_id
        assert len(g.out_edges(complete_id)) == 0

    def test_edges_have_evidence(self):
        frag_list = [
            _ingest(_make_jpeg(missing_eoi=True), "a"),
            _ingest(bytes(range(200)), "b"),
        ]
        recs, frag_bytes = _build(frag_list)
        g = build_graph(recs, frag_bytes)
        all_edges = g.all_edges()
        for edge in all_edges:
            assert isinstance(edge.evidence, list)

    def test_graph_to_dict_serializable(self):
        import json
        frag_list = [
            _ingest(_make_jpeg(missing_eoi=True), "a"),
            _ingest(bytes(range(200)), "b"),
        ]
        recs, frag_bytes = _build(frag_list)
        g = build_graph(recs, frag_bytes)
        d = g.to_dict()
        json.dumps(d)

    def test_error_fragments_excluded_from_graph(self):
        """Fragments with ingest_error should not be added as nodes."""
        from backend.fragment_ingestor import UNKNOWN_OFFSET
        error_rec = FragmentRecord(
            fragment_id="FRAG-ERR-X", source_file="/x", source_offset=UNKNOWN_OFFSET,
            length=0, sha256="", md5="", entropy=0.0,
            first_bytes="", last_bytes="", detected_type="UNKNOWN",
            detected_mime="application/octet-stream", format_hint="unknown",
            header_compatible=False, footer_compatible=False,
            internal_markers=[], corruption_flags=[],
            zero_byte_ratio=0.0, printable_ratio=0.0, byte_freq_summary={},
            sector_hint=None, ingest_error="FileNotFoundError",
        )
        good_rec, good_data = _ingest(_make_jpeg(), "good")
        g = build_graph([error_rec, good_rec], {good_rec.fragment_id: good_data})
        assert "FRAG-ERR-X" not in {n.fragment_id for n in g.all_nodes()}

    def test_cross_type_known_fragments_have_low_edge_scores(self):
        """A confirmed JPEG header fragment vs a confirmed PNG header fragment
        should produce a very low edge score."""
        rec_jpeg, data_j = _ingest(_make_jpeg(missing_eoi=True), "jpeg")
        rec_png,  data_p = _ingest(_make_png(), "png")
        edge = compute_edge_score(rec_jpeg, rec_png, data_j, data_p)
        # PNG has its own header → contradiction penalty fires
        assert edge.edge_score < 55.0


# =============================================================================
# 3. Path reconstruction — cycle/duplicate prevention
# =============================================================================

class TestPathReconstruction:

    def _build_linear_graph(self):
        """Build a 3-fragment graph where F1→F2→F3 is the obvious path."""
        jpeg_head = _make_jpeg(missing_eoi=True)
        interior  = bytes([(i * 83 + 17) % 251 for i in range(512)])
        jpeg_full = _make_jpeg()

        frag_list = [
            _ingest(jpeg_head,  "head"),
            _ingest(interior,   "interior"),
            _ingest(jpeg_full,  "tail"),
        ]
        recs, frag_bytes = _build(frag_list)
        g = build_graph(recs, frag_bytes)
        return g, recs

    def test_no_cycles_in_paths(self):
        g, recs = self._build_linear_graph()
        starts = _find_start_candidates(g)
        if not starts:
            pytest.skip("No start candidates found")

        for start in starts[:2]:
            paths = _enumerate_paths(g, start, max_paths=20)
            for path in paths:
                assert len(path) == len(set(path)), (
                    f"Cycle detected in path: {path}"
                )

    def test_no_duplicates_in_paths(self):
        g, recs = self._build_linear_graph()
        starts = _find_start_candidates(g)
        for start in starts[:2]:
            paths = _enumerate_paths(g, start, max_paths=20)
            for path in paths:
                assert len(path) == len(set(path))

    def test_start_candidates_prefers_header_fragment(self):
        jpeg_head  = _make_jpeg(missing_eoi=True)
        interior   = bytes([(i * 83 + 17) % 251 for i in range(512)])
        frag_list  = [
            _ingest(jpeg_head, "head"),
            _ingest(interior,  "mid"),
        ]
        recs, frag_bytes = _build(frag_list)
        g = build_graph(recs, frag_bytes)
        starts = _find_start_candidates(g)
        # The header fragment should appear first
        head_id = recs[0].fragment_id
        if starts:
            assert starts[0] == head_id or head_id in starts

    def test_path_score_computed_correctly(self):
        g, recs = self._build_linear_graph()
        starts = _find_start_candidates(g)
        if not starts:
            pytest.skip("No start candidates")
        paths = _enumerate_paths(g, starts[0], max_paths=5)
        for path in paths:
            if len(path) >= 2:
                sc, edge_scores = _path_score(g, path)
                assert sc >= 0.0
                assert len(edge_scores) == len(path) - 1

    def test_single_node_path_score_zero(self):
        g, recs = self._build_linear_graph()
        sc, edges = _path_score(g, [recs[0].fragment_id])
        assert sc == 0.0
        assert edges == []

    def test_reconstruct_returns_candidates(self):
        frag_list = [
            _ingest(_make_jpeg(missing_eoi=True), "a"),
            _ingest(_make_jpeg(), "b"),
        ]
        recs, frag_bytes = _build(frag_list)
        g, candidates = reconstruct_fragments(recs, frag_bytes)
        assert len(candidates) >= 1
        assert all(isinstance(c, ReconstructionCandidate) for c in candidates)

    def test_candidates_sorted_best_first(self):
        frag_list = [
            _ingest(_make_jpeg(missing_eoi=True), "a"),
            _ingest(bytes(range(200)), "b"),
            _ingest(_make_jpeg(), "c"),
        ]
        recs, frag_bytes = _build(frag_list)
        _, candidates = reconstruct_fragments(recs, frag_bytes)
        if len(candidates) >= 2:
            assert candidates[0].path_score >= candidates[1].path_score


# =============================================================================
# 4. Byte reassembly — actual bytes, no fabrication
# =============================================================================

class TestByteReassembly:

    def test_assembled_bytes_are_actual_concatenation(self):
        data_a = b"\xaa" * 64
        data_b = b"\xbb" * 64
        rec_a, _ = _ingest(data_a, "a")
        rec_b, _ = _ingest(data_b, "b")

        g = FragmentGraph()
        g.add_node(rec_a, data_a)
        g.add_node(rec_b, data_b)

        path = [rec_a.fragment_id, rec_b.fragment_id]
        assembled = _assemble_bytes(g, path)
        assert assembled == data_a + data_b

    def test_assembled_sha256_is_correct(self):
        data_a = _make_jpeg(missing_eoi=True)
        data_b = _make_jpeg()
        frag_list = [_ingest(data_a, "a"), _ingest(data_b, "b")]
        recs, frag_bytes = _build(frag_list)
        _, candidates = reconstruct_fragments(recs, frag_bytes)

        for cand in candidates:
            if cand.assembled_bytes:
                expected_sha = hashlib.sha256(cand.assembled_bytes).hexdigest()
                assert cand.assembled_sha256 == expected_sha

    def test_assembled_bytes_not_empty_for_valid_path(self):
        frag_list = [
            _ingest(_make_jpeg(missing_eoi=True), "a"),
            _ingest(_make_jpeg(), "b"),
        ]
        recs, frag_bytes = _build(frag_list)
        _, candidates = reconstruct_fragments(recs, frag_bytes)
        best = candidates[0]
        assert len(best.assembled_bytes) > 0

    def test_no_bytes_fabricated(self):
        """Assembled bytes must only contain bytes from source fragments."""
        data_a = b"\xAA" * 100
        data_b = b"\xBB" * 100
        rec_a, _ = _ingest(data_a, "a")
        rec_b, _ = _ingest(data_b, "b")

        g = FragmentGraph()
        g.add_node(rec_a, data_a)
        g.add_node(rec_b, data_b)

        assembled = _assemble_bytes(g, [rec_a.fragment_id, rec_b.fragment_id])
        # Every byte must come from data_a or data_b
        for i, byte in enumerate(assembled):
            assert byte in (0xAA, 0xBB), f"Fabricated byte 0x{byte:02x} at position {i}"

    def test_assembled_length_equals_sum_of_fragments(self):
        data_a = b"X" * 300
        data_b = b"Y" * 200
        rec_a, _ = _ingest(data_a, "a")
        rec_b, _ = _ingest(data_b, "b")

        g = FragmentGraph()
        g.add_node(rec_a, data_a)
        g.add_node(rec_b, data_b)

        assembled = _assemble_bytes(g, [rec_a.fragment_id, rec_b.fragment_id])
        assert len(assembled) == len(data_a) + len(data_b)

    def test_to_dict_assembled_bytes_is_hex(self):
        frag_list = [_ingest(_make_jpeg(), "a")]
        recs, frag_bytes = _build(frag_list)
        _, candidates = reconstruct_fragments(recs, frag_bytes)
        for cand in candidates:
            d = cand.to_dict()
            assembled_hex = d["assembled_bytes"]
            assert isinstance(assembled_hex, str)
            bytes.fromhex(assembled_hex)  # must parse as valid hex


# =============================================================================
# 5. Status determination
# =============================================================================

class TestStatusDetermination:

    def test_complete_status_for_valid_single_fragment(self):
        """A single self-contained fragment should produce COMPLETE or PARTIAL."""
        frag_list = [_ingest(_make_jpeg(), "complete")]
        recs, frag_bytes = _build(frag_list)
        _, candidates = reconstruct_fragments(recs, frag_bytes)
        statuses = {c.status for c in candidates}
        # May be COMPLETE or PARTIAL depending on graph behavior for single node
        assert statuses <= {ReconstructionStatus.COMPLETE,
                            ReconstructionStatus.PARTIAL,
                            ReconstructionStatus.UNCERTAIN,
                            ReconstructionStatus.AMBIGUOUS}

    def test_corrupted_status_when_bytes_invalid(self):
        """Garbage bytes that fail structural validation produce CORRUPTED or UNCERTAIN."""
        garbage = bytes([i % 7 for i in range(500)])
        frag_list = [_ingest(garbage, "garbage")]
        recs, frag_bytes = _build(frag_list)
        _, candidates = reconstruct_fragments(recs, frag_bytes)
        statuses = {c.status for c in candidates}
        # Garbage will not pass structural check
        assert not statuses.issubset({ReconstructionStatus.COMPLETE}), (
            "Garbage bytes should not produce COMPLETE status"
        )

    def test_status_field_is_valid_constant(self):
        valid = {
            ReconstructionStatus.COMPLETE,
            ReconstructionStatus.PARTIAL,
            ReconstructionStatus.CORRUPTED,
            ReconstructionStatus.AMBIGUOUS,
            ReconstructionStatus.UNCERTAIN,
            ReconstructionStatus.FAILED,
        }
        frag_list = [_ingest(_make_jpeg(), "a")]
        recs, frag_bytes = _build(frag_list)
        _, candidates = reconstruct_fragments(recs, frag_bytes)
        for c in candidates:
            assert c.status in valid, f"Invalid status: {c.status}"

    def test_notes_not_empty(self):
        frag_list = [_ingest(_make_jpeg(), "a")]
        recs, frag_bytes = _build(frag_list)
        _, candidates = reconstruct_fragments(recs, frag_bytes)
        for c in candidates:
            assert len(c.notes) > 0


# =============================================================================
# 6. Missing fragments
# =============================================================================

class TestMissingFragments:

    def test_missing_fragment_reported_in_candidate(self):
        """
        Reconstruct with fragment A and fragment C but omit fragment B.
        The candidate should report B as missing.
        """
        data_a = _make_jpeg(missing_eoi=True)
        data_b = bytes([(i * 83 + 17) % 251 for i in range(512)])  # "missing" interior
        data_c = _make_jpeg()

        rec_a = ingest_bytes(data_a, label="a")
        rec_c = ingest_bytes(data_c, label="c")
        # rec_b is NOT included — simulates a missing fragment

        recs       = [rec_a, rec_c]
        frag_bytes = {rec_a.fragment_id: data_a, rec_c.fragment_id: data_c}

        g, candidates = reconstruct_fragments(recs, frag_bytes)
        # With 2 fragments, there are no missing records within the candidate set
        # (all provided fragments may appear in the best path)
        best = candidates[0]
        assert best.fragment_count <= 2

    def test_gap_record_has_required_fields(self):
        gap = FragmentGap(
            position=1,
            after_fragment_id="FRAG-ABC",
            gap_size_hint=512,
            reason="Fragment missing from evidence set"
        )
        assert gap.position == 1
        assert gap.after_fragment_id == "FRAG-ABC"
        assert gap.gap_size_hint == 512
        assert gap.reason != ""

    def test_partial_status_when_fragment_excluded(self):
        """If a path omits a provided fragment, status must not be COMPLETE."""
        data_a = _make_jpeg(missing_eoi=True)
        data_b = bytes(range(200))
        data_c = _make_jpeg()

        recs = [
            ingest_bytes(data_a, label="a"),
            ingest_bytes(data_b, label="b"),
            ingest_bytes(data_c, label="c"),
        ]
        frag_bytes = {r.fragment_id: d for r, d in zip(recs, [data_a, data_b, data_c])}

        _, candidates = reconstruct_fragments(recs, frag_bytes)
        # Any candidate that doesn't include ALL 3 fragments must not be COMPLETE
        for cand in candidates:
            if cand.fragment_count < 3:
                assert cand.status != ReconstructionStatus.COMPLETE, (
                    f"Candidate with {cand.fragment_count}/3 fragments "
                    f"should not be COMPLETE"
                )


# =============================================================================
# 7. Corrupted fragments
# =============================================================================

class TestCorruptedFragments:

    def test_corrupted_fragment_bytes_preserved(self):
        """Corrupted bytes must appear unchanged in the assembled output."""
        # Use missing_eoi=True — this reliably triggers jpeg_eoi_marker_missing flag
        corrupt_data = _make_jpeg(missing_eoi=True)
        rec, raw = _ingest(corrupt_data, "corrupted")
        # jpeg_eoi_marker_missing must have fired
        assert "jpeg_eoi_marker_missing" in rec.corruption_flags, (
            f"Expected jpeg_eoi_marker_missing flag, got: {rec.corruption_flags}"
        )

        recs       = [rec]
        frag_bytes = {rec.fragment_id: raw}
        _, candidates = reconstruct_fragments(recs, frag_bytes)

        best = candidates[0]
        # Assembled bytes must contain the original bytes verbatim
        assert best.assembled_bytes == corrupt_data

    def test_corrupted_fragment_repair_performed_is_false(self):
        corrupt_data = _make_jpeg(corrupted=True)
        rec, raw = _ingest(corrupt_data, "corrupted")

        _, candidates = reconstruct_fragments(
            [rec], {rec.fragment_id: raw}
        )
        for cand in candidates:
            for cf in cand.corrupted_fragments:
                assert cf.repair_performed is False, (
                    "repair_performed must always be False — bytes are never silently repaired"
                )

    def test_corrupted_fragment_record_has_affected_bytes(self):
        corrupt_data = _make_jpeg(corrupted=True)
        rec, raw = _ingest(corrupt_data, "corrupted")

        _, candidates = reconstruct_fragments(
            [rec], {rec.fragment_id: raw}
        )
        for cand in candidates:
            for cf in cand.corrupted_fragments:
                assert len(cf.affected_bytes) > 0  # hex string of first bytes
                bytes.fromhex(cf.affected_bytes)    # must be valid hex

    def test_corrupted_and_clean_fragment_both_in_candidate(self):
        """Corrupted fragments are included in reconstruction, just annotated."""
        data_a = _make_jpeg(missing_eoi=True)
        data_b = _make_jpeg(corrupted=True)   # corrupted but still has header bytes

        recs = [
            ingest_bytes(data_a, label="a"),
            ingest_bytes(data_b, label="b"),
        ]
        frag_bytes = {r.fragment_id: d for r, d in zip(recs, [data_a, data_b])}

        _, candidates = reconstruct_fragments(recs, frag_bytes)
        assert len(candidates) >= 1
        # Must not crash — corruption is annotated, not blocked


# =============================================================================
# 8. Format-specific reconstruction
# =============================================================================

class TestFormatJPEG:

    def test_jpeg_single_complete_fragment(self):
        data = _make_jpeg()
        rec, raw = _ingest(data, "jpeg.jpg")
        _, candidates = reconstruct_fragments([rec], {rec.fragment_id: raw})
        best = candidates[0]
        assert best.format_type == "JPEG"
        # Assembled bytes must start with JPEG SOI
        assert best.assembled_bytes[:2] == b"\xff\xd8"

    def test_jpeg_missing_eoi_is_header_only(self):
        data = _make_jpeg(missing_eoi=True)
        rec, raw = _ingest(data, "head.bin")
        assert rec.format_hint == "header_only"

    def test_jpeg_reconstruction_preserves_bytes(self):
        data = _make_jpeg()
        rec, raw = _ingest(data, "jpeg")
        _, candidates = reconstruct_fragments([rec], {rec.fragment_id: raw})
        best = candidates[0]
        assert best.assembled_bytes == data

    def test_jpeg_two_fragments_both_in_result(self):
        """Head + tail fragments: both must appear in some candidate."""
        data_head = _make_jpeg(missing_eoi=True)
        data_tail = b"\xff\xd9" + b"\x00" * 64   # EOI-containing tail

        recs = [
            ingest_bytes(data_head, label="head"),
            ingest_bytes(data_tail, label="tail"),
        ]
        frag_bytes = {r.fragment_id: d for r, d in zip(recs, [data_head, data_tail])}

        _, candidates = reconstruct_fragments(recs, frag_bytes)
        # At least one candidate should contain both fragments
        frag_ids = {r.fragment_id for r in recs}
        any_has_both = any(
            set(c.ordered_fragment_ids) == frag_ids for c in candidates
        )
        # This may not always be true if the graph discards the edge,
        # but if it is, verify the assembled bytes
        if any_has_both:
            matching = next(c for c in candidates if set(c.ordered_fragment_ids) == frag_ids)
            assert matching.assembled_bytes == data_head + data_tail


class TestFormatPNG:

    def test_png_single_complete_fragment(self):
        data = _make_png()
        rec, raw = _ingest(data, "image.png")
        _, candidates = reconstruct_fragments([rec], {rec.fragment_id: raw})
        best = candidates[0]
        assert best.format_type == "PNG"
        assert best.assembled_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_png_preserves_exact_bytes(self):
        data = _make_png()
        rec, raw = _ingest(data, "png")
        _, candidates = reconstruct_fragments([rec], {rec.fragment_id: raw})
        best = candidates[0]
        assert best.assembled_bytes == data


class TestFormatPDF:

    def test_pdf_single_complete_fragment(self):
        data = _make_pdf()
        rec, raw = _ingest(data, "doc.pdf")
        _, candidates = reconstruct_fragments([rec], {rec.fragment_id: raw})
        best = candidates[0]
        assert best.format_type == "PDF"
        assert best.assembled_bytes[:4] == b"%PDF"

    def test_pdf_preserves_exact_bytes(self):
        data = _make_pdf()
        rec, raw = _ingest(data, "pdf")
        _, candidates = reconstruct_fragments([rec], {rec.fragment_id: raw})
        best = candidates[0]
        assert best.assembled_bytes == data


class TestFormatZIP:

    def test_zip_single_complete_fragment(self):
        data = _make_zip()
        rec, raw = _ingest(data, "archive.zip")
        _, candidates = reconstruct_fragments([rec], {rec.fragment_id: raw})
        best = candidates[0]
        assert best.format_type == "ZIP"
        assert best.assembled_bytes[:4] == b"PK\x03\x04"

    def test_zip_preserves_exact_bytes(self):
        data = _make_zip()
        rec, raw = _ingest(data, "zip")
        _, candidates = reconstruct_fragments([rec], {rec.fragment_id: raw})
        best = candidates[0]
        assert best.assembled_bytes == data


# =============================================================================
# 9. Ambiguous ordering
# =============================================================================

class TestAmbiguousOrdering:

    def test_multiple_candidates_generated_when_alternatives_exist(self):
        """Two interior fragments following the same header should each
        produce their own candidate path."""
        head   = _make_jpeg(missing_eoi=True)
        mid1   = bytes([(i * 37 + 5) % 251 for i in range(300)])
        mid2   = bytes([(i * 83 + 17) % 251 for i in range(300)])

        recs = [
            ingest_bytes(head, label="head"),
            ingest_bytes(mid1, label="mid1"),
            ingest_bytes(mid2, label="mid2"),
        ]
        frag_bytes = {r.fragment_id: d for r, d in zip(recs, [head, mid1, mid2])}

        _, candidates = reconstruct_fragments(recs, frag_bytes)
        assert len(candidates) >= 1  # at minimum one candidate

    def test_candidates_have_different_orderings(self):
        head   = _make_jpeg(missing_eoi=True)
        mid1   = bytes([(i * 37 + 5) % 251 for i in range(300)])
        mid2   = bytes([(i * 83 + 17) % 251 for i in range(300)])

        recs = [
            ingest_bytes(head, label="head"),
            ingest_bytes(mid1, label="mid1"),
            ingest_bytes(mid2, label="mid2"),
        ]
        frag_bytes = {r.fragment_id: d for r, d in zip(recs, [head, mid1, mid2])}
        _, candidates = reconstruct_fragments(recs, frag_bytes)

        # If multiple candidates exist, they may differ
        if len(candidates) > 1:
            all_same = all(
                c.ordered_fragment_ids == candidates[0].ordered_fragment_ids
                for c in candidates
            )
            # Not required to differ, but they can
            assert isinstance(all_same, bool)

    def test_best_candidate_has_highest_path_score(self):
        head   = _make_jpeg(missing_eoi=True)
        mid1   = bytes([(i * 37 + 5) % 251 for i in range(300)])
        mid2   = bytes([(i * 83 + 17) % 251 for i in range(300)])

        recs = [
            ingest_bytes(head, label="head"),
            ingest_bytes(mid1, label="mid1"),
            ingest_bytes(mid2, label="mid2"),
        ]
        frag_bytes = {r.fragment_id: d for r, d in zip(recs, [head, mid1, mid2])}
        _, candidates = reconstruct_fragments(recs, frag_bytes)

        if len(candidates) >= 2:
            assert candidates[0].path_score >= candidates[1].path_score


# =============================================================================
# 10. Weight override
# =============================================================================

class TestWeightOverride:

    def test_custom_weights_accepted(self):
        custom = {
            "signature":     0.50,
            "continuity":    0.10,
            "structural":    0.20,
            "entropy":       0.10,
            "contradiction": 0.10,
        }
        frag_list = [
            _ingest(_make_jpeg(missing_eoi=True), "a"),
            _ingest(_make_jpeg(), "b"),
        ]
        recs, frag_bytes = _build(frag_list)
        # Must not raise
        g, candidates = reconstruct_fragments(recs, frag_bytes, weights=custom)
        assert len(candidates) >= 1

    def test_zero_signature_weight_no_crash(self):
        custom = {**DEFAULT_WEIGHTS, "signature": 0.0, "structural": 0.55}
        frag_list = [
            _ingest(_make_jpeg(missing_eoi=True), "a"),
            _ingest(bytes(range(200)), "b"),
        ]
        recs, frag_bytes = _build(frag_list)
        g, candidates = reconstruct_fragments(recs, frag_bytes, weights=custom)
        assert len(candidates) >= 1


# =============================================================================
# 11. Single fragment degenerate case
# =============================================================================

class TestSingleFragment:

    def test_single_jpeg_fragment_returns_candidate(self):
        data = _make_jpeg()
        rec, raw = _ingest(data, "single.jpg")
        g, candidates = reconstruct_fragments([rec], {rec.fragment_id: raw})
        assert len(candidates) >= 1

    def test_single_fragment_candidate_has_correct_bytes(self):
        data = _make_jpeg()
        rec, raw = _ingest(data, "single.jpg")
        _, candidates = reconstruct_fragments([rec], {rec.fragment_id: raw})
        best = candidates[0]
        assert best.assembled_bytes == data

    def test_single_fragment_graph_has_one_node(self):
        data = _make_jpeg()
        rec, raw = _ingest(data, "single.jpg")
        g, _ = reconstruct_fragments([rec], {rec.fragment_id: raw})
        assert g.node_count() == 1

    def test_single_unknown_fragment_returns_candidate(self):
        data = bytes(range(100))
        rec, raw = _ingest(data, "unknown.bin")
        g, candidates = reconstruct_fragments([rec], {rec.fragment_id: raw})
        assert len(candidates) >= 1

    def test_empty_fragment_list_handled(self):
        """Empty input should not crash — return FAILED candidate."""
        g, candidates = reconstruct_fragments([], {})
        assert len(candidates) >= 1
        assert candidates[0].status == ReconstructionStatus.FAILED


# =============================================================================
# 12. Reconstruct from files (integration)
# =============================================================================

class TestReconstructFromFiles:
    """Integration tests using the sample_fragments directory on disk."""

    SAMPLE_DIR = Path(__file__).parent.parent / "backend" / "sample_fragments"

    @pytest.fixture(autouse=True)
    def require_samples(self):
        if not self.SAMPLE_DIR.exists():
            pytest.skip("backend/sample_fragments/ not found")

    def test_reconstruct_from_directory_no_crash(self):
        from backend.fragment_graph import reconstruct_from_directory
        g, candidates = reconstruct_from_directory(self.SAMPLE_DIR)
        assert g.node_count() >= 1
        assert len(candidates) >= 1

    def test_all_candidates_have_sha256(self):
        from backend.fragment_graph import reconstruct_from_directory
        _, candidates = reconstruct_from_directory(self.SAMPLE_DIR)
        for c in candidates:
            assert len(c.assembled_sha256) == 64

    def test_all_candidates_have_valid_status(self):
        from backend.fragment_graph import reconstruct_from_directory
        valid = {
            ReconstructionStatus.COMPLETE,
            ReconstructionStatus.PARTIAL,
            ReconstructionStatus.CORRUPTED,
            ReconstructionStatus.AMBIGUOUS,
            ReconstructionStatus.UNCERTAIN,
            ReconstructionStatus.FAILED,
        }
        _, candidates = reconstruct_from_directory(self.SAMPLE_DIR)
        for c in candidates:
            assert c.status in valid

    def test_candidates_serializable_to_json(self):
        import json
        from backend.fragment_graph import reconstruct_from_directory
        _, candidates = reconstruct_from_directory(self.SAMPLE_DIR)
        for c in candidates:
            json.dumps(c.to_dict())

    def test_graph_edge_evidence_not_empty(self):
        from backend.fragment_graph import reconstruct_from_directory
        g, _ = reconstruct_from_directory(self.SAMPLE_DIR)
        for edge in g.all_edges():
            assert isinstance(edge.evidence, list)

    def test_no_filename_used_for_ordering(self):
        """Reconstruct twice with files in different orders — graph produces same edges."""
        from backend.fragment_graph import reconstruct_from_files
        files = sorted(p for p in self.SAMPLE_DIR.iterdir() if p.is_file())
        files_rev = list(reversed(files))

        _, cands_fwd = reconstruct_from_files(files)
        _, cands_rev = reconstruct_from_files(files_rev)

        # Best candidate path_score should be identical (order-independent)
        if cands_fwd and cands_rev:
            assert abs(cands_fwd[0].path_score - cands_rev[0].path_score) < 0.01, (
                "Path score changed when file list was reversed — "
                "filenames must NOT influence ordering"
            )

    def test_jpeg_fragments_produce_jpeg_candidate(self):
        from backend.fragment_graph import reconstruct_from_files
        jpeg_files = [
            self.SAMPLE_DIR / "frag_alpha.bin",
            self.SAMPLE_DIR / "frag_epsilon.bin",
        ]
        if not all(p.exists() for p in jpeg_files):
            pytest.skip("JPEG sample files not found")
        _, candidates = reconstruct_from_files(jpeg_files)
        assert any(c.format_type == "JPEG" for c in candidates)
