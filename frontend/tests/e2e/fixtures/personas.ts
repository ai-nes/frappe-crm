export type Persona =
  | 'saleA'
  | 'saleB'
  | 'leadSales'
  | 'marketing'
  | 'admissionsDirector'
  | 'reviewer'
  | 'systemManager'

const browserPersonas = new Set<Persona>(['saleA', 'saleB', 'leadSales'])

export function storageStateFor(persona: Persona): string {
  if (!browserPersonas.has(persona)) {
    throw new Error(
      `${persona} is API/bench-only; it must not be substituted with browser API calls.`,
    )
  }
  return `playwright/.auth/${persona}.json`
}

export function isBrowserPersona(persona: Persona): boolean {
  return browserPersonas.has(persona)
}
