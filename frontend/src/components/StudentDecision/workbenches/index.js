import { defineAsyncComponent } from 'vue'

export const ACTION_WORKBENCH_REGISTRY = Object.freeze({
  'call-package:v1': defineAsyncComponent(() => import('./CallWorkbench.vue')),
  'email-package:v1': defineAsyncComponent(() => import('./EmailWorkbench.vue')),
})
export function workbenchFor(model) { return model?.package?.schema ? ACTION_WORKBENCH_REGISTRY[model.package.schema] || null : null }
