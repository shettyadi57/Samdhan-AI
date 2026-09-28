import React, { useState, useEffect } from 'react';
import Header from './components/Header';
import HeroCyberBanner from './components/HeroCyberBanner';
import InputScreen from './components/InputScreen';
import ProcessingScreen from './components/ProcessingScreen';
import DashboardScreen from './components/DashboardScreen';
import ArtifactDetailModal from './components/ArtifactDetailModal';
import AiVsRuleModal from './components/AiVsRuleModal';
import AuditLogModal from './components/AuditLogModal';
import IntegrityDashboard from './components/IntegrityDashboard';
import InvestigationCenter from './components/InvestigationCenter';
import FragmentReconstructionWorkflow from './components/FragmentReconstructionWorkflow';
import JuryDemoModal from './components/JuryDemoModal';
import DEMO_ARTIFACTS, { computeDemoStats } from './data/demoArtifacts';
import { SAMPLE_CASES, MOCK_ARTIFACTS, INITIAL_AUDIT_LOG } from './data/mockForensicData';

export default function App() {
  const [currentScreen, setCurrentScreen] = useState('input'); // 'input', 'processing', 'dashboard'
  const [isAnalyzed, setIsAnalyzed] = useState(false);

  useEffect(() => {
    document.title = "SAMDHAN AI | Digital Forensics & Carved Fragment Triaging Platform";
  }, []);

  // Use the new 15-artifact demo dataset merged with mock artifacts
  const artifacts = [...DEMO_ARTIFACTS, ...MOCK_ARTIFACTS.filter(m =>
    !DEMO_ARTIFACTS.some(d => d.id === m.id)
  )];

  const [selectedArtifact, setSelectedArtifact] = useState(null);
  const [showIntegrity, setShowIntegrity] = useState(false);
  const [integrityArtifact, setIntegrityArtifact] = useState(null);
  const [showAiRules, setShowAiRules] = useState(false);
  const [showAuditLog, setShowAuditLog] = useState(false);
  const [showJuryPlaybook, setShowJuryPlaybook] = useState(false);
  const [auditLogs, setAuditLogs] = useState(INITIAL_AUDIT_LOG);

  const handleAddAuditLog = (entry) => {
    setAuditLogs(prev => [entry, ...prev]);
  };

  // Active Case Context
  const [caseContext, setCaseContext] = useState({
    caseId: SAMPLE_CASES.operation_nightfall.id,
    caseTitle: SAMPLE_CASES.operation_nightfall.title,
    investigator: SAMPLE_CASES.operation_nightfall.investigator,
    targetDevice: SAMPLE_CASES.operation_nightfall.targetDevice,
    incidentStart: SAMPLE_CASES.operation_nightfall.incidentStart.slice(0, 16),
    incidentEnd: SAMPLE_CASES.operation_nightfall.incidentEnd.slice(0, 16),
    iocs: SAMPLE_CASES.operation_nightfall.iocs.join(', '),
    rawImageHash: SAMPLE_CASES.operation_nightfall.rawImageHash,
    totalFragments: SAMPLE_CASES.operation_nightfall.totalFragments,
  });

  // Start analysis pipeline
  const handleStartPipeline = () => {
    setCurrentScreen('processing');
  };

  // Pipeline completed
  const handlePipelineComplete = () => {
    setIsAnalyzed(true);
    setCurrentScreen('dashboard');
  };

  // Open Integrity Dashboard for an artifact
  const handleOpenIntegrity = (artifact) => {
    setIntegrityArtifact(artifact);
    setShowIntegrity(true);
  };

  // Switch to related artifact
  const handleSelectRelated = (artifactId) => {
    const found = artifacts.find(a => a.id === artifactId);
    if (found) {
      setSelectedArtifact(found);
    }
  };

  // Export full forensic dossier
  const handleExportReport = () => {
    const stats = computeDemoStats(artifacts);
    const reportData = {
      platform: "SAMDHAN AI — Data Integrity & Corruption Assessment v2.4",
      module: "Integrity & Corruption Assessment (§24 PDR)",
      exportTimestamp: new Date().toISOString(),
      caseContext: {
        ...caseContext,
        custodyStatus: "DERIVED_FROM_READ_ONLY_IMAGE_UNMODIFIED",
        validationAlgorithm: "SHA-256 + Magic-byte + GradientBoosting + IsolationForest",
      },
      summary: stats,
      integrityWeights: { structural: 0.30, content: 0.35, fragment: 0.20, metadata: 0.15,
        note: "Prototype defaults — not forensically validated" },
      artifacts: artifacts.map(a => ({
        id: a.id,
        filename: a.filename,
        type: a.type,
        classificationConfidence: a.classificationConfidence,
        structuralIntegrity: a.structuralIntegrity,
        contentIntegrity: a.contentIntegrity,
        metadataIntegrity: a.metadataIntegrity,
        fragmentContinuity: a.fragmentContinuity,
        overallIntegrity: a.overallIntegrity,
        corruptionSeverity: a.corruptionSeverity,
        recoverability: a.recoverability,
        corruptionRegions: a.corruptionRegions,
        priorityScore: a.priorityScore,
        priorityTier: a.priorityTier,
        sha256: a.metadata?.sha256,
      }))
    };

    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(reportData, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `INTEGRITY_REPORT_${caseContext.caseId}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  return (
    <div className="min-h-screen bg-dark-950 text-slate-100 flex flex-col font-sans selection:bg-cyber-neon selection:text-black">
      {/* Top Sticky Header */}
      <Header
        currentScreen={currentScreen}
        setCurrentScreen={setCurrentScreen}
        activeCase={caseContext}
        onOpenAiRules={() => setShowAiRules(true)}
        onOpenAuditLog={() => setShowAuditLog(true)}
        onOpenJuryPlaybook={() => setShowJuryPlaybook(true)}
        onExportReport={handleExportReport}
        isAnalyzed={isAnalyzed}
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {currentScreen === 'input' && (
          <div className="space-y-6">
            {/* Cybersecurity Hero Banner */}
            <HeroCyberBanner
              onStartDemo={handleStartPipeline}
              onOpenAiRules={() => setShowAiRules(true)}
            />

            {/* Input & Case Context Form */}
            <InputScreen
              onStartPipeline={handleStartPipeline}
              caseContext={caseContext}
              setCaseContext={setCaseContext}
            />
          </div>
        )}

        {currentScreen === 'processing' && (
          <ProcessingScreen
            onComplete={handlePipelineComplete}
            totalFragments={caseContext.totalFragments || 36}
            caseContext={caseContext}
          />
        )}

        {currentScreen === 'dashboard' && (
          <DashboardScreen
            artifacts={artifacts}
            onSelectArtifact={(art) => setSelectedArtifact(art)}
            onOpenIntegrity={handleOpenIntegrity}
            onNavigateToInvestigation={() => setCurrentScreen('investigation')}
            caseContext={caseContext}
          />
        )}

        {currentScreen === 'investigation' && (
          <InvestigationCenter
            caseContext={caseContext}
            artifacts={artifacts}
            onAddAuditLog={handleAddAuditLog}
          />
        )}

        {currentScreen === 'reconstruction' && (
          <FragmentReconstructionWorkflow />
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-zinc-800/80 bg-dark-950 py-6 text-center text-xs font-mono text-zinc-500">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center space-x-2">
            <span className="w-2 h-2 rounded-full bg-cyber-neon"></span>
            <span>SAMDHAN AI • Data Integrity & Corruption Assessment Module v2.4</span>
          </div>
          <div className="flex items-center space-x-4 text-[11px] text-zinc-400">
            <span>CALMSTACKS 24H Hackathon</span>
            <span>•</span>
            <span>§10 Scoring · §9 Taxonomy · §11 Recoverability</span>
            <span>•</span>
            <button
              onClick={() => setShowAiRules(true)}
              className="text-cyber-neon hover:underline"
            >
              AI vs Rule Architecture
            </button>
          </div>
        </div>
      </footer>

      {/* Modals */}
      {selectedArtifact && (
        <ArtifactDetailModal
          artifact={selectedArtifact}
          onClose={() => setSelectedArtifact(null)}
          onSelectRelated={handleSelectRelated}
          onOpenIntegrity={handleOpenIntegrity}
          caseContext={caseContext}
        />
      )}

      {showIntegrity && integrityArtifact && (
        <IntegrityDashboard
          artifact={integrityArtifact}
          onClose={() => { setShowIntegrity(false); setIntegrityArtifact(null); }}
        />
      )}

      {showAiRules && (
        <AiVsRuleModal
          onClose={() => setShowAiRules(false)}
        />
      )}

      {showAuditLog && (
        <AuditLogModal
          onClose={() => setShowAuditLog(false)}
          caseContext={caseContext}
          auditLogs={auditLogs}
        />
      )}

      {showJuryPlaybook && (
        <JuryDemoModal
          onClose={() => setShowJuryPlaybook(false)}
          onLoadPreset={(presetKey) => {
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
              setCurrentScreen('input');
            }
          }}
        />
      )}
    </div>
  );
}
