<template>
  <section class="analysis-workspace flex h-full min-h-0 w-full flex-col" aria-label="Analysis and recommendations" data-testid="student-analysis-panel">
    <header class="analysis-header flex flex-col gap-4 border-b px-5 py-4 sm:flex-row sm:items-start sm:justify-between sm:px-6">
      <div class="min-w-0">
        <div class="analysis-kicker text-xs font-semibold tracking-[0.08em] text-ink-gray-5">{{ __('CASE INVESTIGATION') }}</div>
        <div class="mt-1 flex flex-wrap items-center gap-2">
          <h2 class="text-xl font-semibold tracking-tight text-ink-gray-9">{{ __('Analyze with AI') }}</h2>
          <Badge :label="statusLabel" :theme="statusTheme" variant="subtle" />
        </div>
        <p class="mt-1 max-w-2xl text-sm leading-6 text-ink-gray-6">{{ subtitle }}</p>
      </div>
      <div class="flex shrink-0 gap-2">
        <Button v-if="running" variant="subtle" :label="__('Stop')" @click="cancel" />
        <Button v-else variant="outline" icon-left="refresh-cw" :label="hasBrief ? __('Run again') : __('Start analysis')" @click="analyze()" />
      </div>
    </header>

    <div class="analysis-grid min-h-0 flex-1 overflow-y-auto lg:grid lg:grid-cols-[minmax(280px,0.9fr)_minmax(0,1.6fr)] lg:overflow-hidden">
      <aside class="trajectory-pane border-b px-5 py-5 sm:px-6 lg:min-h-0 lg:overflow-y-auto lg:border-b-0 lg:border-r">
        <div class="flex items-center justify-between">
          <div>
            <h3 class="text-sm font-semibold text-ink-gray-9">{{ __('Live trajectory') }}</h3>
            <p class="mt-1 text-xs leading-5 text-ink-gray-5">{{ __('The agent chooses the next evidence source from capability and access results.') }}</p>
          </div>
          <span v-if="nodes.length" class="text-xs tabular-nums text-ink-gray-5">{{ nodes.length }} {{ __('events') }}</span>
        </div>

        <ol class="mt-5 space-y-1" data-testid="analysis-graph">
          <li v-for="(node, index) in nodes" :key="node.node_id" class="trajectory-item relative pl-7">
            <span class="trajectory-marker" :class="markerClass(node.status)" aria-hidden="true">{{ nodeIcon(node.status) }}</span>
            <span v-if="index < nodes.length - 1" class="trajectory-line" aria-hidden="true" />
            <button type="button" class="trajectory-button w-full rounded-md px-3 py-2 text-left" :aria-expanded="Boolean(expanded[node.node_id])" @click="toggleNode(node.node_id)">
              <span class="block text-sm font-medium leading-5 text-ink-gray-8">{{ node.summary }}</span>
              <span class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-gray-5">
                <span>{{ navigationLabel(node) }}</span><span v-if="node.resource">· {{ node.resource }}</span><span>{{ statusCopy(node.status) }}</span>
              </span>
            </button>
            <div v-if="expanded[node.node_id]" class="trajectory-detail mx-3 mb-2 rounded-md px-3 py-3 text-xs leading-5 text-ink-gray-6">
              <p v-if="node.navigation_reason"><span class="font-medium text-ink-gray-8">{{ __('Why this path') }}:</span> {{ node.navigation_reason }}</p>
              <p v-if="node.tool" class="mt-1"><span class="font-medium text-ink-gray-8">{{ __('Tool') }}:</span> {{ node.tool }}</p>
              <p class="mt-1"><span class="font-medium text-ink-gray-8">{{ __('Evidence') }}:</span> {{ node.evidence_count || 0 }} {{ __('items') }}<span v-if="node.duration_ms !== undefined"> · {{ node.duration_ms }}ms</span></p>
              <div v-if="node.record_refs?.length" class="mt-2 space-y-1">
                <span class="font-medium text-ink-gray-8">{{ __('Inspect records') }}</span>
                <a v-for="record in node.record_refs" :key="record" class="evidence-link block truncate" :href="recordHref(node.resource, record)" target="_blank" rel="noopener" :title="record">{{ record }}</a>
              </div>
            </div>
          </li>
          <li v-if="!nodes.length" class="rounded-md border border-dashed border-outline-gray-2 px-3 py-5 text-sm leading-6 text-ink-gray-5">{{ running ? __('Waiting for the first evidence event.') : __('Start an analysis to see the investigation trajectory.') }}</li>
        </ol>

        <section v-if="reasoning.length" class="mt-6 border-t pt-5" aria-labelledby="analysis-reasoning-title">
          <div class="flex items-center justify-between"><h3 id="analysis-reasoning-title" class="text-sm font-semibold text-ink-gray-9">{{ __('Reasoning summary') }}</h3><span class="text-xs tabular-nums text-ink-gray-5">{{ reasoning.length }}</span></div>
          <p class="mt-1 text-xs leading-5 text-ink-gray-5">{{ __('Safe summaries only. No private chain-of-thought is shown.') }}</p>
          <ol class="mt-3 space-y-2" data-testid="analysis-reasoning">
            <li v-for="(step, index) in reasoning" :key="step.node_id || index" class="reasoning-row rounded-md px-3 py-3 text-xs leading-5 text-ink-gray-6">
              <p><span class="font-medium text-ink-gray-8">{{ __('Observed') }}:</span> {{ step.observed }}</p>
              <p class="mt-1"><span class="font-medium text-ink-gray-8">{{ __('Assessment') }}:</span> {{ step.analysis }}</p>
              <p class="mt-1"><span class="font-medium text-ink-gray-8">{{ __('Next move') }}:</span> {{ step.next_step }}</p>
              <p class="mt-1 text-ink-orange-5"><span class="font-medium">{{ __('Uncertainty') }}:</span> {{ step.uncertainty }}</p>
            </li>
          </ol>
        </section>
      </aside>

      <main class="assessment-pane min-w-0 px-5 py-5 sm:px-6 lg:min-h-0 lg:overflow-y-auto">
        <div v-if="changes.length" class="change-strip mb-5 rounded-md px-4 py-3" aria-live="polite">
          <div class="flex items-center justify-between gap-3"><h3 class="text-sm font-semibold text-ink-gray-9">{{ __('What changed') }}</h3><span class="text-xs text-ink-gray-5">{{ __('Since the previous analysis') }}</span></div>
          <ul class="mt-2 space-y-1 text-sm leading-6 text-ink-gray-7"><li v-for="change in changes" :key="change">{{ change }}</li></ul>
        </div>

        <section class="assessment-lead" aria-labelledby="assessment-title">
          <div class="flex flex-wrap items-center justify-between gap-3"><div><div class="analysis-kicker text-xs font-semibold tracking-[0.08em] text-ink-gray-5">{{ __('ASSESSMENT') }}</div><h3 id="assessment-title" class="mt-1 text-lg font-semibold text-ink-gray-9">{{ brief.current_situation || __('Building the case assessment') }}</h3></div><span v-if="brief.anchor?.context_revision" class="text-xs text-ink-gray-5">{{ __('Context') }} {{ brief.anchor.context_revision }}</span></div>
        </section>

        <div class="mt-6 grid gap-4 xl:grid-cols-2">
          <AssessmentGroup v-for="assessment in assessmentGroups" :key="assessment.key" :group="assessment" @inspect="inspectEvidence" />
        </div>

        <section v-if="brief.evidence_summary?.length" class="evidence-ledger mt-6 rounded-md px-4 py-4" aria-labelledby="evidence-ledger-title">
          <div class="flex items-center justify-between gap-3"><div><h3 id="evidence-ledger-title" class="text-sm font-semibold text-ink-gray-9">{{ __('Evidence consulted') }}</h3><p class="mt-1 text-xs text-ink-gray-5">{{ __('Open a permitted record to verify the assessment.') }}</p></div><span class="text-xs tabular-nums text-ink-gray-5">{{ brief.evidence_summary.length }} {{ __('sources') }}</span></div>
          <div class="mt-3 grid gap-3 sm:grid-cols-2">
            <div v-for="source in brief.evidence_summary" :key="source.resource" class="evidence-source rounded-md border border-outline-gray-2 bg-surface-white px-3 py-3">
              <div class="flex items-center justify-between gap-2"><span class="truncate text-sm font-medium text-ink-gray-8">{{ source.resource }}</span><Badge :label="source.status" :theme="source.status === 'succeeded' ? 'green' : source.status === 'forbidden' ? 'orange' : 'gray'" variant="subtle" /></div>
              <p class="mt-1 text-xs text-ink-gray-5">{{ source.evidence_count || 0 }} {{ __('items') }}<span v-if="source.forbidden_count"> · {{ source.forbidden_count }} {{ __('restricted') }}</span></p>
              <div v-if="source.record_refs?.length" class="mt-2 space-y-1"><a v-for="record in source.record_refs" :key="record" class="evidence-link block truncate text-xs" :href="recordHref(source.resource, record)" target="_blank" rel="noopener" :title="record">{{ record }}</a></div>
              <p v-else class="mt-2 text-xs text-ink-gray-5">{{ source.status === 'forbidden' ? __('Access restricted') : __('No record link returned') }}</p>
            </div>
          </div>
        </section>

        <section class="recommendations-section mt-6" aria-labelledby="recommended-actions-title">
          <div class="flex flex-wrap items-end justify-between gap-3"><div><div class="analysis-kicker text-xs font-semibold tracking-[0.08em] text-ink-gray-5">{{ __('NEXT BEST ACTION') }}</div><h3 id="recommended-actions-title" class="mt-1 text-lg font-semibold text-ink-gray-9">{{ __('Recommended actions') }}</h3></div><Badge v-if="brief.recommended_actions?.length" :label="`${brief.recommended_actions.length}`" theme="orange" variant="subtle" /></div>
          <div v-if="brief.recommended_actions?.length" class="mt-3 space-y-3">
            <article v-for="item in brief.recommended_actions" :key="item.action || item" class="recommendation-row rounded-md px-4 py-4">
              <h4 class="text-sm font-semibold leading-6 text-ink-gray-9">{{ item.action || item }}</h4>
              <p v-if="item.reason" class="mt-2 text-sm leading-6 text-ink-gray-7"><span class="font-medium text-ink-gray-8">{{ __('Why') }}:</span> {{ item.reason }}</p>
              <button v-if="item.based_on?.length" type="button" class="mt-2 text-left text-xs text-[--brand-ink] hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2" @click="inspectEvidence(item.based_on)">{{ __('Based on {0} evidence references', [item.based_on.length]) }}</button>
              <p v-if="item.expected_outcome" class="mt-2 text-xs leading-5 text-ink-gray-6"><span class="font-medium text-ink-gray-8">{{ __('Expected outcome') }}:</span> {{ item.expected_outcome }}</p>
              <p v-if="item.suggested_conversation" class="mt-3 rounded-md bg-surface-gray-2 px-3 py-2 text-sm leading-6 text-ink-gray-7"><span class="font-medium text-ink-gray-8">{{ __('Suggested conversation') }}:</span> {{ item.suggested_conversation }}</p>
              <Button class="mt-3" size="sm" variant="outline" :label="__('Review in Actions')" @click="emit('open-actions')" />
            </article>
          </div>
          <p v-else class="mt-3 rounded-md border border-dashed border-outline-gray-2 px-4 py-4 text-sm text-ink-gray-5">{{ running ? __('Recommendations will appear after the evidence is assessed.') : __('No grounded action recommendation was returned.') }}</p>
        </section>

        <div v-if="error" class="mt-6 rounded-md border border-ink-red-2 px-4 py-3 text-sm leading-6 text-ink-red-4" role="alert">{{ error }}</div>
        <div v-if="message" class="mt-6 rounded-md bg-surface-gray-1 px-4 py-3 text-sm leading-6 text-ink-gray-7" data-testid="analysis-answer">{{ message }}</div>
      </main>
    </div>

    <form class="analysis-composer flex gap-2 border-t px-5 py-3 sm:px-6" @submit.prevent="askMore">
      <FormControl v-model="question" class="flex-1" :disabled="running" :placeholder="__('Ask a focused question about this case...')" aria-label="Ask a focused question" />
      <Button type="submit" variant="solid" :label="__('Ask')" :disabled="running || !question.trim()" />
    </form>
  </section>
</template>

<script setup>
import { computed, defineComponent, h, onBeforeUnmount, ref } from 'vue'
import { Badge, Button, FormControl } from 'frappe-ui'
import { applyUIStreamEvent, consumeUIStream } from '@/components/AIChatbox/stream'

const props = defineProps({ student: { type: String, required: true }, contextRevision: { type: String, default: '' } })
const emit = defineEmits(['open-actions'])
const running = ref(false); const error = ref(''); const message = ref(''); const question = ref(''); const sessionId = ref(null); const previousBrief = ref(null)
const brief = ref({ facts: [], inferences: [], unknowns: [], recommended_actions: [], key_signals: [], what_matters_now: [], risks: [], missing_evidence: [], reasoning_steps: [] }); const reasoning = ref([]); const nodesById = ref({}); const expanded = ref({}); let activeRun = null
const nodes = computed(() => Object.values(nodesById.value)); const hasBrief = computed(() => Boolean(brief.value.current_situation || nodes.value.length)); const statusLabel = computed(() => running.value ? __('Investigating') : brief.value.status === 'insufficient' ? __('Needs evidence') : error.value ? __('Unable to finish') : hasBrief.value ? __('Assessment ready') : __('Not started')); const statusTheme = computed(() => running.value ? 'blue' : brief.value.status === 'insufficient' ? 'orange' : error.value ? 'red' : hasBrief.value ? 'green' : 'gray'); const subtitle = computed(() => running.value ? __('Following evidence as the case changes.') : hasBrief.value ? __('Evidence is separated from interpretation so the next decision stays grounded.') : __('Let the agent choose what to inspect from the Student record and available capabilities.'))
const assessmentGroups = computed(() => [
  { key: 'facts', label: __('Facts'), tone: 'neutral', items: brief.value.facts || [] },
  { key: 'inferences', label: __('Inferences'), tone: 'blue', items: brief.value.inferences || [] },
  { key: 'unknowns', label: __('Unknowns'), tone: 'amber', items: brief.value.unknowns || [] },
  { key: 'risks', label: __('Risks'), tone: 'red', items: brief.value.risks || [] },
  { key: 'what_matters_now', label: __('What matters now'), tone: 'orange', items: brief.value.what_matters_now || [] },
  { key: 'missing_evidence', label: __('Missing evidence'), tone: 'amber', items: brief.value.missing_evidence || [] },
])
const changes = computed(() => {
  if (!previousBrief.value) return []
  const current = brief.value; const previous = previousBrief.value; const output = []
  const compare = (field, label, property = 'statement') => { const before = (previous[field] || []).map((item) => typeof item === 'string' ? item : item[property]).filter(Boolean); const after = (current[field] || []).map((item) => typeof item === 'string' ? item : item[property]).filter(Boolean); after.filter((item) => !before.includes(item)).slice(0, 3).forEach((item) => output.push(`${label}: ${item}`)); if (field === 'inferences') before.filter((item) => !after.includes(item)).slice(0, 2).forEach((item) => output.push(`${__('Weakened or replaced hypothesis')}: ${item}`)) }
  compare('inferences', __('Strengthened or new hypothesis')); compare('risks', __('New or changed risk')); compare('unknowns', __('New unknown'))
  return output
})
const analysisCache = new Map(); const analysisInFlight = new Set(); const CACHE_TTL_MS = 5 * 60 * 1000
function analysisCacheKey(prompt) { return JSON.stringify([props.student, props.contextRevision || 'unknown', prompt.trim()]) }
function storageKey(key) { let hash = 2166136261; for (const char of key) { hash ^= char.charCodeAt(0); hash = Math.imul(hash, 16777619) } return `crm-student-analysis:${(hash >>> 0).toString(16)}` }
function loadCached(key) { let cached = analysisCache.get(key); if (!cached) { try { cached = JSON.parse(sessionStorage.getItem(storageKey(key)) || 'null') } catch { cached = null } } if (!cached || cached.expiresAt <= Date.now()) { if (cached) sessionStorage.removeItem(storageKey(key)); return null } analysisCache.set(key, cached); return cached }
function saveCached(key) { const cached = { expiresAt: Date.now() + CACHE_TTL_MS, sessionId: sessionId.value, message: message.value, brief: brief.value, reasoning: reasoning.value, nodes: nodesById.value }; analysisCache.set(key, cached); try { sessionStorage.setItem(storageKey(key), JSON.stringify(cached)) } catch { /* private browsing or quota limits */ } }
function restoreCached(cached) { sessionId.value = cached.sessionId || null; message.value = cached.message || ''; brief.value = cached.brief || brief.value; reasoning.value = cached.reasoning || cached.brief?.reasoning_steps || []; nodesById.value = cached.nodes || {}; running.value = false }
function csrfToken() { return typeof window === 'undefined' ? 'fetch' : window.csrf_token || window.frappe?.csrf_token || 'fetch' }
function toggleNode(id) { expanded.value[id] = !expanded.value[id] }
function nodeIcon(status) { return status === 'running' ? '…' : ['completed', 'succeeded'].includes(status) ? '✓' : ['failed', 'denied'].includes(status) ? '!' : '›' }
function markerClass(status) { return ['failed', 'denied'].includes(status) ? 'trajectory-marker-error' : ['completed', 'succeeded'].includes(status) ? 'trajectory-marker-done' : status === 'running' ? 'trajectory-marker-live' : 'trajectory-marker-neutral' }
function statusCopy(status) { return ({ running: __('in progress'), succeeded: __('received'), completed: __('complete'), failed: __('failed'), denied: __('restricted') }[status] || status || __('pending')) }
function navigationLabel(node) { return ({ select: __('selected'), describe: __('inspected'), expand: __('expanded'), refine: __('refined'), replace: __('changed direction') }[node.navigation] || __('considered')) }
function recordHref(resource, record) { const slug = String(resource || 'CRM Student').toLowerCase().replace(/^crm\s+/, '').replace(/\s+/g, '-'); return `/app/${slug}/${encodeURIComponent(record)}` }
function inspectEvidence(refs) { if (!refs?.length) return; const node = nodes.value.find((item) => item.record_refs?.some((ref) => refs.includes(ref))); if (node?.node_id) expanded.value[node.node_id] = true }
function addNode(activity) { if (!activity?.node_id) return; nodesById.value = { ...nodesById.value, [activity.node_id]: { ...nodesById.value[activity.node_id], ...activity } } }
function addReasoning(activity) { const step = activity?.reasoning || activity; if (!step?.observed || !step?.analysis || !step?.implication || !step?.uncertainty || !step?.next_step) return; const item = { ...step, node_id: activity?.node_id || `${reasoning.value.length}-${step.analysis}` }; if (!reasoning.value.some((current) => current.node_id === item.node_id)) reasoning.value = [...reasoning.value, item] }
function askMore() { const text = question.value.trim(); if (!text) return; question.value = ''; analyze(text) }
function analyze(prompt = __('Analyze this student and prepare an evidence-grounded assessment.')) { const normalizedPrompt = prompt.trim(); if (!normalizedPrompt) return; const key = analysisCacheKey(normalizedPrompt); if (activeRun?.cacheKey === key && running.value) return; if (analysisInFlight.has(key)) { error.value = __('This analysis is already running.'); return } const cached = loadCached(key); if (cached) { previousBrief.value = brief.value; cancel(); error.value = ''; restoreCached(cached); return } cancel(); previousBrief.value = hasBrief.value ? JSON.parse(JSON.stringify(brief.value)) : null; analysisInFlight.add(key); error.value = ''; message.value = ''; reasoning.value = []; brief.value = { facts: [], inferences: [], unknowns: [], recommended_actions: [], key_signals: [], what_matters_now: [], risks: [], missing_evidence: [], reasoning_steps: [] }; nodesById.value = {}; const controller = new AbortController(); const run = { controller, cacheKey: key, id: `${Date.now()}-${Math.random()}` }; activeRun = run; running.value = true; const body = { mode: 'student_analysis', analysis_context: { anchor_resource: 'CRM Student', anchor_id: props.student, context_revision: props.contextRevision || 'unknown' }, messages: [{ role: 'user', parts: [{ type: 'text', text: normalizedPrompt }] }] }; if (sessionId.value) body.id = sessionId.value; fetch('/api/method/crm.api.copilot_delegation.stream_chat', { method: 'POST', credentials: 'same-origin', signal: controller.signal, headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json', 'X-Frappe-CSRF-Token': csrfToken() }, body: JSON.stringify(body) }).then((response) => { if (!response.ok) throw new Error(__('Analysis request was rejected.')); return consumeUIStream(response, (event) => { if (activeRun !== run) return; const target = { id: 'analysis', text: message.value, streaming: true }; applyUIStreamEvent(event, target, run, true, (id) => { sessionId.value = id }, null, () => { running.value = false }, addNode, addReasoning); if (target.text) message.value = target.text; if (target.analysisBrief) { brief.value = target.analysisBrief; reasoning.value = target.analysisBrief.reasoning_steps || reasoning.value } }) }).then(() => { if (activeRun === run) { saveCached(key); running.value = false; activeRun = null } analysisInFlight.delete(key) }).catch((reason) => { analysisInFlight.delete(key); if (activeRun !== run || reason?.name === 'AbortError') return; error.value = reason?.message || __('Unable to complete the analysis.'); running.value = false; activeRun = null }) }
function cancel() { if (!activeRun) return; analysisInFlight.delete(activeRun.cacheKey); activeRun.controller.abort(); activeRun = null; running.value = false }
onBeforeUnmount(cancel)

const AssessmentGroup = defineComponent({ props: { group: { type: Object, required: true } }, emits: ['inspect'], setup(props, { emit }) { return () => h('section', { class: `assessment-group assessment-${props.group.tone}`, 'aria-labelledby': `assessment-${props.group.key}` }, [h('div', { class: 'flex items-center justify-between gap-3' }, [h('h3', { id: `assessment-${props.group.key}`, class: 'text-sm font-semibold text-ink-gray-9' }, __(props.group.label)), h('span', { class: 'text-xs tabular-nums text-ink-gray-5' }, String(props.group.items.length))]), props.group.items.length ? h('ul', { class: 'mt-3 space-y-3' }, props.group.items.map((item, index) => { const text = typeof item === 'string' ? item : item.statement; const refs = typeof item === 'object' ? item.based_on : []; return h('li', { key: `${text}-${index}`, class: 'assessment-item text-sm leading-6 text-ink-gray-7' }, [h('p', text), refs?.length ? h('button', { type: 'button', class: 'mt-1 text-left text-xs text-[--brand-ink] hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2', onClick: () => emit('inspect', refs) }, __('Trace to {0} evidence references', [refs.length])) : null, typeof item === 'object' && item.uncertainty ? h('p', { class: 'mt-1 text-xs text-ink-orange-5' }, `${__('Uncertainty')}: ${item.uncertainty}`) : null]) })) : h('p', { class: 'mt-3 text-sm text-ink-gray-5' }, __('No entries yet.'))]) } })
</script>

<style scoped>
.analysis-workspace { --analysis-ink: oklch(0.27 0.025 255); --analysis-surface: oklch(0.985 0.008 250); --analysis-paper: oklch(0.995 0.006 250); --analysis-line: oklch(0.88 0.018 250); --analysis-inset: oklch(0.965 0.018 250); --analysis-accent: oklch(0.68 0.16 55); --analysis-blue: oklch(0.52 0.14 250); background: var(--analysis-surface); }
.analysis-header, .analysis-composer { background: var(--analysis-paper); }
.analysis-kicker { color: var(--analysis-blue); }
.trajectory-pane { background: var(--analysis-paper); }
.trajectory-item { min-height: 3.5rem; }
.trajectory-marker { position: absolute; left: 0.125rem; top: 0.65rem; z-index: 1; display: flex; height: 1.25rem; width: 1.25rem; align-items: center; justify-content: center; border: 1px solid var(--analysis-line); border-radius: 999px; background: var(--analysis-paper); font-size: 0.7rem; font-weight: 700; }
.trajectory-marker-live { border-color: var(--analysis-accent); color: var(--analysis-accent); }
.trajectory-marker-done { border-color: oklch(0.65 0.14 145); color: oklch(0.45 0.12 145); }
.trajectory-marker-error { border-color: oklch(0.62 0.16 25); color: oklch(0.52 0.16 25); }
.trajectory-marker-neutral { color: var(--analysis-blue); }
.trajectory-line { position: absolute; left: 0.7rem; top: 1.85rem; bottom: -0.25rem; width: 1px; background: var(--analysis-line); }
.trajectory-button { transition: background-color 180ms ease-out, transform 120ms ease-out; }
.trajectory-button:hover { background: oklch(0.96 0.02 250); transform: translateX(2px); }
.trajectory-button:active { transform: translateX(1px); }
.trajectory-button:focus-visible { outline: 2px solid var(--analysis-accent); outline-offset: 2px; }
.trajectory-detail { background: oklch(0.965 0.018 250); }
.evidence-link { color: var(--analysis-blue); }
.evidence-link:hover { text-decoration: underline; }
.reasoning-row { background: oklch(0.965 0.018 250); }
.assessment-lead { border-bottom: 1px solid var(--analysis-line); padding-bottom: 1rem; }
.assessment-group { border-top: 2px solid var(--analysis-line); padding-top: 0.75rem; }
.assessment-blue { border-color: oklch(0.68 0.12 250); }
.assessment-amber { border-color: oklch(0.74 0.14 80); }
.assessment-red { border-color: oklch(0.65 0.15 25); }
.assessment-orange { border-color: var(--analysis-accent); }
.assessment-item { border-bottom: 1px solid oklch(0.91 0.012 250); padding-bottom: 0.75rem; }
.assessment-item:last-child { border-bottom: 0; padding-bottom: 0; }
.change-strip { background: oklch(0.96 0.04 75); border: 1px solid oklch(0.85 0.11 80); }
.recommendation-row { background: var(--analysis-paper); border: 1px solid var(--analysis-line); border-top: 2px solid var(--analysis-accent); }
.evidence-ledger { background: var(--analysis-inset); }
@media (prefers-reduced-motion: reduce) { .trajectory-button { transition: none; } .trajectory-button:hover, .trajectory-button:active { transform: none; } }
</style>
