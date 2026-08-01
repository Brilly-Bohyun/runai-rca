import { describe, expect, it } from 'vitest';

import { collectorEvidencePresentation, rcaSummaryText, shouldPresentRunArtifacts } from './analysisPresentation';

describe('rcaSummaryText', () => {
  // The RCA Summary panel renders analysis_summary verbatim when present
  // (Korean by chart default) -- these three placeholders occupy that exact
  // slot while a run has no summary yet, and were hardcoded English with no
  // language context, unlike every other status string in the same panel.
  it('shows the real summary once analysis has completed', () => {
    expect(rcaSummaryText(false, '대상 Pod가 15분 이상 Ready 상태가 되지 않았습니다.')).toBe(
      '대상 Pod가 15분 이상 Ready 상태가 되지 않았습니다.',
    );
  });

  it('is Korean, not English, while a first analysis is pending', () => {
    const text = rcaSummaryText(false, '');
    expect(text).not.toMatch(/[A-Za-z]/);
    expect(text).toBe('분석 대기 중입니다. 수집기가 완료되는 대로 증거 수집 내역이 채워집니다.');
  });

  it('is a Korean sentence, not the old English placeholder, while a first analysis is running', () => {
    expect(rcaSummaryText(true, '')).toBe('분석이 진행 중입니다. 에이전트가 완료되면 RCA 내용이 표시됩니다.');
  });

  it('is a Korean sentence, not the old English placeholder, while a re-analysis replaces a prior summary', () => {
    // isAnalyzing wins over an existing summary on purpose: the stale prior
    // result must not be mistaken for the (not yet available) new one.
    expect(rcaSummaryText(true, '이전 RCA 요약')).toBe(
      '재분석이 진행 중입니다. 이전 RCA 결과는 유지되며, 완료되면 새 결과로 교체됩니다.',
    );
  });
});

describe('collectorEvidencePresentation', () => {
  it('hides retained evidence while a reanalysis is active', () => {
    expect(collectorEvidencePresentation({
      isAnalyzing: true,
      runStatus: 'analyzing',
      firstCompletedAt: '2026-07-14T00:00:00Z',
      artifactCount: 4,
    })).toMatchObject({ hidden: true });
  });

  it('identifies last-good evidence after a failed reanalysis', () => {
    const presentation = collectorEvidencePresentation({
      isAnalyzing: false,
      runStatus: 'failed',
      firstCompletedAt: '2026-07-14T00:00:00Z',
      artifactCount: 4,
    });

    expect(presentation.hidden).toBe(false);
    expect(presentation.notice).toContain('last completed result');
  });

  it('does not claim a prior completion for a first-attempt failure', () => {
    const presentation = collectorEvidencePresentation({
      isAnalyzing: false,
      runStatus: 'failed',
      artifactCount: 2,
    });

    expect(presentation.notice).toContain('partial evidence from the failed attempt');
  });
});

describe('shouldPresentRunArtifacts', () => {
  it('keeps retained or partial artifacts out of global collector summaries', () => {
    expect(shouldPresentRunArtifacts('complete')).toBe(true);
    expect(shouldPresentRunArtifacts('analyzing')).toBe(false);
    expect(shouldPresentRunArtifacts('failed')).toBe(false);
  });
});
