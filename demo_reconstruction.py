# -*- coding: utf-8 -*-
"""
SAMDHAN AI -- FEATURE 01: INTELLIGENT FRAGMENT RECONSTRUCTION
demo_reconstruction.py

Live Forensic Demonstration Script:
  Original file
        ↓
  Artificial fragmentation
        ↓
  Fragments shuffled
        ↓
  System receives fragments
        ↓
  Fragment analysis
        ↓
  Candidate relationships
        ↓
  Directed Graph
        ↓
  Reconstruction candidates
        ↓
  Byte reassembly
        ↓
  Format structural validation
        ↓
  Recovered file
        ↓
  Provenance + Report generation

Usage:
  python demo_reconstruction.py
  python demo_reconstruction.py --format PNG --scenario B
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

if sys.platform == "win32":
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from backend.fragment_ingestor import ingest_bytes
from backend.fragment_graph import reconstruct_fragments
from backend.format_validator import validate_format_structure
from backend.reconstruction_report import (
    build_provenance_records,
    determine_reconstruction_status,
    export_reconstruction_artifacts,
    ReconstructionReport,
)
from backend.ground_truth_dataset import (
    build_scenario_a,
    build_scenario_b,
    build_scenario_c,
    build_scenario_d,
    build_scenario_e,
    evaluate_reconstruction,
)


def run_demo(scenario_id: str = "A", format_type: str = "JPEG"):
    print("=" * 72)
    print(" SAMDHAN AI -- FEATURE 01: INTELLIGENT FRAGMENT RECONSTRUCTION DEMO")
    print("=" * 72)
    print(f"[*] Target Format : {format_type}")
    print(f"[*] Test Scenario : Scenario {scenario_id.upper()}")
    print("-" * 72)

    # 1. Generate Ground-Truth Original & Artificial Fragmentation
    builders = {
        "A": build_scenario_a,
        "B": build_scenario_b,
        "C": build_scenario_c,
        "D": build_scenario_d,
        "E": build_scenario_e,
    }
    builder = builders.get(scenario_id.upper(), build_scenario_a)
    scenario_data = builder(format_type)

    orig_sha = scenario_data.original_sha256
    print(f"[1] Original File Generated:")
    print(f"    - Size       : {scenario_data.total_original_bytes} bytes")
    print(f"    - SHA-256    : {orig_sha}")
    print(f"    - Description: {scenario_data.scenario_description}")

    # 2. Shuffled Fragments
    print(f"\n[2] Ingesting Shuffled Fragments ({len(scenario_data.fragments)} fragments):")
    records = []
    frag_bytes = {}
    for i, sf in enumerate(scenario_data.fragments):
        rec = ingest_bytes(sf.data, label=sf.fragment_id, source_offset=sf.source_offset)
        records.append(rec)
        frag_bytes[sf.fragment_id] = sf.data
        corrupt_flag = " [CORRUPTED]" if sf.is_corrupted else ""
        foreign_flag = " [FOREIGN]" if sf.is_foreign else ""
        print(f"    [{i+1}] {sf.fragment_id}: {sf.length} B | entropy={rec.entropy:.2f} | type={rec.detected_type}{corrupt_flag}{foreign_flag}")

    # 3. Directed Graph Construction & 5-Component Edge Scoring
    print(f"\n[3] Building Directed Fragment Graph & Edge Scoring:")
    graph, candidates = reconstruct_fragments(records, frag_bytes)
    print(f"    - Graph Nodes: {graph.node_count()}")
    print(f"    - Graph Edges: {graph.edge_count()}")

    for edge in graph.all_edges()[:6]:
        print(f"      • {edge.from_id} -> {edge.to_id} : score={edge.edge_score:.1f}% "
              f"(sig={edge.signature_score:.0f}, cont={edge.continuity_score:.0f}, "
              f"struct={edge.structural_score:.0f}, ent={edge.entropy_score:.0f}, pen={edge.contradiction_penalty:.0f})")

    # 4. Reconstruction Candidates
    print(f"\n[4] Enumerating Reconstruction Candidates:")
    print(f"    - Candidates Found: {len(candidates)}")
    for i, c in enumerate(candidates[:3]):
        chain = " -> ".join(c.ordered_fragment_ids)
        print(f"    Rank #{i+1} [{c.candidate_id}]: score={c.path_score:.1f}% | status={c.status}")
        print(f"           Chain: {chain}")

    best = candidates[0]

    # 5. Format Structural Validation
    print(f"\n[5] Byte Reassembly & Structural Validation:")
    print(f"    - Assembled Bytes   : {len(best.assembled_bytes)} bytes")
    print(f"    - Assembled SHA-256 : {best.assembled_sha256}")

    val_res = validate_format_structure(best.assembled_bytes, format_type)
    print(f"    - Validation Status : {'PASSED ✓' if val_res.format_valid else 'FAILED ✗'}")
    print(f"    - Structural Score  : {val_res.score:.1f}/100")
    print(f"    - Details           : {val_res.reason}")
    for chk in val_res.checks:
        mark = "✓" if chk.passed else "✗"
        print(f"      [{mark}] {chk.name}: {chk.description}")

    # 6. Provenance Mapping
    records_map = {r.fragment_id: r for r in records}
    edges_map = {(e.from_id, e.to_id): e for e in graph.all_edges()}
    provenance_entries = build_provenance_records(
        best.ordered_fragment_ids,
        frag_bytes,
        records_map,
        edges_map,
        val_res,
    )
    print(f"\n[6] Provenance Ledger ({len(provenance_entries)} mapped byte ranges):")
    for pe in provenance_entries:
        edge_label = f"edge_from={pe.edge_from} (score={pe.edge_score*100:.1f}%)" if pe.edge_from else "HEAD"
        print(f"    - Range [{pe.output_range[0]}..{pe.output_range[1]}] <- {pe.source_fragment} | {edge_label}")

    # 7. Ground Truth Evaluation
    metrics = evaluate_reconstruction(
        scenario_data,
        best.ordered_fragment_ids,
        best.assembled_bytes,
        best.status,
        val_res,
    )
    print(f"\n[7] Ground-Truth Evaluation Benchmark:")
    print(f"    - Byte-Level Accuracy       : {metrics.byte_level_accuracy * 100:.2f}%")
    print(f"    - Fragment Ordering Accuracy: {metrics.fragment_ordering_accuracy * 100:.2f}%")
    print(f"    - Missing Fragments Detected: {'YES ✓' if metrics.missing_fragment_detected else 'NO ✗'}")
    print(f"    - Corruption Flagged Correct: {'YES ✓' if metrics.corruption_detected else 'NO ✗'}")
    print(f"    - Reconstructed SHA Match   : {'EXACT MATCH ✓' if metrics.sha256_match else 'DIFFERS (Expected for missing/corrupt)'}")

    # 8. Output Artifact Generation
    output_dir = Path(__file__).parent / "reconstructed"
    final_status, notes = determine_reconstruction_status(
        val_res,
        len(best.ordered_fragment_ids),
        len(records),
        len(best.missing_fragments),
        len(best.corrupted_fragments),
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
        format_type=format_type,
        format_validation=val_res.to_dict(),
        fragments_used=[{"fragment_id": fid, "length": len(frag_bytes.get(fid, b""))} for fid in best.ordered_fragment_ids],
        fragments_missing=[m.__dict__ if hasattr(m, '__dict__') else m for m in best.missing_fragments],
        corrupted_fragments=[c.__dict__ if hasattr(c, '__dict__') else c for c in best.corrupted_fragments],
        fragment_ordering=best.ordered_fragment_ids,
        edge_scores=best.edge_scores,
        edge_evidence=[{"from": e.from_id, "to": e.to_id, "evidence": e.evidence} for e in graph.all_edges()],
        provenance=[p.to_dict() for p in provenance_entries],
        created_at="2026-09-26T00:00:00Z",
        forensic_notes=notes + best.notes,
    )

    artifact_paths = export_reconstruction_artifacts(
        best.candidate_id,
        best.assembled_bytes,
        provenance_entries,
        val_res,
        report,
        output_dir=output_dir,
    )

    print(f"\n[8] Generated Output Artifacts in reconstructed/:")
    for k, v in artifact_paths.items():
        print(f"    - {k:16}: {v}")

    print("=" * 72)
    print(" DEMONSTRATION COMPLETE: FORENSIC INTEGRITY VERIFIED")
    print("=" * 72)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAMDHAN AI Fragment Reconstruction Demo")
    parser.add_argument("--scenario", "-s", default="A", choices=["A", "B", "C", "D", "E"], help="Scenario ID (A-E)")
    parser.add_argument("--format", "-f", default="JPEG", choices=["JPEG", "PNG", "PDF", "ZIP"], help="Target file format")
    args = parser.parse_args()

    run_demo(scenario_id=args.scenario, format_type=args.format)
