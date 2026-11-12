"""Regenerate docs/ai/sample_report.json from the labeled demo simulation."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "examples"))

import run_demo as demo  # noqa: E402

from proofbridge_ai.services.policy_extractor import extract_refund_policy  # noqa: E402


def main() -> None:
    demo._make_fixtures()
    uploads = demo._build_uploads()
    batch = __import__(
        "proofbridge_ai", fromlist=["extract_evidence_batch"]
    ).extract_evidence_batch(uploads)
    policy = extract_refund_policy(
        policy_text=demo.POLICY_TEXT,
        policy_id="policy-demo",
        policy_name="SonicWave Store Refund Policy",
    )
    result, _ = demo._run_pipeline(uploads, policy, scripted_vision=True)
    report = demo.generate_investigation_report(result, demo.TICKET, batch.items)
    report.limitations.append(
        "This sample report was generated for documentation with a clearly "
        "labeled scripted vision simulation; it is not the output of a real "
        "vision model."
    )
    out = Path(__file__).resolve().parent / "sample_report.json"
    out.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"wrote {out} (outcome={report.recommended_outcome.value}, "
        "generated with the clearly labeled scripted vision simulation)"
    )


if __name__ == "__main__":
    main()
