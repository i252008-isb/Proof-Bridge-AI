"""Cross-source consistency verification of case facts.

Compares the same fact (order number, product name, dates, price,
currency, quantity, seller name) as stated by different sources: the
customer ticket, receipt extraction, backend order-system data, and
payment-provider data. Results are factual:

- agreement across sources is reported as ``supported``;
- differing values are reported as contradictions with both sources
  referenced — never as accusations of dishonesty or fraud;
- a value that cannot be checked because the other source is missing is
  reported as missing information, not as a contradiction.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable

from proofbridge_ai.exceptions import InputValidationError
from proofbridge_ai.logging_utils import get_logger
from proofbridge_ai.schemas import (
    Contradiction,
    ConversationAnalysis,
    CrossSourceFinding,
    FieldValueObservation,
    MissingInformation,
    OrderInformation,
    PaymentInformation,
    PurchaseInformation,
    SupportTicket,
    TicketAnalysisResult,
    VerificationStatus,
)

logger = get_logger("services.cross_source_verifier")

_Normalizer = Callable[[object], str | None]

_FUZZY_OVERLAP_THRESHOLD = 0.5


def _identity(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _collapse(text: object) -> str | None:
    normalized = _identity(text)
    if normalized is None:
        return None
    return re.sub(r"\s+", " ", normalized).lower()


def _upper(value: object) -> str | None:
    normalized = _identity(value)
    return normalized.upper() if normalized is not None else None


def _date(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return text


def _price(value: object) -> str | None:
    if value is None:
        return None
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return None


def _tokens(normalized: str) -> set[str]:
    return {token for token in normalized.split() if len(token) >= 2}


def verify_cross_source(
    ticket: SupportTicket,
    ticket_analysis: TicketAnalysisResult | None = None,
    purchase_information: PurchaseInformation | None = None,
    order_information: OrderInformation | None = None,
    payment_information: PaymentInformation | None = None,
    conversation_analysis: ConversationAnalysis | None = None,
) -> tuple[list[CrossSourceFinding], list[Contradiction], list[MissingInformation]]:
    """Compare case facts across all available sources.

    Args:
        ticket: Backend-supplied support ticket (customer allegations).
        ticket_analysis: Ticket analysis result (used only when the ticket
            itself lacks a date, for LLM-verified complaint dates).
        purchase_information: Facts extracted from receipt/order evidence.
        order_information: Backend order-system data, used verbatim.
        payment_information: Payment-provider data (e.g. PayPal), used
            strictly as an additional consistency source.
        conversation_analysis: Chat analysis; internal contradictions found
            in the conversation are reported factually.

    Returns:
        (findings, contradictions, missing_information) — contradictions
        never accuse any party of dishonesty.
    """
    if not isinstance(ticket, SupportTicket):
        raise InputValidationError("ticket must be a SupportTicket")
    ticket_analysis = (
        ticket_analysis
        if isinstance(ticket_analysis, TicketAnalysisResult)
        else None
    )

    ticket_date = ticket.purchase_date or (
        ticket_analysis.purchase_date_mentioned if ticket_analysis else None
    )

    field_specs: list[tuple[str, str, bool, _Normalizer, list[FieldValueObservation]]] = [
        (
            "order_id",
            "order number",
            False,
            _upper,
            [
                _observation("customer ticket", ticket.order_id),
                _observation(
                    "receipt",
                    purchase_information.order_number if purchase_information else None,
                    purchase_information.evidence_id if purchase_information else None,
                ),
                _observation(
                    "order system",
                    order_information.order_id if order_information else None,
                ),
                _observation(
                    "payment provider",
                    payment_information.order_id if payment_information else None,
                ),
            ],
        ),
        (
            "product_name",
            "product name",
            True,
            _collapse,
            [
                _observation("customer ticket", ticket.product_name),
                _observation(
                    "receipt",
                    purchase_information.product_name if purchase_information else None,
                    purchase_information.evidence_id if purchase_information else None,
                ),
                _observation(
                    "order system",
                    order_information.product_name if order_information else None,
                ),
            ],
        ),
        (
            "product_model",
            "product model",
            False,
            _collapse,
            [
                _observation(
                    "receipt",
                    purchase_information.product_model if purchase_information else None,
                    purchase_information.evidence_id if purchase_information else None,
                ),
                _observation(
                    "order system",
                    order_information.product_model if order_information else None,
                ),
            ],
        ),
        (
            "seller_name",
            "seller name",
            True,
            _collapse,
            [
                _observation(
                    "receipt",
                    purchase_information.seller_name if purchase_information else None,
                    purchase_information.evidence_id if purchase_information else None,
                ),
                _observation(
                    "order system",
                    order_information.seller_name if order_information else None,
                ),
                _observation(
                    "payment provider (merchant)",
                    payment_information.merchant if payment_information else None,
                ),
            ],
        ),
        (
            "purchase_date",
            "purchase date",
            False,
            _date,
            [
                _observation("customer ticket", ticket_date),
                _observation(
                    "receipt",
                    purchase_information.purchase_date if purchase_information else None,
                    purchase_information.evidence_id if purchase_information else None,
                ),
                _observation(
                    "order system",
                    order_information.purchase_date if order_information else None,
                ),
            ],
        ),
        (
            "price",
            "price",
            False,
            _price,
            [
                _observation(
                    "receipt",
                    purchase_information.price if purchase_information else None,
                    purchase_information.evidence_id if purchase_information else None,
                ),
                _observation(
                    "order system",
                    order_information.price if order_information else None,
                ),
                _observation(
                    "payment provider (amount)",
                    payment_information.amount if payment_information else None,
                ),
            ],
        ),
        (
            "currency",
            "currency",
            False,
            _upper,
            [
                _observation(
                    "receipt",
                    purchase_information.currency if purchase_information else None,
                    purchase_information.evidence_id if purchase_information else None,
                ),
                _observation(
                    "order system",
                    order_information.currency if order_information else None,
                ),
                _observation(
                    "payment provider",
                    payment_information.currency if payment_information else None,
                ),
            ],
        ),
        (
            "quantity",
            "quantity",
            False,
            _identity,
            [
                _observation(
                    "receipt",
                    purchase_information.quantity if purchase_information else None,
                    purchase_information.evidence_id if purchase_information else None,
                ),
                _observation(
                    "order system",
                    order_information.quantity if order_information else None,
                ),
            ],
        ),
    ]

    findings: list[CrossSourceFinding] = []
    contradictions: list[Contradiction] = []
    missing_information: list[MissingInformation] = []
    counter = 0

    for key, label, fuzzy, _normalize, observations in field_specs:
        present = [obs for obs in observations if _normalize(obs.value) is not None]
        if len(present) < 2:
            continue
        counter += 1
        status = _agreement_status(present, _normalize, fuzzy)
        agreeing_ids = [
            obs.evidence_id
            for obs in present
            if obs.evidence_id
            and _normalize(obs.value) == _normalize(present[0].value)
        ]
        if status is VerificationStatus.CONTRADICTED:
            contradictions.append(
                Contradiction(
                    id=f"contradiction-{counter}",
                    field=key,
                    description=_contradiction_description(label, present),
                    evidence_ids=[
                        obs.evidence_id for obs in present if obs.evidence_id
                    ],
                    observed_values=present,
                )
            )
            findings.append(
                CrossSourceFinding(
                    id=f"finding-{counter}",
                    field=key,
                    status=status,
                    observed_values=present,
                    rationale=_contradiction_description(label, present),
                    supporting_evidence_ids=agreeing_ids,
                    contradicting_evidence_ids=[
                        obs.evidence_id
                        for obs in present
                        if obs.evidence_id
                        and _normalize(obs.value) != _normalize(present[0].value)
                    ],
                    requires_human_review=True,
                )
            )
        else:
            findings.append(
                CrossSourceFinding(
                    id=f"finding-{counter}",
                    field=key,
                    status=status,
                    observed_values=present,
                    rationale=_agreement_rationale(label, present, status),
                    supporting_evidence_ids=[
                        obs.evidence_id for obs in present if obs.evidence_id
                    ],
                    requires_human_review=True,
                )
            )

    missing_information.extend(
        _receipt_confirmation_gaps(
            ticket, purchase_information, order_information, payment_information
        )
    )

    if (
        conversation_analysis is not None
        and conversation_analysis.contradictions
    ):
        for index, text in enumerate(conversation_analysis.contradictions, start=1):
            contradictions.append(
                Contradiction(
                    id=f"contradiction-chat-{index}",
                    field="conversation",
                    description=text,
                    evidence_ids=[conversation_analysis.evidence_id],
                    observed_values=[],
                )
            )

    return findings, contradictions, missing_information


def _observation(
    source: str, value: object, evidence_id: str | None = None
) -> FieldValueObservation:
    return FieldValueObservation(
        value="" if value is None else str(value),
        source=source,
        evidence_id=evidence_id,
    )


def _agreement_status(
    observations: list[FieldValueObservation],
    normalize: _Normalizer,
    fuzzy: bool,
) -> VerificationStatus:
    normalized = [normalize(obs.value) for obs in observations]
    if len(set(normalized)) == 1:
        return VerificationStatus.SUPPORTED
    if not fuzzy:
        return VerificationStatus.CONTRADICTED
    token_sets = [_tokens(value) for value in normalized if value is not None]
    for index, tokens in enumerate(token_sets):
        for other in token_sets[index + 1 :]:
            if not tokens or not other:
                continue
            overlap = len(tokens & other) / max(len(tokens), len(other))
            if overlap < _FUZZY_OVERLAP_THRESHOLD:
                return VerificationStatus.CONTRADICTED
    return VerificationStatus.PARTIALLY_SUPPORTED


def _agreement_rationale(
    label: str,
    observations: list[FieldValueObservation],
    status: VerificationStatus,
) -> str:
    sources = ", ".join(f"{obs.source} ({obs.value})" for obs in observations)
    if status is VerificationStatus.SUPPORTED:
        return f"All available sources agree on the {label}: {sources}."
    return (
        f"The {label} is worded differently across sources but the values "
        f"are consistent enough to be considered matching: {sources}. "
        "Wording differences are not treated as contradictions."
    )


def _contradiction_description(
    label: str, observations: list[FieldValueObservation]
) -> str:
    sources = ", ".join(
        f"{obs.source} states {obs.value!r}" for obs in observations
    )
    return (
        f"The {label} differs across sources: {sources}. This inconsistency "
        "is reported factually and does not imply wrongdoing by either party."
    )


def _receipt_confirmation_gaps(
    ticket: SupportTicket,
    purchase_information: PurchaseInformation | None,
    order_information: OrderInformation | None,
    payment_information: PaymentInformation | None,
) -> list[MissingInformation]:
    gaps: list[MissingInformation] = []
    if not ticket.order_id:
        return gaps
    receipt_confirms = purchase_information is not None and bool(
        purchase_information.order_number
    )
    order_confirms = order_information is not None and bool(
        order_information.order_id
    )
    payment_confirms = payment_information is not None and bool(
        payment_information.order_id
    )
    if receipt_confirms or order_confirms or payment_confirms:
        return gaps
    if purchase_information is not None:
        gaps.append(
            MissingInformation(
                id="missing-order-confirmation",
                description=(
                    f"The order number stated in the ticket "
                    f"({ticket.order_id!r}) could not be confirmed because "
                    "the receipt evidence does not state an order number."
                ),
                recommended_evidence=[
                    "Receipt or invoice showing the order number",
                    "Order confirmation email",
                ],
            )
        )
    else:
        gaps.append(
            MissingInformation(
                id="missing-order-confirmation",
                description=(
                    f"The order number stated in the ticket "
                    f"({ticket.order_id!r}) could not be independently "
                    "confirmed because no receipt, order-system data, or "
                    "payment-provider data was supplied."
                ),
                recommended_evidence=[
                    "Receipt or invoice showing the order number",
                    "Order confirmation email",
                    "Payment-provider transaction details",
                ],
            )
        )
    if (
        ticket.purchase_date
        and purchase_information is not None
        and purchase_information.purchase_date is None
    ):
        gaps.append(
            MissingInformation(
                id="missing-purchase-date-confirmation",
                description=(
                    "The purchase date stated in the ticket could not be "
                    "cross-checked because the receipt evidence does not "
                    "state a date."
                ),
                recommended_evidence=[
                    "Receipt or invoice showing the purchase date"
                ],
            )
        )
    return gaps
