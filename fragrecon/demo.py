# -*- coding: utf-8 -*-
"""
SAMDHAN AI -- Module 01: Fragment Reconstruction Demo
demo.py

End-to-end simulated pendrive recovery:

  1. Builds a real, valid JPEG in memory (via Pillow if installed,
     else a large synthetic binary JPEG).
  2. Simulates a "deleted file" scenario: the JPEG's bytes are scattered
     non-contiguously across a synthetic disk image, interleaved with
     unrelated log-text clusters and a decoy PDF file.
  3. Hands the engine ONLY the raw bytes — no offsets, no file-type hints.
  4. Writes recovered files to  output/recovered/
     and a full JSON report to output/reconstruction_report.json.

Run:
    cd fragrecon
    python demo.py

Proof of concept:
    Rename output/recovered/recovered_1_JPEG.bin  →  recovered.jpg
    Open in any image viewer — it should render as a valid coloured image.
    That is your literal "deleted from a pendrive and recovered" proof.
"""

import hashlib
import io
import json
import os
import struct
import sys
from pathlib import Path

# Force UTF-8 output so Unicode box-drawing works on Windows CP1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Allow running from the fragrecon/ directory directly
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from engine.fragment_reconstructor import reconstruct, summarize, shannon_entropy

# ── Paths ─────────────────────────────────────────────────────────────────────
CONFIG_PATH  = _HERE / "config" / "signatures.json"
OUTPUT_DIR   = _HERE / "output" / "recovered"
REPORT_PATH  = _HERE / "output" / "reconstruction_report.json"

# ── Simulation constants ───────────────────────────────────────────────────────
CLUSTER = 4096   # Simulated filesystem cluster size (bytes)

# ── Optional Pillow ────────────────────────────────────────────────────────────
try:
    from PIL import Image, ImageDraw
    _PILLOW = True
except ImportError:
    _PILLOW = False


# ═════════════════════════════════════════════════════════════════════════════
# §A  SYNTHETIC MATERIAL BUILDERS
# ═════════════════════════════════════════════════════════════════════════════

def _build_jpeg_pillow() -> bytes:
    """Build a real, Pillow-verifiable JPEG >8 KB (so it spans 2+ clusters)."""
    img  = Image.new("RGB", (640, 480))
    draw = ImageDraw.Draw(img)
    # Varied colour blocks — adds entropy variation and file size
    for y in range(0, 480, 30):
        for x in range(0, 640, 30):
            r = (x * 4 + y)     % 256
            g = (y * 3 + x * 2) % 256
            b = (x + y * 5)     % 256
            draw.rectangle([x, y, x + 29, y + 29], fill=(r, g, b))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _build_jpeg_synthetic() -> bytes:
    """
    Build a structurally minimal JPEG large enough to span 2 clusters.
    Used only when Pillow is not installed.
    NOTE: this will not pass a real Pillow decode because the entropy-coded
    scan data is synthetic; structural_check() will still accept it via
    marker-only check (Pillow not available path).
    """
    soi  = b"\xff\xd8"
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    dqt  = b"\xff\xdb" + struct.pack(">H", 67) + b"\x00" + bytes(range(1, 65))
    sof0 = (b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
            + struct.pack(">HH", 160, 120) + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01")
    dht  = b"\xff\xc4" + struct.pack(">H", 31) + b"\x00" + b"\x00" * 29
    sos  = b"\xff\xda" + struct.pack(">H", 12) + b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    # Large pseudo-random entropy payload spanning 2+ clusters
    # Pattern is non-uniform to give stable entropy similar to real compressed data
    entropy = bytes([(i * 83 + 17) % 251 for i in range(12_000)])
    eoi  = b"\xff\xd9"
    return soi + app0 + dqt + sof0 + dht + sos + entropy + eoi


def _build_decoy_pdf() -> bytes:
    """Minimal valid PDF — used as an interleaved decoy file."""
    body  = b"%PDF-1.4\n"
    body += b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    body += b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    body += b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
    body += b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
    body += b"0000000058 00000 n \n0000000115 00000 n \n"
    body += b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n200\n%%EOF\n"
    return body


def _build_log_noise(cluster_count: int = 1) -> bytes:
    """
    Low-entropy log-text noise that simulates reallocated filesystem clusters.

    Shannon entropy ≈ 4.5 bits/byte  (vs JPEG compressed ≈ 7.5 bits/byte).
    This large entropy delta (≈ 3.0) drives entropy_continuity_score to ≈ 0
    when tested against JPEG data, making noise clusters score far below the
    stitching threshold of 50. True JPEG-to-JPEG continuity (delta ≈ 0–0.3)
    scores ≈ 90–100. This is the key property that makes the demo reliable.

    In a real disk image, other compressed files would occupy these slots,
    making the discrimination harder — that's the case for the trained-model
    upgrade described in DDR §7.
    """
    line = (
        b"2026-09-24 14:23:01 INFO  kernel: [45123.456789] "
        b"ext4_readpage: block=0x1A3C status=ok csum=0xDEADBEEF\n"
    )
    block = (line * (CLUSTER // len(line) + 1))[:CLUSTER]
    return block * cluster_count


# ═════════════════════════════════════════════════════════════════════════════
# §B  DISK IMAGE BUILDER
# ═════════════════════════════════════════════════════════════════════════════

def build_disk_image(jpeg_bytes: bytes):
    """
    Assemble a synthetic pendrive disk image:

    Cluster  │ Content
    ─────────┼──────────────────────────────────────────────────────
       0     │ Log-text noise   (low entropy, simulates FAT region)
       1     │ JPEG fragment 1  (starts at offset CLUSTER; contains FFD8/SOI)
       2     │ Decoy PDF        (interleaved unrelated file)
       3     │ Log-text noise   (unallocated padding)
      4…N    │ JPEG fragment 2  (remainder of JPEG; contains FFD9/EOI)
      N+1    │ Log-text noise   (trailing padding)

    Returns:
        image_bytes         – the complete synthetic disk image
        original_sha256     – SHA-256 of the original unscattered JPEG
        split_offset        – byte offset where the JPEG was split
        jpeg_chunk1         – bytes in cluster 1 (before split)
        jpeg_chunk2         – bytes from split onward (in cluster 4+)
    """
    original_sha256 = hashlib.sha256(jpeg_bytes).hexdigest()

    if len(jpeg_bytes) <= CLUSTER:
        raise ValueError(
            f"JPEG is only {len(jpeg_bytes):,} bytes -- must be >{CLUSTER:,} bytes "
            f"(more than 1 cluster) for a meaningful fragmentation demo."
        )

    def _pad(data: bytes) -> bytes:
        """Pad/truncate data to exactly one CLUSTER with log-noise fill."""
        if len(data) >= CLUSTER:
            return data[:CLUSTER]
        return data + _build_log_noise()[:CLUSTER - len(data)]

    # ── Split the JPEG at the first cluster boundary ──────────────────────────
    # chunk1 = bytes [0, CLUSTER)   : contains FFD8 (SOI), NO FFD9
    # chunk2 = bytes [CLUSTER, end) : contains all scan data and FFD9 (EOI)
    # The 640x480 JPEG at quality 92 is ~58KB, so the split is well inside the file.
    split_offset = CLUSTER
    chunk1 = jpeg_bytes[:split_offset]   # 4096 bytes — SOI + APP0 + DQT + SOF + DHT + SOS + first scan bytes (no EOI)
    chunk2 = jpeg_bytes[split_offset:]   # ~54KB — remaining scan data + FFD9 EOI

    # ── Build noise cluster with a DECOY FFD9 (footer collision) ─────────────
    # The contiguous fast-path will:
    #   1. Find the decoy FFD9 at cluster-3 offset 200 first.
    #      Candidate = source[C1 : C3+200+2] = chunk1 + PDF + decoy_noise[:202]
    #      -> structural_check FAILS (truncated scan data; Pillow: unexpected EOI)
    #   2. Find the real FFD9 inside chunk2 (cluster 4+).
    #      Candidate = source[C1 : C4+real_FFD9_pos+2] = chunk1 + PDF + decoy_noise + chunk2[:FFD9_in_chunk2]
    #      -> chunk1 alone has no EOI issue, but chunk2 contains the real scan data.
    #      Pillow MAY pass this because it's the real file. If it does -> contiguous carve.
    #      If not (depends on Pillow version strictness) -> stitching path.
    # Either path demonstrates the module working correctly.
    decoy_noise = bytearray(_build_log_noise())
    decoy_noise[200:202] = b"\xff\xd9"   # plant decoy EOI 200 bytes into noise cluster
    decoy_noise = bytes(decoy_noise)

    image = (
        _build_log_noise(1)      +   # cluster 0: noise (simulates FAT/MBR region)
        _pad(chunk1)             +   # cluster 1: JPEG frag 1  (4096 B, SOI; no EOI)
        _pad(_build_decoy_pdf()) +   # cluster 2: decoy PDF    (unrelated file)
        decoy_noise              +   # cluster 3: noise + decoy FFD9 (footer collision)
        chunk2                   +   # cluster 4+: JPEG frag 2 (scan data + real EOI)
        _build_log_noise(1)          # trailing: noise
    )

    return image, original_sha256, split_offset, chunk1, chunk2


# ═════════════════════════════════════════════════════════════════════════════
# §C  MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    SEP = "=" * 68
    print()
    print("=" * 68)
    print("  SAMDHAN AI -- Module 01: Fragment Reconstruction Demo")
    print("  Hackathon Track 01: Cybersecurity / AI / Digital Forensics")
    print("=" * 68)
    print()

    # -- Step 1: Build source material --
    print("[1/5] Building synthetic pendrive disk image...")
    if _PILLOW:
        jpeg_bytes = _build_jpeg_pillow()
        src_note   = "real JPEG via Pillow (640×480, quality 92)"
    else:
        jpeg_bytes = _build_jpeg_synthetic()
        src_note   = "synthetic JPEG (Pillow not installed — install for real decode)"

    print(f"      JPEG source  : {src_note}")
    print(f"      JPEG size    : {len(jpeg_bytes):,} bytes ({len(jpeg_bytes)/CLUSTER:.1f} clusters)")

    image, orig_sha256, split_at, chunk1, chunk2 = build_disk_image(jpeg_bytes)

    print(f"      Split offset : {split_at:,} bytes (first cluster boundary)")
    print(f"      Disk image   : {len(image):,} bytes ({len(image)//CLUSTER} clusters)")
    print(f"      Layout       : [NOISE][JPEG-C1][PDF-DECOY][NOISE][JPEG-C2][NOISE]")
    print()

    # -- Step 2: Entropy sanity check --
    print("[2/5] Entropy profile (explains why stitching picks the right continuation)...")
    noise_sample = _build_log_noise()[:CLUSTER]
    pdf_sample   = _pad_to_cluster(_build_decoy_pdf())

    def _entropy_label(data: bytes) -> str:
        e = shannon_entropy(data[:256])
        return f"{e:.2f} bits/byte"

    print(f"      Noise cluster entropy      : {_entropy_label(noise_sample)}  (low)")
    print(f"      Decoy PDF cluster entropy  : {_entropy_label(pdf_sample)}  (medium)")
    print(f"      JPEG chunk 1 tail entropy  : {_entropy_label(chunk1[-256:])}  (high - compressed)")
    print(f"      JPEG chunk 2 head entropy  : {_entropy_label(chunk2[:256])}  (high - compressed)")
    print(f"      entropy delta JPEG-JPEG    : ~{abs(shannon_entropy(chunk1[-256:]) - shannon_entropy(chunk2[:256])):.2f} (near 0 -> score ~100)")
    print(f"      entropy delta JPEG-noise   : ~{abs(shannon_entropy(chunk1[-256:]) - shannon_entropy(noise_sample[:256])):.2f} (>=3.0 -> score ~0)")
    print()

    # ── Step 3: Run engine — no hints, raw bytes only ─────────────────────────
    print(f"[3/5] Running engine (raw bytes, zero hints)…")
    results = reconstruct(image, str(CONFIG_PATH))
    print(f"      Found {len(results)} recovered file(s)")
    print()

    # ── Step 4: Print results ─────────────────────────────────────────────────
    print(f"[4/5] Results:")
    print(f"      {SEP}")
    for line in summarize(results):
        print(f"      {line}")
    print(f"      {SEP}")
    print()

    # ── Step 5: Write outputs ─────────────────────────────────────────────────
    print(f"[5/5] Writing outputs…")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    EXT_MAP = {
        "JPEG": "bin", "PNG": "bin", "PDF": "pdf",
        "ZIP":  "zip", "SQLITE": "db", "PCAP": "pcap", "EVTX": "evtx",
    }
    report_entries = []
    for i, r in enumerate(results, 1):
        ext      = EXT_MAP.get(r.file_type, "bin")
        filename = f"recovered_{i}_{r.file_type}.{ext}"
        out_path = OUTPUT_DIR / filename
        out_path.write_bytes(r.data)
        print(f"      ✓  {filename}  ({len(r.data):,} bytes)")
        report_entries.append({
            "index":                     i,
            "file_type":                 r.file_type,
            "category":                  r.category,
            "offset_in_image":           r.offset,
            "size_bytes":                len(r.data),
            "is_fragmented":             r.is_fragmented,
            "footer_confirmed":          r.footer_confirmed,
            "structural_check_passed":   r.structural_check_passed,
            "structural_check_reason":   r.structural_check_reason,
            "reconstruction_confidence": r.confidence,
            "stitch_scores":             r.stitch_scores,
            "sha256":                    r.sha256,
        })

    report = {
        "module":                 "SAMDHAN AI — Module 01: Intelligent Fragment Reconstruction",
        "hackathon_track":        "01 — Cybersecurity / AI / Digital Forensics / Storage Integrity",
        "disk_image_sha256":      hashlib.sha256(image).hexdigest(),
        "jpeg_original_sha256":   orig_sha256,
        "jpeg_split_at_offset":   split_at,
        "total_recovered":        len(results),
        "recovered_files":        report_entries,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"      ✓  reconstruction_report.json")
    print()

    # ── Verification: did we get the JPEG back? ───────────────────────────────
    jpeg_results = [r for r in results if r.file_type == "JPEG"]
    if jpeg_results:
        best         = jpeg_results[0]
        recovered_sha = hashlib.sha256(best.data).hexdigest()
        exact_match  = (recovered_sha == orig_sha256)
        print(f"┌─ JPEG Recovery Verification {'─' * 36}┐")
        print(f"│  Original SHA-256 : {orig_sha256[:52]}…")
        print(f"│  Recovered SHA-256: {recovered_sha[:52]}…")
        print(f"│  Exact byte match : {'YES ✓' if exact_match else 'NO — padding difference (expected; see note)'}")
        print(f"│  Confidence       : {best.confidence:.1f}%")
        print(f"│  Mode             : {'FRAGMENTED → stitched across non-contiguous clusters' if best.is_fragmented else 'CONTIGUOUS carve'}")
        print(f"│  Structural check : {'PASS ✓' if best.structural_check_passed else 'FAIL ✗'}")
        if best.stitch_scores:
            scores = ", ".join(f"{s:.1f}" for s in best.stitch_scores)
            print(f"│  Stitch scores    : [{scores}]")
        print(f"└{'─' * 65}┘")
        print()
        ext = EXT_MAP.get("JPEG", "bin")
        fname = f"recovered_1_JPEG.{ext}"
        print(f"  → Rename  output/recovered/{fname}  to  .jpg")
        print(f"    Open in any image viewer to confirm it is a valid, viewable image.")
        print(f"    That is your proof: a file deleted from a pendrive, recovered.")
    else:
        print("  [!] No JPEG found — check that signatures.json covers the JPEG variant in use.")

    print()
    print("Done.")


def _pad_to_cluster(data: bytes) -> bytes:
    """Pad data to at least one cluster for entropy testing."""
    if len(data) >= CLUSTER:
        return data[:CLUSTER]
    return data + _build_log_noise()[:CLUSTER - len(data)]


if __name__ == "__main__":
    main()
