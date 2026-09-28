import React, { useState } from 'react';
import { 
  X, Sparkles, Folder, FileText, Shield, HardDrive, CheckCircle2, 
  ExternalLink, Copy, Check, Clock, Cpu, AlertTriangle, Terminal, BookOpen
} from 'lucide-react';

export default function JuryDemoModal({ onClose, onLoadPreset }) {
  const [activeTab, setActiveTab] = useState('script'); // 'script', 'vault', 'custody'
  const [copiedKey, setCopiedKey] = useState(null);

  const handleCopy = (text, key) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn">
      <div className="relative w-full max-w-4xl max-h-[90vh] bg-dark-900 border border-cyber-500/40 rounded-2xl shadow-neon-lg flex flex-col overflow-hidden">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800 bg-dark-950/80">
          <div className="flex items-center space-x-3">
            <div className="p-2 rounded-lg bg-cyber-500/10 border border-cyber-500/30 text-cyber-neon">
              <Sparkles className="w-5 h-5 animate-pulse" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white font-mono flex items-center space-x-2">
                <span>SAMDHAN AI -- JURY &amp; DEMO PLAYBOOK</span>
                <span className="px-2 py-0.5 text-[10px] bg-cyber-500/20 text-cyber-neon border border-cyber-500/40 rounded">
                  EVALUATION GUIDE
                </span>
              </h2>
              <p className="text-xs text-zinc-400 font-mono">
                Official presentation script, sample data browser, and ISO 27037 chain-of-custody
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center px-6 border-b border-zinc-800 bg-dark-950/40 text-xs font-mono">
          <button
            onClick={() => setActiveTab('script')}
            className={`py-3 px-4 border-b-2 font-medium transition-colors flex items-center space-x-2 ${
              activeTab === 'script'
                ? 'border-cyber-neon text-cyber-neon bg-cyber-500/5'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <BookOpen className="w-4 h-4" />
            <span>3-Minute Demo Script</span>
          </button>
          <button
            onClick={() => setActiveTab('vault')}
            className={`py-3 px-4 border-b-2 font-medium transition-colors flex items-center space-x-2 ${
              activeTab === 'vault'
                ? 'border-cyber-neon text-cyber-neon bg-cyber-500/5'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Folder className="w-4 h-4" />
            <span>Sample Evidence Vault (sample_data/)</span>
          </button>
          <button
            onClick={() => setActiveTab('custody')}
            className={`py-3 px-4 border-b-2 font-medium transition-colors flex items-center space-x-2 ${
              activeTab === 'custody'
                ? 'border-cyber-neon text-cyber-neon bg-cyber-500/5'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Shield className="w-4 h-4" />
            <span>ISO 27037 Chain of Custody</span>
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 text-xs text-zinc-300 font-sans">
          
          {/* TAB 1: 3-MINUTE DEMO SCRIPT */}
          {activeTab === 'script' && (
            <div className="space-y-6">
              {/* Introduction Banner */}
              <div className="p-4 rounded-xl bg-cyber-500/10 border border-cyber-500/30 flex items-start space-x-3">
                <Sparkles className="w-5 h-5 text-cyber-neon shrink-0 mt-0.5" />
                <div>
                  <h3 className="font-bold text-white text-sm font-mono">
                    Presenter Pitch Goal: Win the Jury in 180 Seconds
                  </h3>
                  <p className="text-zinc-300 mt-1 leading-relaxed">
                    Showcase the end-to-end autonomous forensic triage: from bitstream disk image ingestion with immutable hashing, through multi-factor priority scoring, to mathematical DAG fragment reconstruction with zero AI hallucination.
                  </p>
                </div>
              </div>

              {/* Step 1 */}
              <div className="p-4 rounded-xl bg-dark-950 border border-zinc-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-cyber-neon text-xs">
                    STEP 1 (0:00 - 0:45) • INGESTION &amp; READ-ONLY INTEGRITY LOCK
                  </span>
                  <span className="text-[11px] font-mono text-zinc-500">Screen: 1. Input &amp; Context</span>
                </div>
                <div className="text-zinc-300 space-y-1.5 pl-2 border-l-2 border-cyber-500/30">
                  <p><strong className="text-white">Action:</strong> Select <code className="text-cyber-neon">Operation Nightfall</code> preset. Point out the SHA-256 hash and read-only copy status badge.</p>
                  <p><strong className="text-white">What to say to Jury:</strong> <em>"In digital forensics, evidence integrity is non-negotiable. SAMDHAN AI enforces ISO/IEC 27037 by immediately locking the physical bitstream to read-only, calculating the cryptographic SHA-256 hash, and defining the temporal incident window."</em></p>
                  <p><strong className="text-white">Next:</strong> Click the neon <code className="text-cyber-bright">START ANALYSIS PIPELINE</code> button.</p>
                </div>
              </div>

              {/* Step 2 */}
              <div className="p-4 rounded-xl bg-dark-950 border border-zinc-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-cyber-neon text-xs">
                    STEP 2 (0:45 - 1:30) • MULTI-FACTOR TRIAGING &amp; PRIORITY SCORING
                  </span>
                  <span className="text-[11px] font-mono text-zinc-500">Screen: 3. Results / 4. Decision Support</span>
                </div>
                <div className="text-zinc-300 space-y-1.5 pl-2 border-l-2 border-cyber-500/30">
                  <p><strong className="text-white">Action:</strong> Show the Artifact Table ranked by Priority Tier. Point out <code className="text-cyber-neon">ART-1049 (Ransom Note)</code> at Priority 98.2.</p>
                  <p><strong className="text-white">What to say to Jury:</strong> <em>"Rather than drowning investigators in tens of thousands of carved junk fragments, our algorithm ranks evidence using a 4-part objective formula: 40% incident relevance + 30% structural integrity + 20% temporal recency within the breach window + 10% uniqueness."</em></p>
                  <p><strong className="text-white">Next:</strong> Click on <code className="text-cyber-neon">ART-1049</code> to open the Forensic Inspector Modal.</p>
                </div>
              </div>

              {/* Step 3 */}
              <div className="p-4 rounded-xl bg-dark-950 border border-zinc-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-cyber-neon text-xs">
                    STEP 3 (1:30 - 2:15) • INSPECTOR MODAL &amp; DUAL-ENGINE ARCHITECTURE
                  </span>
                  <span className="text-[11px] font-mono text-zinc-500">Modal: Artifact Inspector</span>
                </div>
                <div className="text-zinc-300 space-y-1.5 pl-2 border-l-2 border-cyber-500/30">
                  <p><strong className="text-white">Action:</strong> Switch between Preview, Hex Dump, and AI vs Rules tabs inside the modal.</p>
                  <p><strong className="text-white">What to say to Jury:</strong> <em>"Notice how our AI extracts threat indicators like the Bitcoin wallet and dark web URL, but structural integrity is verified strictly by deterministic rule parsers. We eliminate hallucination by separating NLP semantic scoring from binary byte verification."</em></p>
                </div>
              </div>

              {/* Step 4 */}
              <div className="p-4 rounded-xl bg-dark-950 border border-zinc-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-cyber-neon text-xs">
                    STEP 4 (2:15 - 3:00) • INTELLIGENT FRAGMENT RECONSTRUCTION
                  </span>
                  <span className="text-[11px] font-mono text-zinc-500">Screen: Reconstruction Engine</span>
                </div>
                <div className="text-zinc-300 space-y-1.5 pl-2 border-l-2 border-cyber-500/30">
                  <p><strong className="text-white">Action:</strong> Click <code className="text-cyber-neon">Reconstruction Engine</code> in the top navigation. Select <code className="text-cyber-neon">Scenario A</code> or <code className="text-cyber-neon">Scenario B</code> and click Run.</p>
                  <p><strong className="text-white">What to say to Jury:</strong> <em>"This is Feature 01: our graph-based fragment reconstructor. It ingests raw disk chunks, computes boundary edge transition weights into a Directed Acyclic Graph, solves the optimal reordering, and reassembles the file with cryptographic provenance certification."</em></p>
                </div>
              </div>

              {/* Cheat Sheet: Tough Jury Questions */}
              <div className="p-4 rounded-xl bg-dark-850 border border-zinc-700/80 space-y-3">
                <h4 className="font-mono font-bold text-white text-xs uppercase flex items-center space-x-2">
                  <Terminal className="w-4 h-4 text-cyber-neon" />
                  <span>Jury FAQ &amp; Defensible Answers Cheat Sheet</span>
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px]">
                  <div className="p-3 rounded-lg bg-dark-950 border border-zinc-800">
                    <span className="font-bold text-cyber-neon block mb-1">Q: How do you guarantee zero AI hallucinations?</span>
                    <span className="text-zinc-400">"All file format signatures, CRCs, headers, and hashes are evaluated strictly by deterministic Python rule engines. AI models only calculate threat semantic relevance and NLP tags—they never generate or modify bytes."</span>
                  </div>
                  <div className="p-3 rounded-lg bg-dark-950 border border-zinc-800">
                    <span className="font-bold text-cyber-neon block mb-1">Q: Can this run in a classified/air-gapped SCIF?</span>
                    <span className="text-zinc-400">"100% yes. The entire platform (FastAPI backend, Vite frontend, and SQLite audit stores) runs completely offline on localhost without any external cloud calls."</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: SAMPLE EVIDENCE VAULT BROWSER */}
          {activeTab === 'vault' && (
            <div className="space-y-4">
              <div className="p-3 rounded-lg bg-dark-950 border border-zinc-800 flex items-center justify-between text-xs font-mono">
                <span className="text-zinc-400">Folder Location:</span>
                <span className="text-cyber-neon select-all font-bold">A:\Samdhan AI\Samdhan-AI\sample_data\</span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Case 01 */}
                <div className="p-4 rounded-xl bg-dark-950 border border-zinc-800 hover:border-cyber-500/50 transition-all space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-white flex items-center space-x-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-red-400"></span>
                      <span>01_INCIDENT_OPERATION_NIGHTFALL</span>
                    </span>
                    <span className="px-2 py-0.5 text-[10px] font-mono bg-red-500/10 text-red-400 border border-red-500/30 rounded">
                      RANSOMWARE
                    </span>
                  </div>
                  <p className="text-zinc-400 text-xs">
                    Simulated 2MB raw disk dump (<code className="text-zinc-200">.dd</code>), carved BlackCat ransom note, wiper batch script, and SQLite auth breach database.
                  </p>
                  <div className="space-y-1 text-[11px] font-mono text-zinc-400">
                    <div className="flex justify-between"><span>seagate_barracuda_incident_dump.dd</span><span className="text-zinc-500">2.00 MB</span></div>
                    <div className="flex justify-between"><span>carved_sec_004F3A20_ransom_note.txt</span><span className="text-zinc-500">609 B</span></div>
                    <div className="flex justify-between"><span>shadow_delete_script.bat</span><span className="text-zinc-500">398 B</span></div>
                    <div className="flex justify-between"><span>auth_audit_carve.db</span><span className="text-zinc-500">12.0 KB</span></div>
                  </div>
                  <button
                    onClick={() => {
                      onLoadPreset('operation_nightfall');
                      onClose();
                    }}
                    className="w-full py-2 bg-cyber-500/15 hover:bg-cyber-500/25 text-cyber-neon border border-cyber-500/40 rounded-lg font-mono text-xs font-semibold transition-colors flex items-center justify-center space-x-1.5"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    <span>Load Case 01 into Active Pipeline</span>
                  </button>
                </div>

                {/* Case 02 */}
                <div className="p-4 rounded-xl bg-dark-950 border border-zinc-800 hover:border-cyber-500/50 transition-all space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-white flex items-center space-x-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-amber-400"></span>
                      <span>02_INCIDENT_PROJECT_AEGIS</span>
                    </span>
                    <span className="px-2 py-0.5 text-[10px] font-mono bg-amber-500/10 text-amber-400 border border-amber-500/30 rounded">
                      EXFILTRATION
                    </span>
                  </div>
                  <p className="text-zinc-400 text-xs">
                    Simulated 1.5MB raw carved flash image (<code className="text-zinc-200">.raw</code>), classified propulsion blueprint PDF, strategy DOCX, and shredded bash history.
                  </p>
                  <div className="space-y-1 text-[11px] font-mono text-zinc-400">
                    <div className="flex justify-between"><span>sandisk_128gb_exfat_carved.raw</span><span className="text-zinc-500">1.50 MB</span></div>
                    <div className="flex justify-between"><span>confidential_cad_schematic.pdf</span><span className="text-zinc-500">3.45 KB</span></div>
                    <div className="flex justify-between"><span>executive_strategy_memo.docx</span><span className="text-zinc-500">1.33 KB</span></div>
                    <div className="flex justify-between"><span>wiped_bash_history.log</span><span className="text-zinc-500">585 B</span></div>
                  </div>
                  <button
                    onClick={() => {
                      onLoadPreset('corporate_espionage');
                      onClose();
                    }}
                    className="w-full py-2 bg-cyber-500/15 hover:bg-cyber-500/25 text-cyber-neon border border-cyber-500/40 rounded-lg font-mono text-xs font-semibold transition-colors flex items-center justify-center space-x-1.5"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    <span>Load Case 02 into Active Pipeline</span>
                  </button>
                </div>

                {/* Case 03 */}
                <div className="p-4 rounded-xl bg-dark-950 border border-zinc-800 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-white flex items-center space-x-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-cyan-400"></span>
                      <span>03_CARVED_FRAGMENTS</span>
                    </span>
                    <span className="px-2 py-0.5 text-[10px] font-mono bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 rounded">
                      GRAPH REASSEMBLY
                    </span>
                  </div>
                  <p className="text-zinc-400 text-xs">
                    Deterministic binary chunks for Feature 01 scenarios: Shuffled JPEG chunks, Missing-tail PNG, and Corrupted-object PDF.
                  </p>
                  <div className="text-[11px] font-mono text-zinc-500 space-y-0.5">
                    <div>• SCENARIO_A_SHUFFLED_JPEG (5 slices + truth reference)</div>
                    <div>• SCENARIO_B_MISSING_TAIL_PNG (Missing IEND chunk)</div>
                    <div>• SCENARIO_C_CORRUPTED_MIDDLE_PDF (Zero-fill leaf)</div>
                  </div>
                </div>

                {/* Case 04 */}
                <div className="p-4 rounded-xl bg-dark-950 border border-zinc-800 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-white flex items-center space-x-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
                      <span>04_ARTIFACT_INTEGRITY_BENCHMARK</span>
                    </span>
                    <span className="px-2 py-0.5 text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 rounded">
                      15 SPEC ARTIFACTS
                    </span>
                  </div>
                  <p className="text-zinc-400 text-xs">
                    15 ground-truth artifacts (JPEG, PDF, DOCX, SQLite, Log) exhibiting all corruption variants from intact to damaged headers.
                  </p>
                  <div className="text-[11px] font-mono text-zinc-500 space-y-0.5">
                    <div>• ART-001 through ART-015 with exact benchmark matrix</div>
                    <div>• Includes full BENCHMARK_MATRIX.md documentation</div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: ISO 27037 CHAIN OF CUSTODY */}
          {activeTab === 'custody' && (
            <div className="space-y-4">
              <div className="p-4 rounded-xl bg-dark-950 border border-emerald-500/30 font-mono text-xs space-y-3 text-zinc-300">
                <div className="flex items-center justify-between pb-2 border-b border-zinc-800 text-emerald-400 font-bold">
                  <span>ISO/IEC 27037:2012 DIGITAL FORENSIC CERTIFICATE</span>
                  <span>STATUS: TAMPER-EVIDENT VERIFIED</span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-[11px]">
                  <div><span className="text-zinc-500">EXAMINER:</span> Det. H. Chen / Senior Forensics Lead</div>
                  <div><span className="text-zinc-500">ACQUISITION:</span> Tableau T8u Forensic Bridge</div>
                  <div><span className="text-zinc-500">WARRANT ID:</span> CFIR-2026-NIGHTFALL</div>
                  <div><span className="text-zinc-500">HASH STANDARD:</span> FIPS 180-4 (SHA-256)</div>
                </div>
                <div className="p-3 rounded bg-dark-900 border border-zinc-800 text-[11px] space-y-1 text-zinc-400 select-all">
                  <div><strong>Item 1:</strong> seagate_barracuda_incident_dump.dd</div>
                  <div><strong>SHA-256:</strong> e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855</div>
                  <div className="text-emerald-400 pt-1">✔ Verified zero bytes modified. Cryptographic checksum unchanged.</div>
                </div>
                <p className="text-[11px] text-zinc-400 italic">
                  "This certificate guarantees that evidence was imaged directly to an immutable bitstream, read-only mounted during analysis, and audited with tamper-proof cryptographic logs."
                </p>
              </div>
            </div>
          )}

        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-3.5 border-t border-zinc-800 bg-dark-950/80 font-mono text-xs">
          <span className="text-zinc-500 flex items-center space-x-1.5">
            <span className="w-2 h-2 rounded-full bg-cyber-neon animate-pulse"></span>
            <span>Jury Demonstration Vault Ready</span>
          </span>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-white font-medium transition-colors"
          >
            Close Guide
          </button>
        </div>

      </div>
    </div>
  );
}
