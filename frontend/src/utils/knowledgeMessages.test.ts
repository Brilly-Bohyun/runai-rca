import { describe, expect, it } from 'vitest';

import { knowledgeMessageKo } from './knowledgeMessages';

describe('knowledgeMessageKo', () => {
  it('translates the refusal an operator sees most from Activate', () => {
    expect(
      knowledgeMessageKo('operator evaluation no longer qualifies this analysis for runtime knowledge'),
    ).toContain('운영자 평가가 더 이상');
  });

  it('keeps the identifiers a validator message is searched by', () => {
    const out = knowledgeMessageKo(
      "package KPKG-1 failure mode family 'novel_x_ab12' is outside the closed catalog",
    );
    expect(out).toContain('KPKG-1');
    expect(out).toContain('novel_x_ab12');
    expect(out).toContain('닫힌 카탈로그');
  });

  it('translates a known prefix and keeps the detail the validator appended', () => {
    const out = knowledgeMessageKo('knowledge validator rejected candidate: package KPKG-2 has no compiled knowledge');
    expect(out).toContain('지식 검증기가 이 후보를 거부했습니다.');
    expect(out).toContain('KPKG-2');
    expect(out).toContain('컴파일된 지식이 없습니다');
  });

  it('returns an unknown message verbatim rather than hiding it', () => {
    expect(knowledgeMessageKo('some brand new failure')).toBe('some brand new failure');
    expect(knowledgeMessageKo('')).toBe('');
  });
});
