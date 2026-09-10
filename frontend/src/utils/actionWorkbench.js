export const ACTION_VIEW_MODEL_CONTRACT = 'actionviewmodel:v1'

const SECTION_KEYS = ['what', 'why', 'how', 'goal', 'action']
const SAFE_STATES = new Set(['available', 'loading', 'unavailable', 'stale', 'blocked', 'approval-required'])

function text(value) {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function normalizeSection(section, fallbackTitle) {
  const value = section && typeof section === 'object' ? section : {}
  return {
    title: text(value.title) || fallbackTitle,
    body: text(value.body),
    evidence: Array.isArray(value.evidence) ? value.evidence.map(text).filter(Boolean) : [],
    gaps: Array.isArray(value.gaps) ? value.gaps.map(text).filter(Boolean) : [],
  }
}

export function unavailableAction(reason = 'unsupported') {
  return {
    state: 'unavailable',
    reason,
    contractVersion: null,
    actionId: '',
    actionRevision: null,
    packageRevision: null,
    freshness: { label: 'unknown', asOf: null, ageSeconds: null, contextCurrent: null },
    sections: Object.fromEntries(SECTION_KEYS.map((key) => [key, normalizeSection({}, key)])),
    allowedOperations: [],
    package: null,
  }
}

export function normalizeActionViewModel(raw) {
  if (!raw || typeof raw !== 'object' || raw.contract_version !== ACTION_VIEW_MODEL_CONTRACT) {
    return unavailableAction('unsupported-contract')
  }
  if (!text(raw.action_id)) return unavailableAction('missing-action-id')

  const freshness = raw.freshness && typeof raw.freshness === 'object' ? raw.freshness : {}
  const label = ['fresh', 'aging', 'stale', 'unknown'].includes(freshness.label) ? freshness.label : 'unknown'
  const allowedOperations = Array.isArray(raw.allowed_operations)
    ? raw.allowed_operations.filter((operation) => operation && typeof operation === 'object' && text(operation.operation || operation.operation_id || operation.id))
      .map((operation) => ({
        operationId: text(operation.operation || operation.operation_id || operation.id),
        label: text(operation.label) || text(operation.operation || operation.operation_id || operation.id),
        available: operation.available !== false && operation.state !== 'denied',
        blocked: Boolean(operation.blocked || operation.blocked_reason || operation.state === 'requires-review'),
        blockedReason: text(operation.blocked_reason || operation.reason_code),
        requiresApproval: Boolean(operation.requires_approval || operation.approval_required || operation.state === 'requires-review'),
      }))
    : []

  return {
    state: label === 'stale' ? 'stale' : 'available',
    reason: '',
    contractVersion: raw.contract_version,
    actionId: text(raw.action_id),
    student: text(raw.student),
    actionRevision: raw.action_revision ?? null,
    packageRevision: raw.package_revision ?? null,
    freshness: { label, asOf: freshness.as_of ?? null, ageSeconds: freshness.age_seconds ?? null, contextCurrent: freshness.context_current ?? null },
    sections: Object.fromEntries(SECTION_KEYS.map((key) => [key, normalizeSection(raw[key], key)])),
    allowedOperations,
    package: raw.package && typeof raw.package === 'object' ? { schema: text(raw.package.schema), revision: raw.package.revision ?? null, data: raw.package.data || {} } : null,
  }
}

// The canonical admissions work item is `CRM Action Item`; every operator
// surface presents it under one name so the review queue and the executed
// worklist read as the same object.
export const NBA_TASK_LABEL = 'NBA Task'
export const NBA_TASK_DOCTYPE = 'CRM Action Item'

export function nbaTaskNoun(value) {
  const label = typeof value === 'string' ? value.trim() : ''
  if (!label || label === NBA_TASK_DOCTYPE || label === 'CRM Action' || label === 'Action') return NBA_TASK_LABEL
  return label
}

const TASK_CREATING_OPERATIONS = new Set(['ACCEPT', 'ACCEPT_WITH_CHANGES'])

// Does this recommendation operation materialise an NBA Task? ACCEPT and
// ACCEPT_WITH_CHANGES do (exactly one); REJECT / DEFER / DISMISS never do.
export function operationCreatesTask(operation) {
  return TASK_CREATING_OPERATIONS.has(operation)
}

/**
 * The NBA Task values that an accepted recommendation produces: the AI proposal
 * is the base, the reviewer delta wins for the allowlisted execution params.
 * The AI payload is treated as immutable — a shallow copy is returned and the
 * input object is never written to.
 */
export function nbaTaskFromDecision({ operation, aiPayload = {}, delta = {} } = {}) {
  if (!operationCreatesTask(operation)) return null
  const base = aiPayload && typeof aiPayload === 'object' ? aiPayload : {}
  const overrides = delta && typeof delta === 'object' ? delta : {}
  const task = { ...base }
  for (const [key, value] of Object.entries(overrides)) {
    if (value !== undefined) task[key] = value
  }
  return task
}

/**
 * Present the AI proposal and the human/Task draft as two separate artifacts so
 * the immutable proposal is never visually overwritten by the editable values.
 */
export function recommendationArtifacts({ aiPayload = {}, delta = {}, operation } = {}) {
  const proposal = aiPayload && typeof aiPayload === 'object' ? { ...aiPayload } : {}
  const task = nbaTaskFromDecision({ operation, aiPayload, delta })
  return {
    proposal,
    task,
    changedKeys: task ? Object.keys(delta || {}).filter((key) => delta[key] !== undefined) : [],
  }
}

export function actionWorkbenchApi(actionId, expectedRevision) {
  return {
    url: 'crm.api.student_worklist.get_action_workbench',
    params: { action: actionId, expected_action_revision: expectedRevision ?? undefined },
  }
}
