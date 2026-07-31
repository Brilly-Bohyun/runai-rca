// Korean for the knowledge-review failures an operator actually hits.
//
// These come from the backend and the agent validator, both English, and they
// are the text shown when Activate is refused. An operator who cannot read them
// has no way to tell "this needs a fresh evaluation" from "the validator is
// down". Anything unrecognised is returned verbatim: a message we failed to
// translate is still far more useful than a generic one.

const EXACT: Record<string, string> = {
  // --- review lifecycle -----------------------------------------------------
  'operator evaluation no longer qualifies this analysis for runtime knowledge':
    '운영자 평가가 더 이상 이 분석을 런타임 지식으로 인정하지 않습니다. 평가 화면에서 원인 family, 해결 결과, 품질 점수를 다시 확인하세요.',
  'no operator evaluation currently confirms this analysis; re-evaluate the incident':
    '이 분석을 확인해 주는 운영자 평가가 없습니다. 인시던트를 다시 평가하세요.',
  'compiled knowledge changed since this candidate was generated; re-evaluate the incident to mint a fresh candidate':
    '후보가 만들어진 뒤 컴파일된 지식이 바뀌었습니다. 인시던트를 다시 평가해 새 후보를 만드세요.',
  'knowledge candidate is not ready for review': '검토 대기 상태인 후보만 승인할 수 있습니다.',
  'knowledge candidate is not in shadow': 'shadow 상태인 후보만 활성화할 수 있습니다.',
  'only a ready-for-review candidate can be edited': '검토 대기 상태인 후보만 조치를 수정할 수 있습니다.',
  'only a validation_failed or rejected candidate can be deleted':
    '검증 실패 또는 거부된 후보만 삭제할 수 있습니다.',
  'candidate still owns a live knowledge package; retire it first':
    '이 후보가 아직 살아 있는 지식 패키지를 갖고 있습니다. 패키지를 먼저 은퇴시키세요.',
  'knowledge candidate not found': '지식 후보를 찾을 수 없습니다.',
  'candidate not found': '지식 후보를 찾을 수 없습니다.',
  'knowledge package not found': '지식 패키지를 찾을 수 없습니다.',
  'knowledge shadow package not found': 'shadow 지식 패키지를 찾을 수 없습니다.',
  'candidate has no compiled payload': '후보에 컴파일된 지식이 없습니다.',

  // --- validator ------------------------------------------------------------
  'agent semantic validation rejected compiled package':
    '에이전트 검증이 컴파일된 패키지를 거부했습니다.',
  'knowledge validator rejected candidate': '지식 검증기가 이 후보를 거부했습니다.',
  'knowledge validator unavailable or rejected candidate':
    '지식 검증기에 연결할 수 없거나 후보가 거부되었습니다. 에이전트 상태를 확인하고 다시 시도하세요.',
  'validator unavailable': '검증기에 연결할 수 없습니다. 에이전트 상태를 확인하세요.',
  'validator is not configured': '검증기가 설정되어 있지 않습니다.',
  'validator returned invalid response': '검증기가 알 수 없는 형식으로 응답했습니다.',

  // --- action editing -------------------------------------------------------
  'between 1 and 10 non-empty actions are required': '조치는 1개 이상 10개 이하로 입력해야 합니다.',
  'action text is too long': '조치 문구가 너무 깁니다.',
  'refiner unavailable': '조치 다듬기 서비스에 연결할 수 없습니다.',

  // --- transport / storage --------------------------------------------------
  'agent is not configured': '에이전트가 설정되어 있지 않습니다.',
  'decision action must be approve, shadow, activate, or reject':
    '결정 값은 approve, shadow, activate, reject 중 하나여야 합니다.',
};

// Parameterised messages. Each rule keeps the identifiers (package, family) as
// they are — they are what an operator searches the logs for.
const RULES: Array<[RegExp, (match: RegExpMatchArray) => string]> = [
  [
    /^could not persist (.+)$/,
    () => 'DB에 저장하지 못했습니다. 잠시 후 다시 시도하고, 계속되면 백엔드 로그를 확인하세요.',
  ],
  [
    /^analysis no longer compiles into promotable knowledge: (.+)$/,
    (m) => `이 분석은 더 이상 승격 가능한 지식으로 컴파일되지 않습니다 — ${knowledgeMessageKo(m[1])}`,
  ],
  [
    /^package (\S+) failure mode family '(.+)' is outside the closed catalog$/,
    (m) => `패키지 ${m[1]}의 원인 family '${m[2]}'가 닫힌 카탈로그에 없습니다. families.yaml에 등재된 family만 승격할 수 있습니다.`,
  ],
  [
    /^package (\S+) has no compiled knowledge$/,
    (m) => `패키지 ${m[1]}에 컴파일된 지식이 없습니다.`,
  ],
  [
    /^package (\S+) symptom requires (.+)$/,
    (m) => `패키지 ${m[1]}의 증상 정의가 올바르지 않습니다 (${m[2]}).`,
  ],
  [
    /^package (\S+) probe template IDs must be safe identifier strings$/,
    (m) => `패키지 ${m[1]}의 진단 스텝 ID 형식이 올바르지 않습니다.`,
  ],
  [
    /^no usable package in the snapshot: (.+)$/,
    (m) => `스냅샷에 쓸 수 있는 패키지가 없습니다 — ${m[1]}`,
  ],
];

export function knowledgeMessageKo(message: string): string {
  const text = (message ?? '').trim();
  if (!text) return text;
  if (EXACT[text]) return EXACT[text];
  for (const [pattern, render] of RULES) {
    const match = text.match(pattern);
    if (match) return render(match);
  }
  // "<known prefix>: <detail>" — the validator appends its own reasons to the
  // backend's message, so translate the half we know and keep the rest.
  const split = text.indexOf(': ');
  if (split > 0) {
    const head = text.slice(0, split);
    if (EXACT[head]) return `${EXACT[head]} ${knowledgeMessageKo(text.slice(split + 2))}`;
  }
  return text;
}
