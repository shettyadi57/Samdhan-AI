import React from 'react';
import { Shield, Lock, FileSearch, Database, Cpu, Terminal, Download, Layers, CheckCircle2, Sparkles } from 'lucide-react';

export default function Header({ 
  currentScreen, 
  setCurrentScreen, 
  activeCase, 
  onOpenAiRules, 
  onOpenAuditLog, 
  onExportReport,
  onOpenJuryPlaybook,
  isAnalyzed
}) {
  return (
    <header className="sticky top-0 z-40 border-b border-cyber-500/20 bg-dark-950/90 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Brand & Title */}
          <div className="flex items-center space-x-3 cursor-pointer" onClick={() => setCurrentScreen('input')}>
            <div className="relative p-2 rounded-lg bg-cyber-500/10 border border-cyber-500/30 text-cyber-neon shadow-neon">
              <Shield className="w-6 h-6 animate-pulse" />
              <div className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-cyber-neon rounded-full animate-ping" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-mono font-black text-xl tracking-wider text-white">
                  SAMDHAN<span className="text-cyber-neon font-sans">.AI</span>
                </span>
                <span className="px-2 py-0.5 text-[10px] font-mono font-semibold uppercase tracking-wider bg-cyber-500/20 text-cyber-neon border border-cyber-500/40 rounded">
                  v2.4 FORENSICS
                </span>
              </div>
              <p className="text-[11px] text-zinc-400 font-mono tracking-tight hidden sm:block">
                Digital Forensics &amp; Carved Fragment Triaging Platform
              </p>
            </div>
          </div>

          {/* Workflow Status / Screen Navigation */}
          <div className="hidden md:flex items-center space-x-1 bg-dark-900/80 p-1 rounded-lg border border-zinc-800">
            <button
              onClick={() => setCurrentScreen('input')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                currentScreen === 'input'
                  ? 'bg-cyber-500/20 text-cyber-neon border border-cyber-500/40 shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
              }`}
            >
              1. Input &amp; Context
            </button>
            <button
              onClick={() => setCurrentScreen('processing')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center space-x-1.5 ${
                currentScreen === 'processing'
                  ? 'bg-cyber-500/20 text-cyber-neon border border-cyber-500/40 shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
              }`}
            >
              <span>2. Processing Engine</span>
            </button>
            <button
              onClick={() => {
                if (isAnalyzed) setCurrentScreen('dashboard');
              }}
              disabled={!isAnalyzed}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center space-x-1.5 ${
                currentScreen === 'dashboard'
                  ? 'bg-cyber-500/20 text-cyber-neon border border-cyber-500/40 shadow-sm'
                  : isAnalyzed
                  ? 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
                  : 'text-zinc-600 cursor-not-allowed'
              }`}
            >
              <span>3. Results Dashboard</span>
              {isAnalyzed && <CheckCircle2 className="w-3.5 h-3.5 text-cyber-neon inline" />}
            </button>
            <button
              onClick={() => setCurrentScreen('investigation')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center space-x-1.5 ${
                currentScreen === 'investigation'
                  ? 'bg-cyber-500/20 text-cyber-neon border border-cyber-500/40 shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
              }`}
            >
              <span>4. Decision Support</span>
              <span className="w-1.5 h-1.5 rounded-full bg-cyber-neon"></span>
            </button>
            <button
              onClick={() => setCurrentScreen('reconstruction')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center space-x-1.5 ${
                currentScreen === 'reconstruction'
                  ? 'bg-cyber-500/25 text-cyber-neon border border-cyber-500/50 shadow-neon font-bold'
                  : 'text-cyber-neon/80 hover:text-cyber-neon hover:bg-cyber-500/10 border border-cyber-500/20'
              }`}
            >
              <Cpu className="w-3.5 h-3.5 text-cyber-neon inline" />
              <span>Reconstruction Engine</span>
            </button>
          </div>

          {/* Security & Forensic Actions */}
          <div className="flex items-center space-x-2">
            {/* Read-Only Guarantee badge */}
            <div className="hidden lg:flex items-center space-x-1.5 px-2.5 py-1 bg-dark-900 border border-emerald-500/30 rounded text-[11px] font-mono text-emerald-400">
              <Lock className="w-3.5 h-3.5 text-emerald-400" />
              <span>READ-ONLY COPY</span>
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
            </div>

            {/* Jury Demo Playbook button */}
            <button
              onClick={onOpenJuryPlaybook}
              title="Open Jury Demonstration Playbook & Sample Vault"
              className="px-2.5 py-1.5 text-xs font-mono rounded bg-cyber-500/15 hover:bg-cyber-500/25 text-cyber-neon border border-cyber-500/40 transition-colors flex items-center space-x-1.5 shadow-neon"
            >
              <Sparkles className="w-3.5 h-3.5 text-cyber-neon" />
              <span className="hidden sm:inline font-semibold">Jury Playbook</span>
            </button>

            {/* AI vs Rule button */}
            <button
              onClick={onOpenAiRules}
              title="Inspect Rule-Based vs ML Forensic Architecture"
              className="px-2.5 py-1.5 text-xs font-mono rounded bg-dark-850 hover:bg-dark-800 text-zinc-300 hover:text-cyber-neon border border-zinc-700/60 hover:border-cyber-500/40 transition-colors flex items-center space-x-1.5"
            >
              <Cpu className="w-3.5 h-3.5 text-cyber-neon" />
              <span className="hidden sm:inline">AI vs Rules</span>
            </button>

            {/* Audit Log button */}
            <button
              onClick={onOpenAuditLog}
              title="View Immutable Audit Trail"
              className="px-2.5 py-1.5 text-xs font-mono rounded bg-dark-850 hover:bg-dark-800 text-zinc-300 hover:text-white border border-zinc-700/60 transition-colors flex items-center space-x-1.5"
            >
              <Terminal className="w-3.5 h-3.5 text-zinc-400" />
              <span className="hidden sm:inline">Audit Log</span>
            </button>

            {/* Export Report button */}
            <button
              onClick={onExportReport}
              disabled={!isAnalyzed}
              title="Export Forensics Court-Admissible Dossier"
              className={`px-3 py-1.5 text-xs font-medium rounded transition-all flex items-center space-x-1.5 ${
                isAnalyzed
                  ? 'bg-cyber-500 text-black hover:bg-cyber-neon font-semibold shadow-neon cursor-pointer'
                  : 'bg-zinc-800 text-zinc-500 border border-zinc-700/50 cursor-not-allowed'
              }`}
            >
              <Download className="w-3.5 h-3.5" />
              <span>Export Dossier</span>
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
