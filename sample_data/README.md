# 🎯 SAMDHAN AI -- JURY & JUDGES PRESENTATION GUIDE
Use this exact playbook when presenting SAMDHAN AI to the jury and technical evaluators.

---

## ⏱️ 3-Minute Live Demonstration Sequence

### PHASE 1: The Problem & Live Evidence Ingestion (0:00 - 0:45)
1. Open the web interface at `http://localhost:5173/`.
2. Point out the **Quick Case Presets** at the top:
   - Click **"Operation Nightfall (Ransomware Attack)"**.
   - Note to the jury: *"Notice how the system immediately locks down a read-only clone, computes the bitstream SHA-256 hash, and sets the incident temporal window (Sept 24, 14:00 - 22:30)."*
3. Show the jury the physical evidence files inside `sample_data/01_INCIDENT_OPERATION_NIGHTFALL/`:
   - `seagate_barracuda_incident_dump.dd` (Raw 2MB forensic disk image)
   - `carved_sec_004F3A20_ransom_note.txt` (Carved BlackCat extortion note)
   - `auth_audit_carve.db` (Compromised audit database)
4. Click the bright neon button: **"START ANALYSIS PIPELINE"**.
   - Watch the 6-stage cyber triage pipeline execute in real time.

---

### PHASE 2: Autonomous Triage & Priority Scoring (0:45 - 1:45)
1. You will land on the **Live Investigation Center**:
   - **Artifact Ranking Table**: Show how the Ransom Note (`ART-1049`) is ranked **#1 Critical (Priority 98.2)** because of the multi-factor scoring formula:
     $$\text{Priority} = 40\% \text{ Relevance} + 30\% \text{ Integrity} + 20\% \text{ Recency} + 10\% \text{ Uniqueness}$$
2. Click on **ART-1049** to open the **Artifact Inspector Modal**:
   - **Live Preview Tab**: Highlight the detected IOCs: Tor URL (`exfil.darkmesh.onion`) and Bitcoin address (`bc1qxy2kg...`).
   - **Color-Coded Hex Dump**: Show the exact byte stream with ASCII translation.
   - **Rule vs AI Arbitration**: Explain that the rule engine validates syntax while the ML model scores semantic threat context without hallucination.
   - **Audit Trail**: Show that every action is logged into an append-only, tamper-proof audit record.

---

### PHASE 3: Feature 01 — Intelligent Fragment Reconstruction (1:45 - 3:00)
1. Click **"Intelligent Fragment Reconstruction"** in the top navigation bar.
2. Select **Scenario A (Correct fragments shuffled)** and click **"RUN FORENSIC WORKFLOW"**.
   - Show the 12-stage forensic progression:
     1. Ingestion of raw chunks (`sample_data/03_CARVED_FRAGMENTS_FOR_RECONSTRUCTION/SCENARIO_A_SHUFFLED_JPEG/`)
     2. Directed Acyclic Graph (DAG) construction with node compatibility weights
     3. Topological branch reassembly
     4. Strict structural format validation (validating JFIF markers and Huffman tables)
     5. Provenance certificate export with cryptographic hashes!
3. Switch to **Scenario B** or **Scenario C**:
   - Show how the engine immediately flags missing trailers (missing IEND) or corrupted internal blocks rather than silently producing corrupt files.

---

## 💡 Top 4 Questions the Jury Might Ask (And Winning Answers)

| Jury Question | Winning Technical Answer |
|:--------------|:-------------------------|
| **"How do you prevent AI hallucinations in evidence presentation?"** | *"Our system uses a dual-engine architecture: all file structures and bytes are strictly validated by deterministic rule engines (format parsers, CRC32, SHA-256). AI models are restricted to ranking relevance and extracting NLP entities; they never synthesize or alter byte streams."* |
| **"How is Chain of Custody preserved?"** | *"Original media is mounted read-only. We compute cryptographic SHA-256 hashes at ingest and verify them at every pipeline hop. Every transition is persisted to an append-only SQLite audit log."* |
| **"What happens if fragments belong to multiple different files?"** | *"Our Directed Graph evaluates format signature compatibility and boundary entropy transitions. Edges between incompatible formats (e.g. JPEG header to PDF object) receive zero compatibility weight and are pruned during graph solving."* |
| **"Can this run offline in an air-gapped forensic lab?"** | *"Yes! The entire pipeline—FastAPI backend, Vite frontend, and local SQLite/disk engines—runs 100% locally on localhost without requiring internet or external cloud APIs."* |

---
*SAMDHAN AI -- Automated Digital Forensic Triaging & Fragment Reconstruction Platform*
