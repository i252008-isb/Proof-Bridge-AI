"""End-to-end offline demo: AI-powered customer support & refund investigation.

Scenario (synthetic, no real customer data): a customer bought "SonicWave
Pro Wireless Headphones", the left ear cup arrived cracked, and the customer
requests a refund. The demo runs every stage of the pipeline visibly:

    0. synthetic fixtures (receipt, listing, chat, delivery, policy, photos)
    1. OCR (receipt scan image -> readable text)
    2. ticket understanding (claims, issue type)
    3. evidence extraction (batch, per-item isolation)
    4. vision AI (photo inspection; mock output clearly labeled)
    5. refund policy extraction (rules with verbatim source quotes)
    6. semantic matching (claims vs evidence relevance)
    7. policy evaluation + recommendation (main pipeline)
    8. structured investigation report (JSON)

With no real providers configured, every AI stage uses the deterministic
offline mocks and every result is labeled mock/heuristic. Stage 9 then
shows, clearly labeled as a DEMO SIMULATION, what a genuine vision output
would add to the final recommendation. No findings are hardcoded and the
pipeline is never bypassed.

Usage:
    python examples/run_demo.py
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from proofbridge_ai import (
    FINAL_DECISION_NOTICE,
    EvidenceCategory,
    EvidenceInput,
    EvidenceUpload,
    OCRNotAvailableError,
    Settings,
    SupportTicket,
    VisionStatus,
    VisualAnalysisResult,
    VisualObservation,
    analyze_support_case,
    analyze_visual_evidence,
    compare_support_evidence,
    extract_document,
    extract_evidence_batch,
    extract_refund_policy,
    extract_ticket_claims,
    generate_investigation_report,
    get_settings,
)
from proofbridge_ai.services import support_case_analyzer

EXAMPLES_DIR = Path(__file__).parent
DEMO_DIR = EXAMPLES_DIR / "demo_data"
CASE_ID = "CASE-DEMO-2026"
ORDER_ID = "ORD-DEMO-2026"
PRODUCT = "SonicWave Pro Wireless Headphones"
PURCHASE = datetime.now(timezone.utc) - timedelta(days=4)
DATE_TEXT = f"{PURCHASE.strftime('%B')} {PURCHASE.day}, {PURCHASE.year}"

RECEIPT_TEXT = (
    "SONICWAVE STORE - Receipt\n"
    f"Order #{ORDER_ID}\n"
    f"Date: {DATE_TEXT}\n"
    f"Product: {PRODUCT} (model SW-PRO-X)\n"
    "Quantity: 1\n"
    "Total: $49.99\n"
    "Payment: card ending 1234"
)

POLICY_TEXT = (
    "Items may be returned within 30 days of purchase. "
    "Items that arrive damaged may be replaced or refunded when "
    "photographic proof of the damage is provided. "
    "A refund requires the original receipt."
)

LISTING_TEXT = (
    f"{PRODUCT} - Product Listing\n"
    "Model: SW-PRO-X\n"
    "Over-ear wireless headphones, matte black, foldable, 40h battery.\n"
    "Included: carrying case, USB-C cable, 3.5mm aux cable."
)

CHAT_TEXT = (
    "customer: Hi, my headphones arrived and the left ear cup is cracked.\n"
    "seller: Hello! Sorry to hear that. Could you send a photo of the damage?\n"
    "customer: Sure, photo attached.\n"
    "seller: Thank you. If the damage is confirmed we will replace or "
    "refund your order."
)

DELIVERY_TEXT = (
    "Delivery record\n"
    f"Order #{ORDER_ID}\n"
    f"Delivered: {DATE_TEXT}\n"
    "Carrier: ShipFast\n"
    "Tracking: TRK-98765"
)

TICKET = SupportTicket(
    case_id=CASE_ID,
    complaint=(
        f"My order {ORDER_ID} arrived damaged: the left ear cup is cracked. "
        "I contacted the seller and I want a refund."
    ),
    product_name=PRODUCT,
    order_id=ORDER_ID,
    requested_resolution="refund",
    purchase_date=PURCHASE,
)


def _section(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def _make_fixtures() -> None:
    DEMO_DIR.mkdir(exist_ok=True)

    (DEMO_DIR / "receipt.txt").write_text(RECEIPT_TEXT, encoding="utf-8")
    (DEMO_DIR / "product_listing.txt").write_text(LISTING_TEXT, encoding="utf-8")
    (DEMO_DIR / "seller_chat.txt").write_text(CHAT_TEXT, encoding="utf-8")
    (DEMO_DIR / "delivery_record.txt").write_text(DELIVERY_TEXT, encoding="utf-8")
    (DEMO_DIR / "refund_policy.txt").write_text(POLICY_TEXT, encoding="utf-8")

    receipt = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(receipt)
    for index, line in enumerate(RECEIPT_TEXT.splitlines()):
        draw.text((30, 20 + index * 26), line, fill="black")
    receipt.save(DEMO_DIR / "receipt_scan.png")

    photo = Image.new("RGB", (640, 420), "#e8e8e8")
    draw = ImageDraw.Draw(photo)
    draw.arc((120, 60, 520, 340), start=180, end=360, fill="black", width=18)
    draw.ellipse((90, 240, 220, 390), outline="black", width=14)
    draw.ellipse((420, 240, 550, 390), outline="black", width=14)
    draw.line([(140, 270), (160, 310), (135, 330), (175, 365)], fill="red", width=6)
    draw.line([(160, 310), (185, 300), (190, 330)], fill="red", width=5)
    draw.text((430, 40), "Customer photo:", fill="black")
    draw.text((430, 64), "cracked left ear cup", fill="black")
    photo.save(DEMO_DIR / "damaged_photo.png")

    print(f"Fixtures written to {DEMO_DIR}")
    for path in sorted(DEMO_DIR.iterdir()):
        print(f"  - {path.name}")


def _upload(evidence_id: str, filename: str, data: bytes, category) -> EvidenceUpload:
    return EvidenceUpload(
        file_bytes=data,
        evidence_input=EvidenceInput(
            evidence_id=evidence_id,
            filename=filename,
            uploaded_by="customer",
            category=category,
        ),
        content_type="image/png" if filename.endswith(".png") else None,
    )


def _build_uploads() -> list[EvidenceUpload]:
    return [
        _upload(
            "EVD-1",
            "receipt.txt",
            (DEMO_DIR / "receipt.txt").read_bytes(),
            EvidenceCategory.PURCHASE_RECORD,
        ),
        _upload(
            "EVD-2",
            "product_listing.txt",
            (DEMO_DIR / "product_listing.txt").read_bytes(),
            EvidenceCategory.PRODUCT_LISTING,
        ),
        _upload(
            "EVD-3",
            "seller_chat.txt",
            (DEMO_DIR / "seller_chat.txt").read_bytes(),
            EvidenceCategory.CONVERSATION,
        ),
        _upload(
            "EVD-4",
            "delivery_record.txt",
            (DEMO_DIR / "delivery_record.txt").read_bytes(),
            EvidenceCategory.DELIVERY_RECORD,
        ),
        _upload(
            "EVD-5",
            "damaged_photo.png",
            (DEMO_DIR / "damaged_photo.png").read_bytes(),
            EvidenceCategory.PRODUCT_IMAGE,
        ),
    ]


def _stage_ocr() -> None:
    _section("STAGE 1/9 - OCR (receipt scan image -> readable text)")
    try:
        result = extract_document(
            (DEMO_DIR / "receipt_scan.png").read_bytes(),
            "receipt_scan.png",
            content_type="image/png",
        )
        print("OCR extracted:")
        for line in result.normalized_text.splitlines():
            print(f"  | {line}")
    except OCRNotAvailableError:
        print(
            "[OCR UNAVAILABLE] Tesseract is not installed in this "
            "environment. The OCR service was invoked and reported the "
            "limitation honestly; the demo continues with the receipt "
            "text file. Install Tesseract (see docs/ai/OCR_SETUP.md) to "
            "see live OCR output."
        )


def _stage_ticket() -> None:
    _section("STAGE 2/9 - Ticket understanding (claims, issue type)")
    result = extract_ticket_claims(TICKET)
    print(f"Issue type : {result.issue_type.value}")
    print(f"Requested  : {result.requested_resolution or '(not stated)'}")
    print(f"Summary    : {result.customer_claim_summary}")
    for claim in result.extracted_claims:
        print(
            f"  claim {claim.id} [{claim.verification_status.value}] "
            f"source={claim.source}: {claim.claim}"
        )
    for warning in result.warnings:
        print(f"  [warning {warning.code}] {warning.message}")
    return result


def _stage_evidence(uploads: list[EvidenceUpload]) -> list:
    _section("STAGE 3/9 - Evidence extraction (batch)")
    batch = extract_evidence_batch(uploads)
    for item in batch.items:
        print(
            f"  {item.evidence_id} ({item.kind.value}, "
            f"{item.category.value if item.category else '?'}): {item.summary}"
        )
        for fact in item.identified_facts:
            print(f"      fact: {fact}")
    for failure in batch.failures:
        print(
            f"  [FAILED, isolation demo] {failure.evidence_id}: "
            f"{failure.error_type}: {failure.message}"
        )
    return batch.items


def _stage_vision() -> None:
    _section("STAGE 4/9 - Vision AI (damaged product photo)")
    result = analyze_visual_evidence(
        (DEMO_DIR / "damaged_photo.png").read_bytes(),
        EvidenceInput(evidence_id="EVD-5", filename="damaged_photo.png"),
        content_type="image/png",
    )
    print(f"Status       : {result.status.value}")
    print(f"Observations : {len(result.visual_observations)}")
    for observation in result.visual_observations:
        print(f"  - {observation.observation} (confidence {observation.confidence})")
    for limitation in result.limitations:
        print(f"  limitation: {limitation}")
    for warning in result.warnings:
        print(f"  [warning {warning.code}] {warning.message}")


def _stage_policy() -> None:
    _section("STAGE 5/9 - Refund policy extraction")
    policy = extract_refund_policy(
        policy_text=POLICY_TEXT,
        policy_id="policy-demo",
        policy_name="SonicWave Store Refund Policy",
    )
    print(f"Policy: {policy.policy_name} ({len(policy.rules)} rules)")
    for rule in policy.rules:
        print(f"  rule {rule.rule_id} [{rule.category.value}]")
        print(f"      quote    : {rule.source_quote}")
        print(f"      evidence : {rule.requires_evidence}")
    for warning in policy.policy_extraction_warnings:
        print(f"  [warning {warning.code}] {warning.message}")
    return policy


def _stage_similarity(claims, items) -> None:
    _section("STAGE 6/9 - Semantic matching (claims vs evidence)")
    result = compare_support_evidence(claims, items)
    print(f"Method: {result.method.value}")
    for limitation in result.limitations:
        print(f"  limitation: {limitation}")
    by_claim: dict[str, list] = {}
    for match in result.matches:
        by_claim.setdefault(match.claim_id, []).append(match)
    for claim in claims:
        top = sorted(
            by_claim.get(claim.id, []), key=lambda m: m.score, reverse=True
        )[:3]
        if not top:
            print(f"  claim {claim.id}: no relevant evidence")
            continue
        for match in top:
            print(
                f"  claim {claim.id} <-> {match.evidence_id}: "
                f"score={match.score:.2f} ({match.method.value})"
            )


def _run_pipeline(
    uploads: list[EvidenceUpload], policy, scripted_vision: bool = False
):
    settings = get_settings()
    visual_label = (
        "[DEMO SIMULATION - scripted vision provider, not a real model]"
        if scripted_vision
        else ""
    )
    original = support_case_analyzer.analyze_visual_evidence
    if scripted_vision:

        def scripted(file_bytes, evidence_input, content_type=None, **kwargs):
            return VisualAnalysisResult(
                evidence_id=evidence_input.evidence_id,
                status=VisionStatus.ANALYZED,
                visual_observations=[
                    VisualObservation(
                        observation="A visible crack along the left ear cup",
                        confidence=0.9,
                    )
                ],
                requires_human_review=True,
            )

        support_case_analyzer.analyze_visual_evidence = scripted
    try:
        return asyncio.run(
            analyze_support_case(
                TICKET,
                uploads,
                refund_policy=policy,
                settings=settings,
            )
        ), visual_label
    finally:
        support_case_analyzer.analyze_visual_evidence = original


def _stage_pipeline(uploads, policy) -> None:
    _section("STAGE 7/9 - Policy evaluation + recommendation")
    result, _ = _run_pipeline(uploads, policy)
    print("Claim assessments:")
    for assessment in result.claims:
        print(
            f"  {assessment.claim_id} [{assessment.status.value}]: "
            f"{assessment.claim[:80]}..."
        )
    print("Policy rule assessments:")
    if result.policy_evaluation:
        for rule in result.policy_evaluation.rule_assessments:
            print(
                f"  {rule.rule_id} [{rule.assessment.value}]: "
                f"{rule.explanation}"
            )
    for contradiction in result.contradictions:
        print(f"  [contradiction {contradiction.field}] {contradiction.description}")
    for missing in result.missing_information:
        print(f"  [missing] {missing.description}")
    if result.recommendation:
        print(f"Recommendation: {result.recommendation.outcome.value}")
        print(f"  confidence  : {result.recommendation.confidence}")
        print(f"  reasoning   : {result.recommendation.reasoning}")
    return result


def _stage_report(result, items) -> None:
    _section("STAGE 8/9 - Structured investigation report")
    report = generate_investigation_report(result, TICKET, items)
    report_path = DEMO_DIR / "demo_report.json"
    report_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Report title      : {report.report_title}")
    print(f"Schema version    : {report.schema_version}")
    print(f"Recommended outcome: {report.recommended_outcome.value}")
    print(f"Timeline events   : {len(report.timeline)}")
    print(f"Evidence inventory: {len(report.evidence_inventory)} items")
    print(f"OCR findings      : {len(report.ocr_findings)}")
    print(f"Neutral summary   : {report.neutral_summary}")
    print(f"Final notice      : {report.final_decision_notice}")
    print(f"Full JSON written : {report_path}")


def _stage_simulation(uploads, policy) -> None:
    _section(
        "STAGE 9/9 - DEMO SIMULATION: what a genuine vision output adds"
    )
    result, label = _run_pipeline(uploads, policy, scripted_vision=True)
    print(f"Vision provider in this stage: {label}")
    print("This stage injects a scripted vision provider to demonstrate the")
    print("complete happy path. It is a labeled simulation - NOT real model")
    print("output and NOT the result of the honest mock run in stage 7.")
    print()
    for assessment in result.claims:
        print(f"  {assessment.claim_id} [{assessment.status.value}]: {assessment.claim}")
    if result.recommendation:
        print(f"Recommendation: {result.recommendation.outcome.value}")
        print(f"  reasoning: {result.recommendation.reasoning}")
    print(f"Human review: {result.requires_human_review}")
    print(f"Final notice: {FINAL_DECISION_NOTICE}")


def main() -> None:
    settings = get_settings()
    print("ProofBridge AI - Customer Support & Refund Investigation Demo")
    print(f"Providers: llm={settings.llm_provider} "
          f"vision={settings.vision_provider} "
          f"embeddings={settings.embeddings_provider} "
          f"(mock providers produce clearly labeled placeholder output)")

    _section("STAGE 0/9 - Synthetic fixtures")
    _make_fixtures()

    _stage_ocr()
    claims_result = _stage_ticket()
    uploads = _build_uploads()
    items = _stage_evidence(uploads)
    _stage_vision()
    policy = _stage_policy()
    _stage_similarity(claims_result.extracted_claims, items)
    pipeline_result = _stage_pipeline(uploads, policy)
    _stage_report(pipeline_result, items)
    _stage_simulation(uploads, policy)


if __name__ == "__main__":
    main()
