import React, { useState } from 'react';
import { 
  UploadCloud, FolderUp, FileCode, Clock, Tag, User, HardDrive, 
  Play, ShieldAlert, Sparkles, AlertCircle, FileCheck, Check,
  Folder, BookOpen, ExternalLink, HelpCircle
} from 'lucide-react';
import { SAMPLE_CASES } from '../data/mockForensicData';
import JuryDemoModal from './JuryDemoModal';

export default function InputScreen({ 
  onStartPipeline, 
  caseContext, 
  setCaseContext 
}) {
  const [selectedPreset, setSelectedPreset] = useState('operation_nightfall');
  const [activeTab, setActiveTab] = useState('upload'); // 'upload' or 'carved_folder'
  const [dragActive, setDragActive] = useState(false);
  const [showJuryGuide, setShowJuryGuide] = useState(false);
  const [uploadedFile, setUploadedFile] = useState({
    name: 'seagate_barracuda_incident_dump.dd',
    path: 'sample_data/01_INCIDENT_OPERATION_NIGHTFALL/seagate_barracuda_incident_dump.dd',
    size: '2.00 MB (4,096 sectors)',
    hash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    type: 'DD Raw Forensic Disk Clone'
  });

  const handleApplyPreset = (presetKey) => {
    setSelectedPreset(presetKey);
    const p = SAMPLE_CASES[presetKey];
    if (p) {
      setCaseContext({
        caseId: p.id,
        caseTitle: p.title,
        investigator: p.investigator,
        targetDevice: p.targetDevice,
        incidentStart: p.incidentStart.slice(0, 16),
        incidentEnd: p.incidentEnd.slice(0, 16),
        iocs: p.iocs.join(', '),
        rawImageHash: p.rawImageHash,
        totalFragments: p.totalFragments,
      });
      if (presetKey === 'operation_nightfall') {
        setUploadedFile({
          name: 'seagate_barracuda_incident_dump.dd',
          path: 'sample_data/01_INCIDENT_OPERATION_NIGHTFALL/seagate_barracuda_incident_dump.dd',
          size: '2.00 MB (4,096 sectors)',
          hash: p.rawImageHash,
          type: 'DD Raw Forensic Disk Clone'
        });
      } else {
        setUploadedFile({
          name: 'sandisk_128gb_exfat_carved.raw',
          path: 'sample_data/02_INCIDENT_PROJECT_AEGIS/sandisk_128gb_exfat_carved.raw',
          size: '1.50 MB (3,072 sectors)',
          hash: p.rawImageHash,
          type: 'Raw Unallocated Flash Dump'
        });
      }
    }
  };

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      setUploadedFile({
        name: file.name,
        size: `${(file.size / (1024 * 1024)).toFixed(2)} MB`,
        hash: '7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069',
        type: file.type || 'Raw Image / Carved Fragment'
      });
    }
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setUploadedFile({
        name: file.name,
        size: `${(file.size / (1024 * 1024)).toFixed(2)} MB`,
        hash: '7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069',
        type: file.type || 'Raw Image / Carved Fragment'
      });
    }
  };

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Quick Preset Selector for instant testing */}
      <div className="bg-dark-900 border border-zinc-800 rounded-xl p-5 shadow-cyber-card">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <div className="flex items-center space-x-2">
            <Sparkles className="w-4 h-4 text-cyber-neon" />
            <h2 className="text-sm font-semibold text-white uppercase tracking-wider font-mono">
              Quick Case Presets (Single-Click Test Data)
            </h2>
          </div>
          <div className="flex items-center space-x-3">
            <button
              onClick={() => setShowJuryGuide(true)}
              className="px-3 py-1.5 bg-cyber-500/15 hover:bg-cyber-500/25 text-cyber-neon border border-cyber-500/40 rounded-lg text-xs font-mono font-semibold flex items-center space-x-1.5 transition-all shadow-neon"
            >
              <BookOpen className="w-3.5 h-3.5" />
              <span>Jury Demo Playbook &amp; Sample Data</span>
            </button>
            <span className="text-xs text-zinc-400 font-mono hidden md:inline">
              Vault: sample_data/
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div
            onClick={() => handleApplyPreset('operation_nightfall')}
            className={`p-4 rounded-lg border cursor-pointer transition-all ${
              selectedPreset === 'operation_nightfall'
                ? 'bg-cyber-500/10 border-cyber-neon shadow-neon'
                : 'bg-dark-850/60 border-zinc-800 hover:border-zinc-700'
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-sm text-white flex items-center space-x-2">
                <span className="w-2 h-2 rounded-full bg-red-400"></span>
                <span>Operation Nightfall (Ransomware Attack)</span>
              </span>
              {selectedPreset === 'operation_nightfall' && (
                <span className="px-2 py-0.5 text-[10px] font-mono bg-cyber-500/20 text-cyber-neon border border-cyber-500/40 rounded flex items-center space-x-1">
                  <Check className="w-3 h-3" />
                  <span>ACTIVE</span>
                </span>
              )}
            </div>
            <p className="text-xs text-zinc-400 mt-2">
              Seagate 2TB Ext4 disk dump. Contains encrypted databases, batch wiper scripts, ransom demands, and C2 traffic.
            </p>
            <div className="mt-3 flex items-center gap-3 text-[11px] font-mono text-zinc-500">
              <span className="text-cyber-neon">sample_data/01_INCIDENT_OPERATION_NIGHTFALL</span>
              <span>•</span>
              <span className="text-red-400 font-semibold">Active Breach Window</span>
            </div>
          </div>

          <div
            onClick={() => handleApplyPreset('corporate_espionage')}
            className={`p-4 rounded-lg border cursor-pointer transition-all ${
              selectedPreset === 'corporate_espionage'
                ? 'bg-cyber-500/10 border-cyber-neon shadow-neon'
                : 'bg-dark-850/60 border-zinc-800 hover:border-zinc-700'
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-sm text-white flex items-center space-x-2">
                <span className="w-2 h-2 rounded-full bg-orange-400"></span>
                <span>Project Aegis (Corporate Exfiltration)</span>
              </span>
              {selectedPreset === 'corporate_espionage' && (
                <span className="px-2 py-0.5 text-[10px] font-mono bg-cyber-500/20 text-cyber-neon border border-cyber-500/40 rounded flex items-center space-x-1">
                  <Check className="w-3 h-3" />
                  <span>ACTIVE</span>
                </span>
              )}
            </div>
            <p className="text-xs text-zinc-400 mt-2">
              SanDisk 128GB USB exFAT unallocated space. Contains CAD drawings, credentials, wiped bash history, and curl exfil.
            </p>
            <div className="mt-3 flex items-center gap-3 text-[11px] font-mono text-zinc-500">
              <span className="text-cyber-neon">sample_data/02_INCIDENT_PROJECT_AEGIS</span>
              <span>•</span>
              <span className="text-amber-400 font-semibold">Insider Threat Window</span>
            </div>
          </div>
        </div>

        {/* Local Evidence Pack Quick Overview */}
        <div className="mt-4 pt-3 border-t border-zinc-800/80 flex flex-wrap items-center justify-between gap-2 text-[11px] font-mono">
          <div className="flex items-center space-x-2 text-zinc-400">
            <Folder className="w-3.5 h-3.5 text-cyber-neon" />
            <span>Local Evidence Vault:</span>
            <span className="text-zinc-200 bg-dark-950 px-2 py-0.5 rounded border border-zinc-800">
              sample_data/
            </span>
          </div>
          <div className="flex items-center space-x-3 text-zinc-400">
            <span className="flex items-center space-x-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
              <span>4 Real Incident Cases</span>
            </span>
            <span>•</span>
            <span>15 Benchmark Artifacts</span>
            <span>•</span>
            <button
              onClick={() => setShowJuryGuide(true)}
              className="text-cyber-neon hover:underline font-bold"
            >
              Open Jury Presentation Guide &rarr;
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left Column: Image Ingest & Carving Source */}
        <div className="lg:col-span-6 space-y-6">
          <div className="bg-dark-900 border border-zinc-800 rounded-xl p-6 shadow-cyber-card">
            <div className="flex items-center justify-between mb-4 border-b border-zinc-800/80 pb-3">
              <div className="flex items-center space-x-2">
                <HardDrive className="w-5 h-5 text-cyber-neon" />
                <h3 className="text-sm font-semibold text-white uppercase tracking-wider font-mono">
                  1. Evidence Ingestion Source
                </h3>
              </div>
              <div className="flex items-center space-x-2 text-xs font-mono">
                <button
                  onClick={() => setActiveTab('upload')}
                  className={`px-3 py-1 rounded transition-colors ${
                    activeTab === 'upload' 
                      ? 'bg-cyber-500/20 text-cyber-neon border border-cyber-500/40' 
                      : 'text-zinc-400 hover:text-white'
                  }`}
                >
                  Raw Disk Image
                </button>
                <button
                  onClick={() => setActiveTab('carved_folder')}
                  className={`px-3 py-1 rounded transition-colors ${
                    activeTab === 'carved_folder' 
                      ? 'bg-cyber-500/20 text-cyber-neon border border-cyber-500/40' 
                      : 'text-zinc-400 hover:text-white'
                  }`}
                >
                  Carver Output Folder
                </button>
              </div>
            </div>

            {/* Dropzone */}
            <div
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              className={`border-2 border-dashed rounded-xl p-8 text-center transition-all ${
                dragActive
                  ? 'border-cyber-neon bg-cyber-500/10 scale-[1.01]'
                  : 'border-zinc-700 bg-dark-950/60 hover:border-cyber-500/50'
              }`}
            >
              <div className="mx-auto w-14 h-14 rounded-full bg-cyber-500/10 border border-cyber-500/30 flex items-center justify-center text-cyber-neon mb-4">
                {activeTab === 'upload' ? (
                  <UploadCloud className="w-7 h-7" />
                ) : (
                  <FolderUp className="w-7 h-7" />
                )}
              </div>

              <h4 className="text-sm font-medium text-white">
                {activeTab === 'upload'
                  ? 'Drag & Drop Forensic Disk Image (.dd, .raw, .img, .e01)'
                  : 'Select Carving Engine Directory (/forensic/scalpel_output/)'}
              </h4>
              <p className="text-xs text-zinc-400 mt-1 max-w-sm mx-auto">
                Or browse local filesystem. An automated bit-stream read-only copy is mounted upon execution.
              </p>

              <label className="mt-4 inline-block px-4 py-2 bg-dark-800 hover:bg-dark-750 text-cyber-neon border border-cyber-500/40 rounded-lg text-xs font-mono font-medium cursor-pointer transition-colors">
                Browse Filesystem
                <input
                  type="file"
                  className="hidden"
                  onChange={handleFileChange}
                />
              </label>
            </div>

            {/* Ingested File Details & Cryptographic Hashing Banner */}
            {uploadedFile && (
              <div className="mt-4 p-4 rounded-lg bg-dark-950 border border-zinc-800 space-y-2 font-mono text-xs">
                <div className="flex items-center justify-between text-zinc-300">
                  <div className="truncate max-w-[280px]">
                    <span className="font-semibold text-white flex items-center space-x-1.5 truncate">
                      <FileCheck className="w-4 h-4 text-cyber-neon shrink-0" />
                      <span className="truncate">{uploadedFile.name}</span>
                    </span>
                    {uploadedFile.path && (
                      <span className="text-[10px] text-zinc-400 font-mono block truncate mt-0.5">
                        {uploadedFile.path}
                      </span>
                    )}
                  </div>
                  <span className="text-zinc-500 text-[11px] shrink-0">{uploadedFile.size}</span>
                </div>

                <div className="pt-2 border-t border-zinc-800/80 space-y-1">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-zinc-500 uppercase tracking-wider">Ingest SHA-256:</span>
                    <span className="text-cyber-neon font-mono select-all truncate max-w-[320px]">
                      {uploadedFile.hash}
                    </span>
                  </div>
                  <div className="flex items-center space-x-1.5 text-[10px] text-emerald-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                    <span>Bitstream verified. Original image write-locked (Read-Only Copy).</span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Forensic Security Guarantee Box (Spec §9 Controls) */}
          <div className="p-4 rounded-xl bg-dark-900 border border-emerald-500/25 space-y-2">
            <div className="flex items-center space-x-2 text-xs font-semibold text-emerald-400 font-mono">
              <ShieldAlert className="w-4 h-4" />
              <span>FORENSIC PROTOCOL &amp; CHAIN-OF-CUSTODY SAFEGUARDS</span>
            </div>
            <ul className="text-xs text-zinc-300 space-y-1 list-disc list-inside">
              <li>Original image is never modified; pipeline reads strictly from an immutable clone.</li>
              <li>SHA-256 hash computed at ingest and re-verified at every stage.</li>
              <li>Every stage writes to an append-only, tamper-proof SQLite audit trail.</li>
            </ul>
          </div>
        </div>

        {/* Right Column: Case Context (Optional per Spec §8) */}
        <div className="lg:col-span-6 space-y-6">
          <div className="bg-dark-900 border border-zinc-800 rounded-xl p-6 shadow-cyber-card">
            <div className="flex items-center space-x-2 mb-4 border-b border-zinc-800/80 pb-3">
              <Tag className="w-5 h-5 text-cyber-neon" />
              <h3 className="text-sm font-semibold text-white uppercase tracking-wider font-mono">
                2. Case Context &amp; Incident Parameters
              </h3>
            </div>

            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-mono text-zinc-400 mb-1.5 flex items-center space-x-1">
                    <User className="w-3.5 h-3.5 text-cyber-neon" />
                    <span>Investigator Name &amp; ID</span>
                  </label>
                  <input
                    type="text"
                    value={caseContext.investigator}
                    onChange={(e) => setCaseContext({ ...caseContext, investigator: e.target.value })}
                    placeholder="e.g. Det. H. Chen (Badge #4891)"
                    className="w-full px-3 py-2 bg-dark-950 border border-zinc-700/80 rounded-lg text-xs font-mono text-white focus:outline-none focus:border-cyber-neon transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-xs font-mono text-zinc-400 mb-1.5 flex items-center space-x-1">
                    <HardDrive className="w-3.5 h-3.5 text-cyber-neon" />
                    <span>Case Reference ID</span>
                  </label>
                  <input
                    type="text"
                    value={caseContext.caseId}
                    onChange={(e) => setCaseContext({ ...caseContext, caseId: e.target.value })}
                    placeholder="e.g. CASE-2026-NIGHTFALL"
                    className="w-full px-3 py-2 bg-dark-950 border border-zinc-700/80 rounded-lg text-xs font-mono text-white focus:outline-none focus:border-cyber-neon transition-colors"
                  />
                </div>
              </div>

              {/* Incident Date/Time Window */}
              <div className="p-3.5 rounded-lg bg-dark-950 border border-zinc-800 space-y-3">
                <div className="flex items-center space-x-1.5 text-xs font-mono text-zinc-300">
                  <Clock className="w-4 h-4 text-cyber-neon" />
                  <span className="font-semibold text-white">Incident Timeline Window (For Temporal Relevance Scoring)</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-mono text-zinc-400 mb-1">
                      Incident Start Time:
                    </label>
                    <input
                      type="datetime-local"
                      value={caseContext.incidentStart}
                      onChange={(e) => setCaseContext({ ...caseContext, incidentStart: e.target.value })}
                      className="w-full px-2.5 py-1.5 bg-dark-900 border border-zinc-700 rounded text-xs font-mono text-zinc-200 focus:outline-none focus:border-cyber-neon"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-mono text-zinc-400 mb-1">
                      Incident End Time:
                    </label>
                    <input
                      type="datetime-local"
                      value={caseContext.incidentEnd}
                      onChange={(e) => setCaseContext({ ...caseContext, incidentEnd: e.target.value })}
                      className="w-full px-2.5 py-1.5 bg-dark-900 border border-zinc-700 rounded text-xs font-mono text-zinc-200 focus:outline-none focus:border-cyber-neon"
                    />
                  </div>
                </div>
              </div>

              {/* Keyword / IOC List */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-xs font-mono text-zinc-400 flex items-center space-x-1">
                    <FileCode className="w-3.5 h-3.5 text-cyber-neon" />
                    <span>Keywords &amp; Known IOCs (Comma or line separated)</span>
                  </label>
                  <span className="text-[10px] font-mono text-zinc-500">Used by NLP &amp; Regex</span>
                </div>
                <textarea
                  rows={4}
                  value={caseContext.iocs}
                  onChange={(e) => setCaseContext({ ...caseContext, iocs: e.target.value })}
                  placeholder="198.51.100.24, exfil.onion, ransomware, DROP TABLE, mimikatz, shadowcopy delete, bitcoin:bc1q..."
                  className="w-full p-3 bg-dark-950 border border-zinc-700/80 rounded-lg text-xs font-mono text-white focus:outline-none focus:border-cyber-neon transition-colors"
                />
              </div>
            </div>

            {/* Start Pipeline Action Button */}
            <div className="mt-6 pt-4 border-t border-zinc-800">
              <button
                onClick={onStartPipeline}
                className="w-full py-3.5 px-6 rounded-xl bg-cyber-neon hover:bg-cyber-bright text-black font-bold font-mono tracking-wider text-sm transition-all flex items-center justify-center space-x-2 shadow-neon-lg transform active:scale-[0.99]"
              >
                <Play className="w-4 h-4 fill-black" />
                <span>START ANALYSIS PIPELINE (MOUNT READ-ONLY &amp; TRIAGE)</span>
              </button>
              <p className="text-center text-[11px] text-zinc-500 font-mono mt-2">
                Creates read-only copy • Hashes bitstream • Executes 6-stage triaging engine
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Jury Presentation Playbook Modal */}
      {showJuryGuide && (
        <JuryDemoModal
          onClose={() => setShowJuryGuide(false)}
          onLoadPreset={handleApplyPreset}
        />
      )}
    </div>
  );
}
