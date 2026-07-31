import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { KnowledgeCandidate } from '../../types';
import { CandidateDetail, catalogReviewDue, decisionConfirmLabel, IngestionPreview } from './LearnedKnowledgeDashboard';

function candidate(overrides: Partial<KnowledgeCandidate> = {}): KnowledgeCandidate {
  return {
    candidate_id: 'KC-1',
    status: 'ready_for_review',
    payload: {
      mechanism: 'configmap missing at container start',
      compiled: {
        failure_modes: [
          {
            family: 'workload_startup_error',
            symptoms: [
              {
                name: 'configmap missing at container start',
                keywords: ['configmap', 'createcontainerconfigerror'],
                actions: ['Recreate the missing ConfigMap and restart the workload.'],
              },
            ],
          },
        ],
      },
    },
    ...overrides,
  };
}

describe('IngestionPreview', () => {
  it('shows the symptom → family chain, keywords, and confirmed remediation', () => {
    const markup = renderToStaticMarkup(<IngestionPreview candidate={candidate()} />);
    expect(markup).toContain('what activation writes');
    expect(markup).toContain('workload_startup_error');
    expect(markup).toContain('configmap missing at container start');
    expect(markup).toContain('createcontainerconfigerror');
    expect(markup).toContain('Recreate the missing ConfigMap');
  });

  it('warns loudly when the learned symptom has no remediation', () => {
    const noActions = candidate();
    noActions.payload!.compiled!.failure_modes![0].symptoms![0].actions = [];
    const markup = renderToStaticMarkup(<IngestionPreview candidate={noActions} />);
    expect(markup).toContain('matcher only');
    expect(markup).toContain('effective action');
  });

  it('renders nothing for a candidate without a compiled payload', () => {
    const bare = candidate({ payload: undefined });
    expect(renderToStaticMarkup(<IngestionPreview candidate={bare} />)).toBe('');
  });

  it('explains the novel matcher-only boundary', () => {
    const markup = renderToStaticMarkup(<IngestionPreview candidate={candidate({ payload: { matcher_only: true, novelty: 'open_world', compiled: candidate().payload!.compiled } })} />);
    expect(markup).toContain('never names the headline family');
  });
});

describe('CandidateDetail', () => {
  const render = (item: KnowledgeCandidate) => renderToStaticMarkup(
    <CandidateDetail candidate={item} busy={false} onDecide={async () => {}} />,
  );

  it('leads with the symptoms → cause → action chain and hides backend identity', () => {
    const markup = render(candidate({
      root_cause_family: 'workload_startup_error',
      analysis_hash: '550d4ff6deadbeef',
      incident_id: 'INC-1',
      analysis_run_id: 'ANL-1785117859577803398-000001',
      provenance: { source: 'approved_case_snapshot', case_id: 'ANL-1:550d4ff6deadbeef', promotion_path: 'harness_claim' },
    }));
    expect(markup).toContain('Root cause family');
    expect(markup).toContain('Cause (mechanism)');
    expect(markup).toContain('configmap missing at container start');
    expect(markup).toContain('Observed symptoms');
    expect(markup).toContain('createcontainerconfigerror');
    expect(markup).toContain('Confirmed actions');
    expect(markup).toContain('Recreate the missing ConfigMap');
    // Reviewer-irrelevant plumbing stays out of the grid.
    expect(markup).not.toContain('Analysis hash');
    expect(markup).not.toContain('550d4ff6deadbeef');
    expect(markup).not.toContain('Case Id');
    expect(markup).not.toContain('Supporting cases');
    expect(markup).not.toContain('ANL-1785117859577803398-000001');
    expect(markup).not.toContain('harness_claim');
  });

  it('renders linked diagnostic probes with their tool and verdict', () => {
    const markup = render(candidate({
      probe_template_ids: ['k8s_troubleshooting:incident_scope:p01'],
      trace: { probe_executions: [{ template_id: 'k8s_troubleshooting:incident_scope:p01', tool: 'k8s_read', verdict: 'supports' }] },
    }));
    // The causal-chain redesign folded the old "Diagnostic steps" section into
    // a substep under the symptom it confirms; the tool+verdict still render.
    expect(markup).toContain('Confirmed via');
    expect(markup).toContain('incident scope · k8s_read · supports');
  });

  it('explains an empty probe list as a harness-claim promotion', () => {
    expect(render(candidate())).toContain('promoted on the harness root-cause claim');
  });

  it('tells the reviewer how to record a missing action', () => {
    const noActions = candidate();
    noActions.payload!.compiled!.failure_modes![0].symptoms![0].actions = [];
    expect(render(noActions)).toContain('add the effective action in the evaluation review');
  });

  it('offers action editing during review and shows the operator original after curation', () => {
    const curated = candidate({
      provenance: { raw_actions: ['kubectl get secret nonexistent-secret -n default'], actions_curated_by: 'llm-refiner' },
    });
    const markup = renderToStaticMarkup(
      <CandidateDetail candidate={curated} busy={false} onDecide={async () => {}} onEditActions={async () => {}} />,
    );
    // Matched past the button's icon: the label is no longer the first child.
    expect(markup).toContain('Edit</button>');
    expect(markup).toContain('kubectl get secret nonexistent-secret -n default');
    // Without an edit handler the control stays hidden.
    expect(render(curated)).not.toContain('Edit</button>');
  });
});

describe('decisionConfirmLabel', () => {
  it('never confirms shadow or activate as a rejection', () => {
    expect(decisionConfirmLabel('approve')).toBe('활성화');
    expect(decisionConfirmLabel('shadow')).toBe('shadow로 등록');
    expect(decisionConfirmLabel('activate')).toBe('활성화');
    expect(decisionConfirmLabel('reject')).toBe('거부');
    for (const action of ['approve', 'shadow', 'activate'] as const) {
      expect(decisionConfirmLabel(action)).not.toBe(decisionConfirmLabel('reject'));
    }
  });
});

describe('catalogReviewDue', () => {
  it('asks for a catalog look once a matcher-only mechanism keeps recurring', () => {
    expect(catalogReviewDue(candidate({ payload: { matcher_only: true }, supporting_case_count: 3 }))).toBe(true);
  });

  it('stays quiet below the threshold and for families that can already headline', () => {
    expect(catalogReviewDue(candidate({ payload: { matcher_only: true }, supporting_case_count: 2 }))).toBe(false);
    expect(catalogReviewDue(candidate({ supporting_case_count: 9 }))).toBe(false);
  });
});

describe('IngestionPreview', () => {
  it('says what activating actually turns on, so it is not read as a graph write', () => {
    const markup = renderToStaticMarkup(<IngestionPreview candidate={candidate()} />);
    expect(markup).toContain('symptom matching');
    expect(markup).toContain('investigation plans');
    expect(markup).toContain('hourly mirror');
  });
});

describe('CandidateDetail operator affordances', () => {
  it('links straight to the incident the knowledge came from', () => {
    const markup = renderToStaticMarkup(
      <CandidateDetail
        busy={false}
        candidate={candidate({ incident_id: 'INC-42' })}
        onDecide={async () => {}}
      />,
    );
    expect(markup).toContain('href="#/incidents/incidents/INC-42"');
  });

  it('shows the validation refusal in Korean', () => {
    const markup = renderToStaticMarkup(
      <CandidateDetail
        busy={false}
        candidate={candidate({
          status: 'validation_failed',
          validation_error: 'operator evaluation no longer qualifies this analysis for runtime knowledge',
        })}
        onDecide={async () => {}}
      />,
    );
    expect(markup).toContain('검증 실패');
    expect(markup).toContain('운영자 평가가 더 이상');
  });
});
