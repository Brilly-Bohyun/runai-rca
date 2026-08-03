export type CollectorEvidencePresentationInput = {
  isAnalyzing: boolean;
  runStatus?: string;
  firstCompletedAt?: string;
  artifactCount: number;
};

// The RCA Summary panel shows `analysis_summary` verbatim -- Korean by chart
// default (charts/runai-rca/values.yaml language: ko) -- so this placeholder
// occupies the exact same slot and must read as part of the same document,
// not a hardcoded-English component with no language context. There is no
// deployment-language flag on the wire for the frontend to branch on (unlike
// the backend/agent), so this matches the rest of this same detail view,
// which already hardcodes Korean status text (e.g. the evidence-quality
// badges in AppRoot's RCA Summary heading) rather than switching on one.
export function rcaSummaryText(isAnalyzing: boolean, summary: string): string {
  if (isAnalyzing) {
    return summary
      ? '재분석이 진행 중입니다. 이전 RCA 결과는 유지되며, 완료되면 새 결과로 교체됩니다.'
      : '분석이 진행 중입니다. 에이전트가 완료되면 RCA 내용이 표시됩니다.';
  }
  return summary || '분석 대기 중입니다. 수집기가 완료되는 대로 증거 수집 내역이 채워집니다.';
}

// Global collector summaries have no per-card provenance banner. Only a
// completed run can safely contribute artifacts there; analyzing runs retain
// the previous result, while failed runs can contain either retained or partial
// artifacts.
export function shouldPresentRunArtifacts(runStatus: string) {
  return runStatus === 'complete';
}

export function collectorEvidencePresentation({
  isAnalyzing,
  runStatus,
  firstCompletedAt,
  artifactCount,
}: CollectorEvidencePresentationInput) {
  if (isAnalyzing) {
    return {
      hidden: true,
      notice: 'Analyzing… previous collector evidence is hidden until the current run completes.',
    };
  }
  if (runStatus === 'failed' && artifactCount > 0) {
    return {
      hidden: false,
      notice: firstCompletedAt
        ? 'The latest analysis attempt failed. The evidence below is the last completed result.'
        : 'The analysis failed. The evidence below is partial evidence from the failed attempt.',
    };
  }
  return { hidden: false, notice: '' };
}
