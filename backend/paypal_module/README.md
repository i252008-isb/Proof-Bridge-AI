# Person 4 PayPal submission (reference only)

This folder preserves Person 4's original submission for traceability. The
ProofBridge backend does **not** import or mount this package.

The integrated read-only functionality lives in:

- [`app/services/paypal_service.py`](../app/services/paypal_service.py) —
  capture and order lookups, response sanitization, and payment-state
  normalization.
- [`app/routers/paypal.py`](../app/routers/paypal.py) — project-scoped,
  authenticated read-only endpoints.

Do **not** run `paypal_module/dev_server.py` or mount
`paypal_module/router.py` in the ProofBridge backend. Its `create`,
`capture`, `authorize`, `authorizations/.../capture`, and `.../void`
endpoints move, hold, or release money and conflict with ProofBridge's
no-escrow and no-payment-execution boundary.

No dependency from this folder (`requests`) was added to the backend because
the backend already uses `httpx`. Person 4's offline state-mapping cases were
ported into `tests/test_paypal_order_info.py` and pass there.

See [`PERSON4_INTEGRATION_REPORT.md`](../PERSON4_INTEGRATION_REPORT.md) for
the full decision record.
