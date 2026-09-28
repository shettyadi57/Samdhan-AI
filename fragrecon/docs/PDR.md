# Preliminary Design Report (PDR)
## Module 01 — Intelligent Fragment Reconstruction

**Project:** AI-Assisted Intelligent Data Recovery and Digital Evidence Reconstruction
**Track:** 01 — Cybersecurity & AI / ML / Digital Forensics / Storage Integrity
**Objective addressed:** *"Analyze and piece together fragmented file chunks, binary headers, and dangling clusters."*

---

## 1. Problem Statement

When a file is deleted from a filesystem and the Recycle Bin is emptied, the
operating system does not erase the underlying bytes. It marks those storage
clusters as *free* and removes the directory entry that pointed to them. The
bytes remain in what forensics calls **unallocated space** until another write
operation overwrites them.

**Basic undelete** (e.g. PhotoRec, Recuva) handles the easy case: a file whose
clusters were stored contiguously. The tool scans for a known file-format
header, finds the matching footer, and extracts the byte range between them.

This module targets the hard case: **file fragmentation**. Most real-world
filesystems scatter large files across non-contiguous cluster groups. When
those clusters are recovered from unallocated space in isolation there is no
directory entry, no FAT/MFT record, and no metadata linking them. A naïve
header-to-footer scan will either:

- **fail outright** (footer not found within the search window because the
  file's tail is physically far away), or
- **silently succeed incorrectly** by accepting a *footer collision* — a
  coincidental byte sequence in unrelated noise data that matches the format's
  footer pattern — and reporting the garbled result as a valid file at 100%
  confidence.

Both failure modes are forensically unacceptable. The second is actively
harmful because it pollutes the evidence chain.

---

## 2. Objectives & Success Criteria

| # | Objective | Success Criterion |
| :--- | :--- | :--- |
| O1 | Locate file headers in raw unallocated bytes | All configured format headers found at their correct byte offsets |
| O2 | Carve contiguous files correctly | Structural validation (Pillow decode / format parsers) passes; confidence = 100% |
| O3 | Detect and reject footer collisions | Coincidental footer sequences accepted only after structural validation |
| O4 | Reconstruct scattered, non-contiguous fragments | True fragment chain located and re-stitched; structural validation passes |
| O5 | Emit honest, calibrated confidence | Confidence formula distinguishes confirmed (100%), stitched (~60–95%), and unresolved (25%) cases |
| O6 | Chain-of-custody safety | Source bytes never mutated; every output carries SHA-256 |
| O7 | Extensibility | New format added by editing `signatures.json` alone — zero engine changes |

---

## 3. Approach

### 3.1 Two-Path Architecture

```
Raw bytes (disk image / pendrive / unallocated space)
    │
    ├── [FAST PATH] Signature scan → header found → footer found nearby
    │       └── structural_check() → PASS?  → RecoveredFile (contiguous, conf=100%)
    │                              → FAIL?  → try next footer occurrence
    │                              → exhausted → fall through ↓
    │
    └── [STITCH PATH] Greedy best-first search over ALL chunk-aligned candidates
            ├── Score each: entropy_continuity × 0.6 + ngram_affinity × 0.4
            ├── Append best candidate ≥ threshold; repeat up to MAX_JOINS
            ├── Footer in chain? → structural_check() → RecoveredFile (fragmented)
            └── Threshold never met → RecoveredFile (confidence=25%, unresolved)
```

### 3.2 Why greedy best-first across ALL candidates?

Assuming the next contiguous cluster is the continuation is the logic of
*undelete*, not *reconstruction*. In a real fragmented file, the second
fragment may be anywhere in the unallocated space — far from the first,
separated by many unrelated blocks. The candidate pool must therefore be the
full set of unused cluster-aligned offsets, not just the immediate neighbours.

### 3.3 Why entropy + n-gram, not a trained model?

- **Deployable anywhere:** zero GPU, zero model weights, zero training data
  dependency. Runs on a forensic examiner's air-gapped laptop.
- **Fully explainable:** every score is a deterministic formula with explicit
  coefficients — defensible in a courtroom or to a judge panel.
- **Clear extension point:** the `stitch_score(tail, head)` function is a
  single, swappable interface. Replacing it with a trained GradientBoost or
  neural classifier requires changing exactly one function (see DDR §7).

---

## 4. Component Overview

| Component | File | Responsibility |
| :--- | :--- | :--- |
| Signature DB | `config/signatures.json` | Format definitions; extensible by editing JSON only |
| Reconstruction engine | `engine/fragment_reconstructor.py` | Scan, score, stitch, validate, report |
| Demo driver | `demo.py` | End-to-end simulated pendrive recovery |
| PDR | `docs/PDR.md` | This document |
| DDR | `docs/DDR.md` | Module-level design, formulas, limitations, future work |

---

## 5. Key Design Decisions & Rationale

| Decision | Rationale |
| :--- | :--- |
| Multi-occurrence footer validation (not first-match) | First-match accepts footer collisions in noise; see O3 |
| Structural check uses real Pillow decode for JPEG/PNG | Byte-marker check alone cannot reject partial or colliding data |
| Source bytes never written; output is a copy | Chain-of-custody requirement; SHA-256 re-verifiable |
| Fixed 4096-byte cluster stride | Matches typical EXT4/NTFS/FAT32 cluster size; configurable constant |
| Confidence 25.0 for unresolved cases, not 0 | 0 implies "definitely wrong"; 25 implies "uncertain, needs review" |
| PDF processed before JPEG in signature order | PDF clusters marked used before JPEG stitching runs; prevents false candidates |

---

## 6. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
| :--- | :--- | :--- | :--- |
| Footer collision (false positive) | Medium | High — pollutes evidence | Multi-occurrence validation + structural check on every candidate |
| High-entropy noise mistaken for true fragment | Low (demo) / Medium (production) | Medium | Log-text noise in demo (low entropy); production needs trained model |
| Fixed cluster stride misses real fragments | Low (demo) / High (production) | High | `pytsk3` integration path documented in DDR §6 |
| O(n²) candidate scan performance | Low (demo) / Medium (large images) | Medium | Documented limitation; index-bucket optimisation in DDR §7 |

---

## 7. Scope Boundaries

**In scope for this module:**
- Raw byte input (disk image, pendrive dump, unallocated space extract)
- JPEG, PNG, PDF, ZIP/OOXML, SQLite, PCAP, EVTX format support
- Contiguous carve and greedy stitching with structural validation
- JSON report generation and SHA-256 chain-of-custody output

**Out of scope (documented in DDR §5–§7 as future work):**
- Live acquisition from physical media (use `dd`/`ddrescue` first)
- `pytsk3` real filesystem cluster enumeration
- Trained scoring model
- GUI / browser interface (handled by the main SAMDHAN AI frontend)
