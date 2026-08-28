import { evaluateExpression } from '@/utils/expressions'

/**
 * Safely parse link_filters which can be a JSON string or already an object.
 * Returns the parsed object or null.
 */
export function parseLinkFilters(linkFilters) {
  if (!linkFilters) return null
  if (typeof linkFilters === 'object') return linkFilters
  try {
    return JSON.parse(linkFilters)
  } catch {
    return null
  }
}

function getCampusContext(doc) {
  return doc?.campus || doc?.branch
}

function getLinkedDocCode(value) {
  if (typeof value !== 'string') return null
  const code = value.includes(' - ') ? value.split(' - ')[0]?.trim() : value
  if (!/^\d+$/.test(code)) return null
  return code || null
}

function getWardNameContext(value) {
  if (typeof value !== 'string' || !value) return null
  if (value.includes(' - ')) return null
  return value
}

export function getContextualLinkFilters(field, doc, baseFilters = null) {
  if (!field || field.fieldtype !== 'Link' || !doc) {
    return baseFilters
  }

  const campus = getCampusContext(doc)
  const wardCode = getLinkedDocCode(doc.ward)
  const wardName = getWardNameContext(doc.ward)
  const filtersByDoctype = {
    'CRM Ward': doc.province ? { province: doc.province } : null,
    'CRM High School': {
      ...(doc.province ? { province_name: doc.province } : {}),
      ...(wardCode ? { ward_code: wardCode } : {}),
      ...(wardName ? { ward_name: wardName } : {}),
    },
    'CRM Department': campus ? { campus } : null,
    'CRM Campaign': campus ? { campus } : null,
    'CRM Staff': {
      ...(campus ? { campus } : {}),
      ...(doc.department ? { department: doc.department } : {}),
    },
    'CRM Event': {
      ...(doc.crm_campaign ? { crm_campaign: doc.crm_campaign } : {}),
      ...(doc.province ? { province: doc.province } : {}),
    },
  }
  const contextFilters = filtersByDoctype[field.options]
  if (!contextFilters || Object.keys(contextFilters).length === 0) {
    return baseFilters
  }

  return {
    ...(baseFilters || {}),
    ...contextFilters,
  }
}

export function getProvinceScopedLinkFilters(field, doc, baseFilters = null) {
  return getContextualLinkFilters(field, doc, baseFilters)
}

export function getDependentFieldsToClear(fieldname, doc = {}) {
  const dependencies = {
    province: ['ward', 'high_school', 'crm_event'],
    ward: ['high_school'],
    branch: ['crm_campaign'],
    campus: ['department', 'crm_campaign'],
    department: ['assigned_to'],
    crm_campaign: ['crm_event'],
  }

  return (dependencies[fieldname] || []).filter((dependentField) =>
    Object.hasOwn(doc, dependentField),
  )
}

/**
 * Process a raw field meta object into a UI-ready field object.
 * Returns a NEW object — never mutates the input.
 *
 * Applies in order:
 *   1. Clone raw field
 *   2. Perm level overrides (from server layout API)
 *   3. Script property overrides (from setFieldProperty)
 *   4. Select options: string → [{label, value}] array
 *   5. Link options='User' → fieldtype='User'
 *
 * @param {object} rawField - original field meta from doctypesMeta
 * @param {object} [options]
 * @param {object} [options.permOverrides] - { fieldname: { read_only: 1 } }
 * @param {object} [options.propertyOverrides] - { fieldname: { hidden: true } }
 * @returns {object} processed field (fresh object)
 */
export function processField(rawField, options = {}) {
  if (!rawField) return null

  const { permOverrides = {}, propertyOverrides = {} } = options

  // 1. Clone
  let field = { ...rawField }

  // 2. Perm level overrides (security — from server)
  const perm = permOverrides[field.fieldname]
  if (perm) {
    Object.assign(field, perm)
  }

  // 3. Script property overrides (highest priority)
  const scriptOverride = propertyOverrides[field.fieldname]
  if (scriptOverride) {
    Object.assign(field, scriptOverride)
  }

  // 4. Select options: string → array
  if (field.fieldtype === 'Select' && typeof field.options === 'string') {
    field.options = field.options.split('\n').map((option) => ({
      label: option,
      value: option,
    }))

    if (field.options[0]?.value !== '' && field.reqd !== 1) {
      field.options.unshift({ label: '', value: '' })
    }
  }

  // 5. Link with options='User' → fieldtype='User'
  if (field.fieldtype === 'Link' && field.options === 'User') {
    field.fieldtype = 'User'
  }

  return field
}

/**
 * Find mandatory fields that are missing values in the doc.
 * Respects script overrides for reqd and hidden.
 *
 * @param {Array} fields - raw field meta array from doctypesMeta
 * @param {object} doc - the document data
 * @param {object} [options]
 * @param {object} [options.propertyOverrides] - { fieldname: { reqd: true, hidden: false } }
 * @param {object} [options.doctypesMeta] - for resolving parent meta in mandatory_depends_on
 * @returns {string[]} array of missing field labels
 */
export function findMissingMandatory(fields, doc, options = {}) {
  if (!fields || fields.length === 0) return []
  if (!doc) return []

  const { propertyOverrides = {}, doctypesMeta = {} } = options
  const missingFields = []

  for (const df of fields) {
    const overrides = propertyOverrides[df.fieldname] || {}

    // Determine if field is hidden (script override wins)
    const isHidden =
      overrides.hidden !== undefined ? overrides.hidden : df.hidden
    if (isHidden) continue

    // Determine if field is required (script override wins)
    let isRequired
    if (overrides.reqd !== undefined) {
      isRequired = overrides.reqd
    } else if (df.reqd) {
      isRequired = true
    } else {
      let parent = doctypesMeta[df.parent] || null
      isRequired = evaluateExpression(df.mandatory_depends_on, doc, parent)
    }

    if (!isRequired) continue

    const value = doc[df.fieldname]
    if (
      value === undefined ||
      value === null ||
      (typeof value === 'string' && value.trim() === '') ||
      (Array.isArray(value) && value.length === 0)
    ) {
      missingFields.push(df.label || df.fieldname)
    }
  }

  return missingFields
}
