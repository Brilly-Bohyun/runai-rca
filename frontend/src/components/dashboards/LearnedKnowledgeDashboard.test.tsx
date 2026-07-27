import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { KnowledgeCandidate } from '../../types';
import { IngestionPreview } from './LearnedKnowledgeDashboard';

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
});
