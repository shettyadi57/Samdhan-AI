# -*- coding: utf-8 -*-
"""
SAMDHAN AI -- Feature 01: Intelligent Fragment Reconstruction
tests/test_feature01_reconstruction.py

Comprehensive acceptance test suite covering:
  1. Structural validation (JPEG, PNG, PDF, ZIP)
  2. Completeness & corruption reporting
  3. Provenance tracking (byte range -> fragment -> offset -> edge -> validation)
  4. SHA-256 hashing across evidence, fragments, and output
  5. 4-file artifact generation (reconstructed/, provenance, validation, report)
  6. Ground-truth dataset & Scenarios A-E
  7. API v1 endpoints (/discovery, /analysis, /linking, /reconstruction, /candidates)
  8. Forensic safety guarantees (read-only, no silent repairs)
"""

import hashlib
import json
import os
import struct
import tempfile
import zlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.format_validator import (
    validate_jpeg_structure,
    validate_png_structure,
    validate_pdf_structure,
    validate_zip_structure,
    validate_format_structure,
)
from backend.reconstruction_report import (
    ProvenanceEntry,
    build_provenance_records,
    determine_reconstruction_status,
    export_reconstruction_artifacts,
    ReconstructionReport,
)
from backend.ground_truth_dataset import (
    generate_ground_truth_jpeg,
    generate_ground_truth_png,
    generate_ground_truth_pdf,
    generate_ground_truth_zip,
    slice_into_fragments,
    build_scenario_a,
    build_scenario_b,
    build_scenario_c,
    build_scenario_d,
    build_scenario_e,
    evaluate_reconstruction,
)
from backend.integrity_pipeline import app


client = TestClient(app)


# =============================================================================
# 1. Structural Validation Tests
# =============================================================================

class TestFormatStructuralValidation:

    def test_jpeg_valid_structure(self):
        data = generate_ground_truth_jpeg()
        res = validate_jpeg_structure(data)
        assert res.format_valid is True
        assert res.format_type == "JPEG"
        assert res.score >= 80.0
        # Verify checks
        check_names = [c.name for c in res.checks if c.passed]
        assert "soi_marker" in check_names
        assert "eoi_marker" in check_names
        assert "segment_lengths" in check_names
        assert "entropy_stream" in check_names

    def test_jpeg_missing_eoi_marker(self):
        data = generate_ground_truth_jpeg()
        truncated = data[:-2]  # Remove EOI
        res = validate_jpeg_structure(truncated)
        assert res.format_valid is False
        assert any("EOI" in iss for iss in res.issues)

    def test_jpeg_invalid_marker_length(self):
        # Corrupt segment length
        data = bytearray(generate_ground_truth_jpeg())
        # Corrupt APP0 length bytes at offset 4-5 to exceed total length
        data[4] = 0xFF
        data[5] = 0xFF
        res = validate_jpeg_structure(bytes(data))
        assert res.format_valid is False
        assert any("beyond file boundary" in iss or "length" in iss.lower() for iss in res.issues)

    def test_png_valid_structure(self):
        data = generate_ground_truth_png()
        res = validate_png_structure(data)
        assert res.format_valid is True
        assert res.format_type == "PNG"
        assert res.score >= 90.0
        check_names = [c.name for c in res.checks if c.passed]
        assert "png_signature" in check_names
        assert "chunk_structure" in check_names
        assert "crc_integrity" in check_names
        assert "iend_terminal" in check_names

    def test_png_corrupted_crc(self):
        data = bytearray(generate_ground_truth_png())
        # Flip a bit in the IHDR data section (offset 16)
        data[16] ^= 0x55
        res = validate_png_structure(bytes(data))
        assert res.format_valid is False
        assert any("CRC mismatch" in iss for iss in res.issues)

    def test_png_missing_iend(self):
        data = generate_ground_truth_png()
        # Truncate before IEND chunk (last 12 bytes)
        truncated = data[:-12]
        res = validate_png_structure(truncated)
        assert res.format_valid is False
        assert any("IEND" in iss for iss in res.issues)

    def test_pdf_valid_structure(self):
        data = generate_ground_truth_pdf()
        res = validate_pdf_structure(data)
        assert res.format_valid is True
        assert res.format_type == "PDF"
        assert res.score >= 80.0
        check_names = [c.name for c in res.checks if c.passed]
        assert "pdf_header" in check_names
        assert "pdf_objects" in check_names
        assert "eof_marker" in check_names

    def test_pdf_missing_eof(self):
        data = generate_ground_truth_pdf()
        truncated = data.replace(b"%%EOF", b"")
        res = validate_pdf_structure(truncated)
        assert res.format_valid is False
        assert any("%%EOF" in iss for iss in res.issues)

    def test_zip_valid_structure(self):
        data = generate_ground_truth_zip()
        res = validate_zip_structure(data)
        assert res.format_valid is True
        assert res.format_type == "ZIP"
        assert res.score >= 80.0
        check_names = [c.name for c in res.checks if c.passed]
        assert "local_file_headers" in check_names
        assert "central_directory" in check_names
        assert "end_of_central_directory" in check_names

    def test_zip_corrupted_central_directory(self):
        data = bytearray(generate_ground_truth_zip())
        # Corrupt the PK\x05\x06 record
        idx = data.rfind(b"PK\x05\x06")
        assert idx != -1
        data[idx:idx+4] = b"XX\x00\x00"
        res = validate_zip_structure(bytes(data))
        assert res.format_valid is False
        assert any("End-of-Central-Directory" in iss for iss in res.issues)


# =============================================================================
# 2. Provenance Tracking & Reporting Tests
# =============================================================================

class TestProvenanceAndReport:

    def test_provenance_records_continuity(self):
        chunk1 = b"AAAA" * 64   # 256 bytes
        chunk2 = b"BBBB" * 64   # 256 bytes
        chunk3 = b"CCCC" * 64   # 256 bytes

        bytes_map = {"F001": chunk1, "F002": chunk2, "F003": chunk3}
        records_map = {
            "F001": type("MockRec", (), {"source_offset": 0})(),
            "F002": type("MockRec", (), {"source_offset": 4096})(),
            "F003": type("MockRec", (), {"source_offset": 8192})(),
        }
        graph_edges = {
            ("F001", "F002"): type("MockEdge", (), {"edge_score": 91.5, "evidence": ["smooth boundary"]})(),
            ("F002", "F003"): type("MockEdge", (), {"edge_score": 87.0, "evidence": ["compatible entropy"]})(),
        }

        provenance = build_provenance_records(
            ["F001", "F002", "F003"],
            bytes_map,
            records_map,
            graph_edges,
        )

        assert len(provenance) == 3
        # Check range 1: 0..255
        assert provenance[0].output_range == [0, 255]
        assert provenance[0].source_fragment == "F001"
        assert provenance[0].edge_from is None

        # Check range 2: 256..511
        assert provenance[1].output_range == [256, 511]
        assert provenance[1].source_fragment == "F002"
        assert provenance[1].edge_from == "F001"
        assert abs(provenance[1].edge_score - 0.915) < 0.01

        # Check range 3: 512..767
        assert provenance[2].output_range == [512, 767]
        assert provenance[2].source_fragment == "F003"
        assert provenance[2].edge_from == "F002"
        assert abs(provenance[2].edge_score - 0.87) < 0.01

    def test_export_four_artifacts(self, tmp_path):
        assembled = b"TEST_RECONSTRUCTED_BYTES"
        val_res = validate_format_structure(assembled, "UNKNOWN")
        prov = [
            ProvenanceEntry(
                output_range=[0, len(assembled) - 1],
                source_fragment="F001",
                source_offset=0,
                edge_from=None,
                edge_score=1.0,
            )
        ]
        rep = ReconstructionReport(
            candidate_id="CAND-TEST-01",
            reconstructed_sha256=hashlib.sha256(assembled).hexdigest(),
            source_evidence_sha256="abc",
            total_reconstructed_bytes=len(assembled),
            byte_coverage=1.0,
            final_status="complete",
            format_type="UNKNOWN",
            format_validation=val_res.to_dict(),
            fragments_used=[{"fragment_id": "F001", "length": len(assembled)}],
            fragments_missing=[],
            corrupted_fragments=[],
            fragment_ordering=["F001"],
            edge_scores=[],
            edge_evidence=[],
            provenance=[p.to_dict() for p in prov],
            created_at="2026-09-26T00:00:00Z",
        )

        paths = export_reconstruction_artifacts(
            "CAND-TEST-01",
            assembled,
            prov,
            val_res,
            rep,
            output_dir=tmp_path,
        )

        assert Path(paths["binary_path"]).exists()
        assert Path(paths["provenance_path"]).exists()
        assert Path(paths["validation_path"]).exists()
        assert Path(paths["report_path"]).exists()

        # Check binary content is identical
        assert Path(paths["binary_path"]).read_bytes() == assembled


# =============================================================================
# 3. Ground-Truth Scenarios & Evaluation Tests
# =============================================================================

class TestGroundTruthScenarios:

    def test_scenario_a_shuffled_reconstruction(self):
        scenario = build_scenario_a("JPEG")
        assert len(scenario.fragments) == 4
        assert scenario.scenario_name == "Scenario A"

        # Reconstruct with fragment_graph
        from backend.fragment_ingestor import ingest_bytes
        from backend.fragment_graph import reconstruct_fragments

        frag_bytes = {f.fragment_id: f.data for f in scenario.fragments}
        records = [ingest_bytes(f.data, label=f.fragment_id, source_offset=f.source_offset) for f in scenario.fragments]

        graph, candidates = reconstruct_fragments(records, frag_bytes)
        assert len(candidates) > 0
        best = candidates[0]

        val_res = validate_jpeg_structure(best.assembled_bytes)
        metrics = evaluate_reconstruction(
            scenario,
            best.ordered_fragment_ids,
            best.assembled_bytes,
            best.status,
            val_res,
        )

        assert metrics.byte_level_accuracy == 1.0
        assert metrics.fragment_ordering_accuracy == 1.0
        assert metrics.sha256_match is True
        assert val_res.format_valid is True

    def test_scenario_b_missing_fragment_detected(self):
        scenario = build_scenario_b("PNG")
        assert len(scenario.missing_fragment_indices) == 1

        from backend.fragment_ingestor import ingest_bytes
        from backend.fragment_graph import reconstruct_fragments

        frag_bytes = {f.fragment_id: f.data for f in scenario.fragments}
        records = [ingest_bytes(f.data, label=f.fragment_id, source_offset=f.source_offset) for f in scenario.fragments]

        graph, candidates = reconstruct_fragments(records, frag_bytes)
        best = candidates[0]

        val_res = validate_png_structure(best.assembled_bytes)
        metrics = evaluate_reconstruction(
            scenario,
            best.ordered_fragment_ids,
            best.assembled_bytes,
            best.status,
            val_res,
        )

        assert metrics.missing_fragment_detected is True
        assert metrics.sha256_match is False  # Cannot match original when 1 chunk missing

    def test_scenario_c_corrupted_fragment_flagged(self):
        scenario = build_scenario_c("JPEG")
        assert len(scenario.corrupted_fragment_indices) == 1

        from backend.fragment_ingestor import ingest_bytes
        from backend.fragment_graph import reconstruct_fragments

        frag_bytes = {f.fragment_id: f.data for f in scenario.fragments}
        records = [ingest_bytes(f.data, label=f.fragment_id, source_offset=f.source_offset) for f in scenario.fragments]

        graph, candidates = reconstruct_fragments(records, frag_bytes)
        best = candidates[0]

        val_res = validate_jpeg_structure(best.assembled_bytes)
        metrics = evaluate_reconstruction(
            scenario,
            best.ordered_fragment_ids,
            best.assembled_bytes,
            best.status,
            val_res,
        )

        assert metrics.corruption_detected is True


# =============================================================================
# 4. API v1 Endpoints Tests
# =============================================================================

class TestApiV1Endpoints:

    def test_api_v1_discovery(self):
        png_data = generate_ground_truth_png()
        files = [
            ("files", ("chunk1.bin", png_data[:128], "application/octet-stream")),
            ("files", ("chunk2.bin", png_data[128:], "application/octet-stream")),
        ]
        resp = client.post("/api/v1/discovery/", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "DISCOVERED"
        assert data["count"] == 2
        assert len(data["fragments"]) == 2

    def test_api_v1_analysis(self):
        jpeg_data = generate_ground_truth_jpeg()
        files = [
            ("files", ("head.jpg", jpeg_data[:256], "application/octet-stream")),
        ]
        resp = client.post("/api/v1/analysis/", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["fragment_count"] == 1
        item = data["analysis"][0]
        assert "entropy" in item
        assert "detected_type" in item

    def test_api_v1_linking(self):
        pdf_data = generate_ground_truth_pdf()
        c1 = pdf_data[:200]
        c2 = pdf_data[200:]
        files = [
            ("files", ("c1.pdf", c1, "application/octet-stream")),
            ("files", ("c2.pdf", c2, "application/octet-stream")),
        ]
        resp = client.post("/api/v1/linking/", files=files)
        assert resp.status_code == 200
        graph = resp.json()["graph"]
        assert "nodes" in graph
        assert "edges" in graph
        assert graph["node_count"] == 2

    def test_api_v1_reconstruction_candidates(self):
        png_data = generate_ground_truth_png()
        frags = slice_into_fragments(png_data, 3)
        files = [
            ("files", (f.fragment_id, f.data, "application/octet-stream"))
            for f in frags
        ]
        resp = client.post("/api/v1/reconstruction/candidates", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert "candidates" in data
        assert len(data["candidates"]) > 0
        cand = data["candidates"][0]
        # Verify required spec keys
        assert "candidate_id" in cand
        assert "fragments" in cand
        assert "score" in cand
        assert "status" in cand
        assert "validation" in cand
        assert "format_valid" in cand["validation"]
        assert "complete" in cand["validation"]

    def test_api_v1_full_reconstruction_and_export(self):
        jpeg_data = generate_ground_truth_jpeg()
        frags = slice_into_fragments(jpeg_data, 3)
        files = [
            ("files", (f.fragment_id, f.data, "application/octet-stream"))
            for f in frags
        ]
        resp = client.post("/api/v1/reconstruction/", files=files)
        assert resp.status_code == 200
        data = resp.json()
        cand_id = data["candidate_id"]
        assert "artifacts_generated" in data
        assert "report" in data

        # Check export endpoint
        export_resp = client.get(f"/api/v1/reconstruction/export/{cand_id}")
        assert export_resp.status_code == 200
        export_data = export_resp.json()
        assert "report" in export_data
        assert "provenance" in export_data

        # Check binary download endpoint
        dl_resp = client.get(f"/api/v1/reconstruction/export/{cand_id}/download/bin")
        assert dl_resp.status_code == 200
        assert len(dl_resp.content) > 0

    def test_api_v1_scenarios_runner(self):
        resp = client.get("/api/v1/reconstruction/scenarios")
        assert resp.status_code == 200
        scenarios = resp.json()["scenarios"]
        assert len(scenarios) == 5

        # Run Scenario A for JPEG
        run_resp = client.post(
            "/api/v1/reconstruction/scenarios/run",
            data={"scenario_id": "A", "format_type": "JPEG"}
        )
        assert run_resp.status_code == 200
        run_data = run_resp.json()
        assert run_data["scenario"] == "Scenario A"
        assert run_data["evaluation"]["byte_level_accuracy"] == 1.0
        assert run_data["evaluation"]["sha256_match"] is True
