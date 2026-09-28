# Module 01 — Intelligent Fragment Reconstruction

Part of: **AI-Assisted Intelligent Data Recovery and Digital Evidence Reconstruction**
*(Hackathon Track 01 — Cybersecurity & AI / ML / Digital Forensics / Storage Integrity)*

This module solves the first of the four required engineering objectives:

> *"Analyze and piece together fragmented file chunks, binary headers, and dangling clusters."*

It is a fully dynamic engine: it makes no assumption about the input file, its
size, its location on disk, or how many pieces it's been broken into. You hand
it raw bytes (a disk image, a pendrive dump, or unallocated space) and it
finds, scores, and reassembles whatever recoverable content is in there.

---

## Why this exists (the real-world scenario)

When you delete a file and empty the Recycle Bin, the operating system does
**not** erase the bytes — it only removes the entry that pointed to them and
marks that space "free." The content sits in what forensics calls *unallocated
space* until something else happens to overwrite it. That's why recovery is
possible at all.

The hard part isn't finding a deleted file that was stored in one unbroken
block — that's basic **undelete**, and free tools like PhotoRec already do it
well. The hard part, and what this module targets, is when the filesystem
**scattered** the file's clusters non-contiguously (fragmentation), so a naive
"header → footer" scan either:

- **fails outright** (footer not found within search window), or
- **silently stitches together the wrong bytes** and reports success anyway
  (a *footer collision* — a coincidental byte sequence in noise that looks like
  a valid footer, but the assembled bytes are garbage).

Both outcomes are forensically unacceptable. The second is actively harmful
because it injects false positives into the evidence chain.

---

## What it actually does

```
Raw bytes (disk image / pendrive dump / unallocated space)
        │
        ▼
1. Signature scan  (config/signatures.json — add a format, no code change)
        │
        ├── Footer found nearby & structurally valid? ──► Contiguous carve (100% confidence)
        │
        └── Footer not found / carve fails validation
                    │
                    ▼
        2. Fragment stitching — search ALL remaining chunk-aligned
           candidates (not just "the next block"), score each one against
           the tail of the chain so far using:
              • Shannon entropy continuity
              • Byte n-gram affinity
              • Format structural rules
                    │
                    ▼
        3. Reassemble the best-scoring chain; validate the result by
           REAL decode (e.g. actually opening the image with Pillow),
           not just a byte-marker match — this catches "footer collisions"
           where random noise coincidentally contains a footer-like sequence
                    │
                    ▼
        4. Emit each recovered file + an honest confidence score +
           the reasoning behind that score (never a silent 100% guess)
```

---

## Quickstart

```bash
cd fragrecon
pip install pillow          # only dependency; used to build/validate sample images
python demo.py
```

The demo:

1. Builds a real, valid 640×480 JPEG in memory using Pillow.
2. Simulates "deleting" it from a pendrive and having its clusters scattered
   **non-contiguously** across unallocated space, mixed in with unrelated
   log-text noise and a second, unrelated decoy PDF file.
3. Hands the engine **only the raw bytes** — no offsets, no hints — and lets
   it find, score, and reassemble the file on its own.
4. Writes the recovered files to `output/recovered/` and a full JSON report
   to `output/reconstruction_report.json`.

Rename `output/recovered/recovered_1_JPEG.bin` → `.jpg` and open in any image
viewer to prove it's a real, intact, viewable image. That is your literal
*"deleted from a pendrive and recovered"* demo proof.

---

## Using it against a real pendrive / disk image

```python
from engine.fragment_reconstructor import reconstruct, summarize

with open("/path/to/pendrive_image.dd", "rb") as f:
    raw = f.read()

results = reconstruct(raw, "config/signatures.json")
for line in summarize(results):
    print(line)
```

> **Always work off a copy of the media** (`dd` / `ddrescue` an image first).
> Never run analysis directly against the original pendrive — that's both a
> forensic best practice and what keeps your chain-of-custody claim honest in
> front of judges.

---

## File layout

```
fragrecon/
├── config/
│   └── signatures.json           # file-type signature database (edit to add formats)
├── engine/
│   ├── __init__.py
│   └── fragment_reconstructor.py # the reconstruction engine
├── demo.py                       # end-to-end simulated pendrive demo
├── output/                       # generated at runtime — recovered files + JSON report
│   └── recovered/
├── docs/
│   ├── PDR.md                    # Preliminary Design Report
│   └── DDR.md                    # Detailed Design Report
└── README.md                     # this file
```

---

## Scoring explained

The engine uses two complementary signals to score candidate fragment
continuations, combined into one composite score:

```
stitch_score = 0.6 × entropy_continuity + 0.4 × ngram_affinity
```

| Signal | Formula | What it measures |
| :--- | :--- | :--- |
| **Entropy continuity** | `max(0, 100 − (Δentropy / 3.0) × 100)` | How similar the Shannon entropy of the chain tail is to the candidate head. Legitimate continuations of compressed data show near-zero delta; unrelated noise shows large delta. |
| **N-gram affinity** | `min(100, shared_4grams / min_size × 400)` | How many 4-byte sequences are shared between the tail and head windows. Related binary content shares more patterns than truly random data. |

A candidate scoring **below 50** is rejected. Footer-confirmed + structurally
validated results always report **100% confidence**. Unresolved cases where the
footer is never located report **25%** — an explicit "needs review" signal, not
a silent guess.

---

## Why entropy-based and not ML?

Say this out loud to judges — it builds trust:

> "This is a **content-aware heuristic search today**, not a trained model.
> It's fast, runs anywhere with zero GPU or model dependency, and every score
> is a deterministic formula we can explain. The `stitch_score()` function is
> a single, swappable interface — the natural upgrade is to replace it with a
> small trained classifier once there's labeled data for it. That's documented
> in DDR §7 as the explicit next step."

---

## Honesty about current limitations

*(Say these out loud to judges — it builds trust, not doubt)*

1. **Chunk alignment is a fixed constant (4096 B)**, not driven by actual
   filesystem cluster boundaries. Against a real disk image this should come
   from parsing the filesystem (via `pytsk3`) — that's the next integration
   step, documented in DDR §6.

2. **The n-gram / entropy stitching is intentionally simple** — cheap,
   explainable, and runs anywhere — rather than a trained ML model. It is a
   *content-aware heuristic search* with a clear extension point to a learned
   scoring model (DDR §7, Future Work).

3. **The demo uses low-entropy log-text as noise** so that entropy scores
   clearly separate true JPEG continuations from noise clusters. In a real disk
   image, noise might be other compressed files (high entropy), making
   discrimination harder — that is the primary driver for the trained-model
   upgrade.

4. **Structural validation covers 7 formats**: JPEG, PNG, PDF, ZIP/OOXML,
   SQLite, PCAP, EVTX. Add more validators in `structural_check()` as needed —
   no architecture changes required.

---

## JSON report schema

`output/reconstruction_report.json` example entry:

```json
{
  "index": 1,
  "file_type": "JPEG",
  "category": "Photo",
  "offset_in_image": 4096,
  "size_bytes": 47823,
  "is_fragmented": true,
  "footer_confirmed": true,
  "structural_check_passed": true,
  "structural_check_reason": "JPEG: SOI+EOI present; Pillow decode passed",
  "reconstruction_confidence": 100.0,
  "stitch_scores": [91.4],
  "sha256": "a3f1b2c4..."
}
```

---

## Design documents

| Document | Contents |
| :--- | :--- |
| [`docs/PDR.md`](docs/PDR.md) | Problem statement, objectives, architecture overview, risk table |
| [`docs/DDR.md`](docs/DDR.md) | Full data-flow diagram, all formulas with rationale, confidence table, chain-of-custody design, test evidence (including two adversarial bugs found and fixed during build), known limitations, `pytsk3` integration snippet, future work roadmap |
