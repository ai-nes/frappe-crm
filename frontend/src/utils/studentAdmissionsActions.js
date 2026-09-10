export const studentAdmissionsApi = Object.freeze({
  perform: 'crm.api.student_admissions.perform_action',
  decideRecommendation: 'crm.api.student_decision.decide_recommendation',
  directorRecommendations: 'crm.api.director_next_best_action.get_director_recommendations',
})

// Human-in-the-loop operations for a single AI recommendation. ACCEPT and
// ACCEPT_WITH_CHANGES each create exactly one NBA Task; the rest create none.
export const RECOMMENDATION_OPERATIONS = Object.freeze([
  'ACCEPT',
  'ACCEPT_WITH_CHANGES',
  'REJECT',
  'DEFER',
  'DISMISS',
])

export const TASK_CREATING_OPERATIONS = Object.freeze(['ACCEPT', 'ACCEPT_WITH_CHANGES'])

// The only execution parameters a reviewer may override on ACCEPT_WITH_CHANGES.
// Everything else in the AI payload — above all the Action identity — is frozen.
export const ALLOWLISTED_DELTA_PARAMS = Object.freeze(['channel', 'timing'])

// AI payload keys that fix the identity of the proposed Action. A reviewer can
// retune execution params but can never retarget the recommendation to another
// Action; attempting to is a client-side rejection, not a silent override.
export const ACTION_IDENTITY_KEYS = Object.freeze(['actionId', 'action', 'actionType', 'action_type', 'recommendationKey'])

export function recommendationActionIdentity(aiPayload = {}) {
  const source = aiPayload && typeof aiPayload === 'object' ? aiPayload : {}
  const identity = {}
  for (const key of ACTION_IDENTITY_KEYS) {
    if (source[key] !== undefined && source[key] !== null && source[key] !== '') identity[key] = source[key]
  }
  return identity
}

// Delta = allowlisted execution params whose reviewer draft value differs from
// the AI proposal. Identity keys are never emitted here.
export function diffRecommendationDelta(aiPayload = {}, draft = {}) {
  const base = aiPayload && typeof aiPayload === 'object' ? aiPayload : {}
  const next = draft && typeof draft === 'object' ? draft : {}
  const delta = {}
  for (const key of ALLOWLISTED_DELTA_PARAMS) {
    if (next[key] === undefined) continue
    const proposed = String(base[key] ?? '')
    const chosen = String(next[key] ?? '')
    if (chosen !== proposed) delta[key] = next[key]
  }
  return delta
}

function assertIdentityUnchanged(aiPayload, draft) {
  const next = draft && typeof draft === 'object' ? draft : {}
  for (const key of ACTION_IDENTITY_KEYS) {
    if (next[key] === undefined) continue
    if (String(next[key] ?? '') !== String((aiPayload || {})[key] ?? '')) {
      throw new Error(`Cannot change the Action identity of a recommendation (field "${key}").`)
    }
  }
}

/**
 * Build the single append-only command sent to `decide_recommendation`.
 *
 * The AI payload is read-only input and is never mutated or echoed back. For
 * ACCEPT_WITH_CHANGES the reviewer draft is reduced to an allowlisted delta;
 * any attempt to edit the Action identity throws before a command is produced.
 */
export function buildRecommendationDecisionCommand({
  recommendation,
  expectedRevision,
  operation,
  aiPayload = {},
  draft = {},
  idempotencyKey,
}) {
  if (!RECOMMENDATION_OPERATIONS.includes(operation)) {
    throw new Error(`Unsupported recommendation operation: ${operation}`)
  }
  if (!recommendation) throw new Error('A recommendation id is required.')
  if (expectedRevision === undefined || expectedRevision === null || expectedRevision === '') {
    throw new Error('expected_revision is required to decide a recommendation.')
  }
  if (!idempotencyKey) throw new Error('An idempotency key is required.')

  let delta = {}
  if (operation === 'ACCEPT_WITH_CHANGES') {
    assertIdentityUnchanged(aiPayload, draft)
    delta = diffRecommendationDelta(aiPayload, draft)
    if (!Object.keys(delta).length) {
      throw new Error('Accept with changes needs at least one changed execution parameter.')
    }
  }

  return {
    // `decide_recommendation(name, ...)` addresses the CRM Recommendation by
    // its document name; `recommendation` is kept as a stable wire alias.
    name: recommendation,
    recommendation,
    expected_revision: expectedRevision,
    operation,
    delta,
    idempotency_key: idempotencyKey,
  }
}

/**
 * Resolve an operation from the reviewer's intent: an accept whose draft
 * carries an allowlisted change becomes ACCEPT_WITH_CHANGES, otherwise ACCEPT.
 */
export function resolveRecommendationOperation(intent, aiPayload = {}, draft = {}) {
  if (intent !== 'ACCEPT') return intent
  return Object.keys(diffRecommendationDelta(aiPayload, draft)).length ? 'ACCEPT_WITH_CHANGES' : 'ACCEPT'
}

export const admissionsActionDefinitions = Object.freeze([
  { value: 'digital_signal', label: 'Digital signal', description: 'Record an acquisition or digital behaviour.' },
  { value: 'call_attempt', label: 'Call attempt', description: 'Record an unanswered or attempted call.' },
  { value: 'call_success', label: 'Successful call', description: 'Record a connected counselling call.' },
  { value: 'brochure_sent', label: 'Brochure sent', description: 'Record admissions information sent to the student.' },
  { value: 'major_update', label: 'Update major interest', description: 'Capture a change in programme interest.' },
  { value: 'lifecycle_transition', label: 'Change lead status', description: 'Request a governed lifecycle transition.' },
  { value: 'event_invite', label: 'Invite to Open Day', description: 'Record an event invitation.' },
  { value: 'event_register', label: 'Register for event', description: 'Record event registration.' },
  { value: 'event_checkin', label: 'Check in to event', description: 'Record event check-in.' },
  { value: 'scholarship_interest', label: 'Scholarship interest', description: 'Capture scholarship target and confidence.' },
  { value: 'create_task', label: 'Admissions task', description: 'Create a follow-up task linked to this Student.' },
  { value: 'create_insight_note', label: 'Admissions insight', description: 'Create a structured counselling note.' },
  { value: 'assign_counselor', label: 'Assign counselor', description: 'Assign the Student to a counselor through the ownership command.' },
])

export const digitalSignalOptions = Object.freeze([
  { label: 'Facebook Ads click', value: 'Facebook Ads click' },
  { label: 'Landing Page visit', value: 'Landing Page visit' },
  { label: 'Messenger chat', value: 'Messenger chat' },
  { label: 'Zalo chat', value: 'Zalo chat' },
  { label: 'Website visit', value: 'Website visit' },
  { label: 'Admissions prediction tool', value: 'Admissions prediction tool' },
  { label: 'Form submit', value: 'Form submit' },
])

// These summaries are generated from controlled admissions actions. Free-form
// notes and task titles must stay untouched when rendered in the activity log.
export const controlledAdmissionsSummaryValues = Object.freeze([
  ...digitalSignalOptions.map((option) => option.value),
  'Call attempt',
  'Successful call',
  'Brochure sent',
  'Scholarship interest',
])

export function admissionsSummaryTranslation(value) {
  const summary = String(value || '')
  if (controlledAdmissionsSummaryValues.includes(summary)) return { key: summary, args: [] }
  const dynamic = [
    ['Invited to ', 'Invited to {0}'],
    ['Registered for ', 'Registered for {0}'],
    ['Checked-in at ', 'Checked-in at {0}'],
  ].find(([prefix]) => summary.startsWith(prefix))
  return dynamic ? { key: dynamic[1], args: [summary.slice(dynamic[0].length)] } : null
}

export const insightSections = Object.freeze([
  'Competing schools',
  'Reason for choosing the major',
  'Finance and scholarship',
  'Parent influence',
  'Lead hotness',
  'Next best action',
])

const requiredByAction = {
  digital_signal: ['signal'],
  call_attempt: ['summary'],
  call_success: ['summary'],
  brochure_sent: ['summary'],
  major_update: ['major'],
  lifecycle_transition: ['to_stage'],
  event_invite: ['event'],
  event_register: ['event'],
  event_checkin: ['event'],
  scholarship_interest: ['target'],
  create_task: ['title'],
  create_insight_note: [],
  assign_counselor: ['counselor'],
}

export function fieldsForAdmissionsAction(action) {
  switch (action) {
    case 'digital_signal':
      return [{ name: 'signal', label: 'Signal', type: 'select', options: digitalSignalOptions }]
    case 'major_update':
      return [{ name: 'major', label: 'Major', type: 'text' }]
    case 'lifecycle_transition':
      return [{ name: 'to_stage', label: 'New lead status', type: 'text' }]
    case 'event_invite':
    case 'event_register':
    case 'event_checkin':
      return [{ name: 'event', label: 'Event', type: 'text' }, { name: 'campaign', label: 'Campaign', type: 'text' }]
    case 'scholarship_interest':
      return [{ name: 'target', label: 'Scholarship target', type: 'text' }, { name: 'confidence', label: 'Confidence (%)', type: 'number' }]
    case 'create_task':
      return [{ name: 'title', label: 'Task title', type: 'text' }, { name: 'due_date', label: 'Due date', type: 'date' }]
    case 'create_insight_note':
      return insightSections.map((section) => ({
        name: `insight_${section.toLowerCase().replace(/[^a-z0-9]+/g, '_')}`,
        label: section,
        type: 'textarea',
      }))
    case 'assign_counselor':
      return [{ name: 'counselor', label: 'Counselor', type: 'text' }, { name: 'team', label: 'Team (optional when unambiguous)', type: 'text' }, { name: 'reason', label: 'Reason', type: 'textarea' }]
    default:
      return [{ name: 'summary', label: 'Summary', type: 'textarea' }]
  }
}

export function validateAdmissionsAction(action, payload = {}) {
  if (action === 'create_insight_note') {
    const hasInsight = Object.values(payload).some((value) => String(value ?? '').trim())
    return hasInsight ? '' : 'Please provide at least one admissions insight.'
  }
  const missing = (requiredByAction[action] || [])
    .filter((field) => !String(payload[field] ?? '').trim())
  return missing.length ? `Please provide: ${missing.join(', ')}.` : ''
}

export function buildAdmissionsActionPayload({ student, action, expectedRevision, payload, idempotencyKey, correlationId, occurredAt }) {
  return {
    student,
    action,
    occurred_at: occurredAt || new Date().toISOString(),
    expected_revision: expectedRevision,
    idempotency_key: idempotencyKey,
    correlation_id: correlationId || idempotencyKey,
    payload: { ...payload },
  }
}

export function createAdmissionsCommandId(prefix = 'student-action') {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return `${prefix}:${crypto.randomUUID()}`
  return `${prefix}:${Date.now()}:${Math.random().toString(16).slice(2)}`
}
