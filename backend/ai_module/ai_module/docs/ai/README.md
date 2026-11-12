# ProofBridge AI — Documentation Index

AI module documentation for Person 2 (FastAPI/PostgreSQL backend) and
future maintainers. Central principle: **customers submit the proof,
ProofBridge AI investigates the proof, human support agents make the
final decisions.**

| Document | Contents |
| --- | --- |
| [API_CONTRACT.md](API_CONTRACT.md) | Exact public function signatures, input/output models, JSON examples, error mapping |
| [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) | End-to-end backend integration flow with code |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Pipeline stages, module map, data flow, provider abstraction |
| [SCHEMAS.md](SCHEMAS.md) | Data contract: enums, models, report structure |
| [CONFIGURATION.md](CONFIGURATION.md) | Environment variables and settings |
| [ERROR_HANDLING.md](ERROR_HANDLING.md) | Exception hierarchy and how the backend maps errors to HTTP |
| [LIMITATIONS.md](LIMITATIONS.md) | Honest limitations: mock providers, vision, OCR, heuristics |
| [OCR_SETUP.md](OCR_SETUP.md) | Tesseract installation and OCR configuration |
| [VISION_SETUP.md](VISION_SETUP.md) | Vision provider configuration and expectations |
| [POLICY_EVALUATION.md](POLICY_EVALUATION.md) | How refund policies are extracted and evaluated |
| [TESTING.md](TESTING.md) | Test suite, scenario tests A–J, current results |
| [DEMO_GUIDE.md](DEMO_GUIDE.md) | Offline demo walkthrough |
| [HANDOFF_CHECKLIST.md](HANDOFF_CHECKLIST.md) | Integration checklist and message for Person 2 |
| [MODULE_STRUCTURE.md](MODULE_STRUCTURE.md) | File-by-file module map |

The `sample_report.json` next to this file is a full example of the
structured `InvestigationReport` output.
