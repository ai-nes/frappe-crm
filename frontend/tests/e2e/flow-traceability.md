# Lead processing flow traceability

| Flow branch                                           | Browser suite                                | Authoritative non-browser evidence                                                                                   |
| ----------------------------------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Desk intake valid/invalid                             | `lead-intake.spec.ts`                        | `crm/api/test_student_intake.py`                                                                                     |
| Signed webhook HMAC, timestamp, nonce                 | —                                            | `crm/api/test_student_intake_webhook.py`                                                                             |
| Idempotency receipt/fingerprint                       | —                                            | Partial helper/contract coverage; canonical `submit_intake()` replay coverage remains required                       |
| Phone/email identity resolution and ambiguity         | Review UI only when fixture is deterministic | `crm/fcrm/test_student_intake_phone_email.py` (resolver contract only; command/review persistence remains uncovered) |
| Ownership and outcome UI; first-response SLA contract | `lead-detail-sla.spec.ts`                    | `crm/api/test_student_routing.py`, `crm/api/test_student_sla.py`                                                     |
| SLA warning/breach/escalation/digest                  | —                                            | `crm/api/test_lead_processing_flow_v2.py`, SLA worker tests                                                          |
| Evidence-backed lifecycle transition                  | `lead-lifecycle.spec.ts`                     | `crm/fcrm/test_lifecycle.py`, `crm/api/test_student_lifecycle_v2.py`                                                 |
| Non-Enrolled and Enrolled conversion                  | `lead-conversion.spec.ts`                    | `crm/fcrm/test_student_conversion.py`                                                                                |
| Recommendation accept/action/outcome                  | Deferred                                     | `crm/api/test_student_decision.py`                                                                                   |

Browser tests must not be treated as evidence for branches marked `—`.

## Coverage and execution evidence

The current Playwright inventory is **7 tests in 5 files**: one authentication
setup test and six lead-processing tests covering the browser suites listed above.
The inventory can be checked without running mutations:

```powershell
cd frontend
./node_modules/.bin/playwright.cmd test --list
```

The available guarded smoke evidence is **2/2 passed**: authentication against
`crm.localhost` and the negative intake case that verifies a Student cannot be
submitted without a phone or email. The generated report recorded
`expectedSite=crm.localhost` and `mutationGuard=enabled`.

The complete `npm run test:e2e` mutation run now passes **7/7** on the seeded
disposable cohort with the flags enabled. A clean reset of immutable audit rows
is still a separate fixture-teardown concern; the flags were disabled after the
run and the seeded manifest remains local-only.
