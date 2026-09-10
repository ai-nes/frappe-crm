function text(value) {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

function datePresentation(value) {
  const iso = text(value)
  if (!iso) return { iso: '', label: '' }

  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return { iso, label: iso }

  return {
    iso: date.toISOString(),
    label: new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(date),
  }
}

function activityItem(item, index) {
  const summary = text(item?.summary)
  const occurredAt = text(item?.occurred_at || item?.creation)
  if (!summary || !occurredAt || item?.superseded) return null

  return {
    key: text(item?.key) || `activity-${index}`,
    summary,
    occurredAt,
  }
}

function nextAction(raw, decisionContext) {
  const summary = text(raw?.summary || raw?.title || decisionContext?.activeAction?.actionType)
  if (!summary) return null

  return {
    summary,
    dueAt: datePresentation(raw?.due_at || raw?.due_date || decisionContext?.activeAction?.dueAt),
  }
}

export function normalizeStudentDemoContext(dto, decisionContext = null) {
  const context = dto && typeof dto === 'object' ? dto : {}
  const campaignLabel = text(context.campaign?.label || context.campaign?.name)
  const eventLabel = text(context.event?.label || context.event?.name)
  const scholarshipNotes = text(context.scholarship?.notes || context.scholarship?.target)
  const scholarshipType = text(context.scholarship?.label || context.scholarship?.intent_type)

  const campaign = campaignLabel
    ? {
        label: campaignLabel,
        source: text(context.campaign?.source),
        occurredAt: datePresentation(context.campaign?.occurred_at),
      }
    : null
  const event = eventLabel
    ? {
        label: eventLabel,
        status: text(context.event?.status).toLowerCase().replaceAll(' ', '_'),
        occurredAt: datePresentation(context.event?.occurred_at),
      }
    : null
  const scholarship = scholarshipNotes || scholarshipType
    ? {
        label: scholarshipType || __('Scholarship interest'),
        notes: scholarshipNotes,
        importance: text(context.scholarship?.importance),
        confidence: context.scholarship?.confidence ?? null,
      }
      : null
  const nextActionItem = nextAction(context.next_action, decisionContext)
  const activity = (Array.isArray(context.activity) ? context.activity : [])
    .map(activityItem)
    .filter(Boolean)

  return {
    campaign,
    event,
    scholarship,
    nextAction: nextActionItem,
    activity,
    capabilities: {
      actions: Array.isArray(context.capabilities?.actions) ? context.capabilities.actions : [],
      documentVisibility: Boolean(context.capabilities?.document_visibility),
    },
    score: context.score
      ? {
          latest: context.score.latest ?? null,
          inputRevision: Number(context.score.input_revision || 0),
          appliedInputRevision: Number(context.score.applied_input_revision || 0),
          state: text(context.score.state) || 'unknown',
        }
      : null,
    hasContent: Boolean(campaign || event || scholarship || nextActionItem || context.score),
  }
}
