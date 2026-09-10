import { test } from './fixtures/auth'

test.skip('intake-review is API-only until a Sale/Lead Sales review inbox or direct route exists', async () => {
  // DecideStudentIntakeReviewModal exists, but is only opened from the result
  // of an intake submission. There is no role-scoped review route/list from
  // which an independently seeded review can be recovered after an error.
  // Phase 2 API coverage remains the authority for review CAS/permissions.
})
