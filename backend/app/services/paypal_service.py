"""Read-only PayPal transaction and order-information retrieval.

This module only obtains an OAuth token and issues HTTP GET requests for
one capture or one order. It never creates, captures, authorizes, voids,
refunds, transfers, releases, or pays out money. Credentials are read from
configuration, are never logged or returned, and are not stored in the
database. Responses are reduced to the transaction fields needed for
audit; payer details are not persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import logging
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, settings as backend_settings
from app.models import PayPalTransaction, Project
from app.schemas import PayPalTransactionResponse


logger = logging.getLogger("proofbridge.paypal")

_SAFE_RAW_KEYS = (
    "id",
    "status",
    "intent",
    "final_capture",
    "create_time",
    "update_time",
    "amount",
)
_MAX_AMOUNT = Decimal("10000000000")


def derive_payment_state(payload: dict) -> str:
    """Normalize a PayPal order or payment payload to one ProofBridge state.

    Adapted from Person 4's read-only normalization helper. It only inspects
    response data; it never calls PayPal or moves money.
    """
    status = str(payload.get("status", "")).upper()

    if "seller_receivable_breakdown" in payload or "final_capture" in payload:
        if status == "COMPLETED":
            return "PAID"
        if status in ("DECLINED", "FAILED"):
            return "FAILED"

    if "expiration_time" in payload and "purchase_units" not in payload:
        if status == "CREATED":
            return "HELD"
        if status == "CAPTURED":
            return "PAID"
        if status == "VOIDED":
            return "VOIDED"
        if status == "EXPIRED":
            return "EXPIRED"
        if status in ("DENIED", "FAILED"):
            return "FAILED"

    intent = str(payload.get("intent", "")).upper()
    purchase_units = payload.get("purchase_units") or [{}]
    purchase_unit = (
        purchase_units[0]
        if isinstance(purchase_units, list) and purchase_units
        else {}
    )
    payments = (
        purchase_unit.get("payments", {})
        if isinstance(purchase_unit, dict)
        else {}
    )

    captures = payments.get("captures", [])
    if captures and isinstance(captures, list):
        first_status = str(captures[0].get("status", "")).upper()
        if first_status == "COMPLETED":
            return "PAID"
        if first_status in ("DECLINED", "FAILED"):
            return "FAILED"

    authorizations = payments.get("authorizations", [])
    if authorizations and isinstance(authorizations, list):
        first_status = str(authorizations[0].get("status", "")).upper()
        if first_status == "CREATED":
            return "HELD"
        if first_status == "CAPTURED":
            return "PAID"
        if first_status == "VOIDED":
            return "VOIDED"
        if first_status == "EXPIRED":
            return "EXPIRED"
        if first_status in ("DENIED", "FAILED"):
            return "FAILED"

    if status in ("CREATED", "SAVED", "PAYER_ACTION_REQUIRED"):
        return "PENDING_APPROVAL"
    if status == "APPROVED":
        return "APPROVED"
    if status == "COMPLETED":
        return "PAID" if intent == "CAPTURE" else "HELD"
    if status == "VOIDED":
        return "VOIDED"

    return "FAILED"


class PayPalError(Exception):
    """Base class for safe, non-secret PayPal failure descriptions."""


class PayPalNotConfigured(PayPalError):
    pass


class PayPalNotFound(PayPalError):
    pass


class PayPalUpstreamError(PayPalError):
    pass


@dataclass(frozen=True)
class PayPalTransactionInfo:
    transaction_id: str
    amount: Decimal
    currency: str
    status: str
    raw_data: dict


@dataclass(frozen=True)
class PayPalOrderInfo:
    order_id: str
    amount: Decimal
    currency: str
    status: str
    intent: str | None
    payment_state: str
    authorization_id: str | None
    authorization_status: str | None
    capture_id: str | None
    case_reference: str | None
    raw_data: dict


@dataclass(frozen=True)
class PayPalSyncOutcome:
    transaction: PayPalTransactionResponse
    created: bool


class PayPalClient:
    """Minimal official-API client for one transaction lookup."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client_factory=None,
    ) -> None:
        self._settings = settings or backend_settings
        self._http_client_factory = http_client_factory or httpx.Client

    @property
    def configured(self) -> bool:
        return self._settings.paypal_configured

    @property
    def environment(self) -> str:
        return self._settings.paypal_environment

    def fetch_transaction(self, transaction_id: str) -> PayPalTransactionInfo:
        if not self.configured:
            raise PayPalNotConfigured(
                "PayPal is not configured. Set PAYPAL_CLIENT_ID and "
                "PAYPAL_CLIENT_SECRET in the environment; no credentials "
                "are stored by this application."
            )

        base = self._settings.paypal_api_base
        timeout = self._settings.PAYPAL_TIMEOUT_SECONDS

        try:
            with self._http_client_factory(timeout=timeout) as client:
                token = self._access_token(client, base)
                response = client.get(
                    f"{base}/v2/payments/captures/"
                    f"{quote(transaction_id, safe='')}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "PayPal lookup failed for one transaction: %s",
                type(exc).__name__,
            )
            raise PayPalUpstreamError(
                "PayPal could not be reached; no transaction information "
                "was stored."
            ) from exc

        if response.status_code == 404:
            raise PayPalNotFound(
                "PayPal did not return a transaction with that identifier."
            )

        if response.status_code in {401, 403}:
            logger.warning(
                "PayPal rejected the configured credentials (%s).",
                response.status_code,
            )
            raise PayPalUpstreamError(
                "PayPal rejected the configured credentials; no transaction "
                "information was stored."
            )

        if response.status_code >= 400:
            logger.warning(
                "PayPal lookup failed with upstream status %s.",
                response.status_code,
            )
            raise PayPalUpstreamError(
                "PayPal returned an error; no transaction information was "
                "stored."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise PayPalUpstreamError(
                "PayPal returned an unreadable response; no transaction "
                "information was stored."
            ) from exc

        info = _normalize_payload(payload)

        if info.transaction_id != transaction_id:
            raise PayPalUpstreamError(
                "PayPal returned information for a different transaction; "
                "nothing was stored."
            )

        return info

    def fetch_order(self, order_id: str) -> PayPalOrderInfo:
        """Read one PayPal order without initiating, capturing, or voiding it."""
        if not self.configured:
            raise PayPalNotConfigured(
                "PayPal is not configured. Set PAYPAL_CLIENT_ID and "
                "PAYPAL_CLIENT_SECRET in the environment; no credentials "
                "are stored by this application."
            )

        base = self._settings.paypal_api_base
        timeout = self._settings.PAYPAL_TIMEOUT_SECONDS

        try:
            with self._http_client_factory(timeout=timeout) as client:
                token = self._access_token(client, base)
                response = client.get(
                    f"{base}/v2/checkout/orders/"
                    f"{quote(order_id, safe='')}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "PayPal order lookup failed: %s",
                type(exc).__name__,
            )
            raise PayPalUpstreamError(
                "PayPal could not be reached; no order information was "
                "stored."
            ) from exc

        if response.status_code == 404:
            raise PayPalNotFound(
                "PayPal did not return an order with that identifier."
            )

        if response.status_code in {401, 403}:
            logger.warning(
                "PayPal rejected the configured credentials (%s).",
                response.status_code,
            )
            raise PayPalUpstreamError(
                "PayPal rejected the configured credentials; no order "
                "information was stored."
            )

        if response.status_code >= 400:
            logger.warning(
                "PayPal order lookup failed with upstream status %s.",
                response.status_code,
            )
            raise PayPalUpstreamError(
                "PayPal returned an error; no order information was stored."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise PayPalUpstreamError(
                "PayPal returned an unreadable response; no order "
                "information was stored."
            ) from exc

        return _normalize_order_payload(payload, order_id)

    def _access_token(self, client: httpx.Client, base: str) -> str:
        try:
            response = client.post(
                f"{base}/v1/oauth2/token",
                auth=(
                    self._settings.PAYPAL_CLIENT_ID,
                    self._settings.PAYPAL_CLIENT_SECRET,
                ),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "PayPal authentication request failed: %s",
                type(exc).__name__,
            )
            raise PayPalUpstreamError(
                "PayPal authentication failed; no transaction information "
                "was stored."
            ) from exc

        if response.status_code in {401, 403}:
            raise PayPalUpstreamError(
                "PayPal rejected the configured credentials; no transaction "
                "information was stored."
            )

        if response.status_code >= 400:
            raise PayPalUpstreamError(
                "PayPal authentication failed; no transaction information "
                "was stored."
            )

        try:
            token = response.json().get("access_token")
        except (ValueError, AttributeError) as exc:
            raise PayPalUpstreamError(
                "PayPal returned an unreadable authentication response; no "
                "transaction information was stored."
            ) from exc

        if not isinstance(token, str) or not token:
            raise PayPalUpstreamError(
                "PayPal did not return an access token; no transaction "
                "information was stored."
            )

        return token


def get_paypal_client_dependency() -> PayPalClient:
    """Return the shared PayPal client; tests override this dependency."""
    return PayPalClient()


def sync_project_transaction(
    db: Session,
    project: Project,
    transaction_id: str,
    client: PayPalClient | None = None,
) -> PayPalSyncOutcome:
    """Retrieve and store one transaction idempotently.

    A transaction already stored for this project is returned without a
    second external call. A transaction stored for a different project is
    rejected, so evidence cannot be silently attached to two cases.
    """
    client = client or get_paypal_client_dependency()
    normalized_id = transaction_id.strip()

    existing = _existing_transaction(db, normalized_id)

    if existing is not None:
        return _existing_outcome(existing, project)

    order_reference = _find_capture_reference(db, normalized_id)
    if order_reference is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This PayPal capture is already recorded as part of an "
                "order for a project; no duplicate was stored."
            ),
        )

    try:
        info = client.fetch_transaction(normalized_id)
    except PayPalNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except PayPalNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PayPalUpstreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    row = PayPalTransaction(
        project_id=project.id,
        paypal_transaction_id=info.transaction_id,
        amount=info.amount,
        currency=info.currency,
        status=info.status,
        raw_data=info.raw_data,
    )
    db.add(row)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _existing_transaction(db, normalized_id)

        if existing is not None:
            return _existing_outcome(existing, project)

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The PayPal transaction could not be stored for this "
                "project."
            ),
        )

    db.refresh(row)

    return PayPalSyncOutcome(
        transaction=_to_response(row),
        created=True,
    )


def sync_project_order(
    db: Session,
    project: Project,
    order_id: str,
    client: PayPalClient | None = None,
) -> PayPalSyncOutcome:
    """Retrieve and store one PayPal order's read-only information.

    The order is only read from PayPal. No capture, authorization, void,
    refund, transfer, or payout is performed. A row already stored for the
    same project is returned without another external call; a row belonging
    to another project is rejected so one payment cannot be attached to two
    cases.
    """
    client = client or get_paypal_client_dependency()
    normalized_id = order_id.strip()

    if not normalized_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid order_id must be provided.",
        )

    existing = _existing_transaction(db, normalized_id)
    if existing is not None:
        return _existing_outcome(existing, project)

    try:
        info = client.fetch_order(normalized_id)
    except PayPalNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except PayPalNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PayPalUpstreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    if info.capture_id is not None:
        capture_reference = _find_capture_reference(db, info.capture_id)
        if capture_reference is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This PayPal order's capture is already recorded as a "
                    "separate transaction; no duplicate was stored."
                ),
            )

    row = PayPalTransaction(
        project_id=project.id,
        paypal_transaction_id=info.order_id,
        amount=info.amount,
        currency=info.currency,
        status=info.status,
        raw_data=info.raw_data,
    )
    db.add(row)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _existing_transaction(db, normalized_id)

        if existing is not None:
            return _existing_outcome(existing, project)

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The PayPal order could not be stored for this project."
            ),
        )

    db.refresh(row)

    return PayPalSyncOutcome(
        transaction=_to_response(row),
        created=True,
    )


def list_project_transactions(
    db: Session, project_id: int
) -> list[PayPalTransactionResponse]:
    rows = (
        db.query(PayPalTransaction)
        .filter(PayPalTransaction.project_id == project_id)
        .order_by(PayPalTransaction.id)
        .all()
    )

    return [_to_response(row) for row in rows]


def get_project_transaction(
    db: Session, project_id: int, transaction_id: str
) -> PayPalTransactionResponse:
    row = _existing_transaction(db, transaction_id.strip())

    if row is None or row.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PayPal transaction information not found for this project.",
        )

    return _to_response(row)


def _existing_transaction(
    db: Session, transaction_id: str
) -> PayPalTransaction | None:
    return (
        db.query(PayPalTransaction)
        .filter(
            PayPalTransaction.paypal_transaction_id == transaction_id
        )
        .first()
    )


def _find_capture_reference(
    db: Session, capture_id: str
) -> PayPalTransaction | None:
    """Find a row that already represents this capture.

    Checks both capture rows (whose primary identifier is the capture ID)
    and order rows that record the capture ID inside their sanitized
    ``raw_data``. This prevents the same payment being stored twice when an
    order and its capture are synced separately.
    """
    rows = db.query(PayPalTransaction).all()

    for row in rows:
        if row.paypal_transaction_id == capture_id:
            return row

        raw_data = row.raw_data or {}
        if raw_data.get("capture_id") == capture_id:
            return row

    return None


def _existing_outcome(
    row: PayPalTransaction, project: Project
) -> PayPalSyncOutcome:
    if row.project_id != project.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This PayPal transaction is already associated with "
                "another project."
            ),
        )

    return PayPalSyncOutcome(
        transaction=_to_response(row),
        created=False,
    )


def _normalize_payload(payload) -> PayPalTransactionInfo:
    if not isinstance(payload, dict):
        raise PayPalUpstreamError(
            "PayPal returned an unexpected response; no transaction "
            "information was stored."
        )

    transaction_id = payload.get("id")
    status_value = payload.get("status")
    amount_block = payload.get("amount")

    if (
        not isinstance(transaction_id, str)
        or not transaction_id.strip()
        or not isinstance(status_value, str)
        or not status_value.strip()
        or not isinstance(amount_block, dict)
    ):
        raise PayPalUpstreamError(
            "PayPal returned incomplete transaction information; nothing "
            "was stored."
        )

    raw_value = amount_block.get("value")
    currency = amount_block.get("currency_code")

    try:
        amount = Decimal(str(raw_value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PayPalUpstreamError(
            "PayPal returned an invalid transaction amount; nothing was "
            "stored."
        ) from exc

    if (
        not amount.is_finite()
        or amount < 0
        or amount >= _MAX_AMOUNT
        or not isinstance(currency, str)
        or len(currency.strip()) != 3
    ):
        raise PayPalUpstreamError(
            "PayPal returned an invalid transaction amount or currency; "
            "nothing was stored."
        )

    raw_data = {
        key: payload[key]
        for key in _SAFE_RAW_KEYS
        if key in payload
    }

    return PayPalTransactionInfo(
        transaction_id=transaction_id.strip(),
        amount=amount,
        currency=currency.strip().upper(),
        status=status_value.strip(),
        raw_data=raw_data,
    )


def _normalize_order_payload(
    payload, expected_order_id: str
) -> PayPalOrderInfo:
    if not isinstance(payload, dict):
        raise PayPalUpstreamError(
            "PayPal returned an unexpected response; no order information "
            "was stored."
        )

    order_id = payload.get("id")
    status_value = payload.get("status")

    if (
        not isinstance(order_id, str)
        or not order_id.strip()
        or not isinstance(status_value, str)
        or not status_value.strip()
    ):
        raise PayPalUpstreamError(
            "PayPal returned incomplete order information; nothing was "
            "stored."
        )

    if order_id.strip() != expected_order_id:
        raise PayPalUpstreamError(
            "PayPal returned information for a different order; nothing "
            "was stored."
        )

    purchase_units = payload.get("purchase_units")

    if (
        not isinstance(purchase_units, list)
        or not purchase_units
        or not isinstance(purchase_units[0], dict)
    ):
        raise PayPalUpstreamError(
            "PayPal returned incomplete order information; nothing was "
            "stored."
        )

    purchase_unit = purchase_units[0]
    amount_block = purchase_unit.get("amount")

    if not isinstance(amount_block, dict):
        raise PayPalUpstreamError(
            "PayPal returned incomplete order information; nothing was "
            "stored."
        )

    raw_value = amount_block.get("value")
    currency = amount_block.get("currency_code")

    try:
        amount = Decimal(str(raw_value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PayPalUpstreamError(
            "PayPal returned an invalid order amount; nothing was stored."
        ) from exc

    if (
        not amount.is_finite()
        or amount < 0
        or amount >= _MAX_AMOUNT
        or not isinstance(currency, str)
        or len(currency.strip()) != 3
    ):
        raise PayPalUpstreamError(
            "PayPal returned an invalid order amount or currency; nothing "
            "was stored."
        )

    intent_value = payload.get("intent")
    intent = (
        intent_value.strip()
        if isinstance(intent_value, str) and intent_value.strip()
        else None
    )

    payments = purchase_unit.get("payments")
    payments = payments if isinstance(payments, dict) else {}

    authorizations = payments.get("authorizations")
    authorizations = (
        authorizations if isinstance(authorizations, list) else []
    )
    first_authorization = (
        authorizations[0]
        if authorizations and isinstance(authorizations[0], dict)
        else {}
    )

    captures = payments.get("captures")
    captures = captures if isinstance(captures, list) else []
    first_capture = (
        captures[0]
        if captures and isinstance(captures[0], dict)
        else {}
    )

    authorization_id = first_authorization.get("id")
    authorization_id = (
        authorization_id
        if isinstance(authorization_id, str) and authorization_id
        else None
    )

    authorization_status = first_authorization.get("status")
    authorization_status = (
        authorization_status
        if isinstance(authorization_status, str) and authorization_status
        else None
    )

    capture_id = first_capture.get("id")
    capture_id = (
        capture_id if isinstance(capture_id, str) and capture_id else None
    )

    reference = purchase_unit.get("reference_id")
    case_reference = (
        reference.strip()
        if isinstance(reference, str) and reference.strip()
        else None
    )

    payment_state = derive_payment_state(payload)

    raw_data = {
        "id": order_id.strip(),
        "status": status_value.strip(),
        "payment_state": payment_state,
    }

    if intent is not None:
        raw_data["intent"] = intent
    if authorization_id is not None:
        raw_data["authorization_id"] = authorization_id
    if authorization_status is not None:
        raw_data["authorization_status"] = authorization_status
    if capture_id is not None:
        raw_data["capture_id"] = capture_id
    if case_reference is not None:
        raw_data["reference_id"] = case_reference

    for key in ("create_time", "update_time"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            raw_data[key] = value

    return PayPalOrderInfo(
        order_id=order_id.strip(),
        amount=amount,
        currency=currency.strip().upper(),
        status=status_value.strip(),
        intent=intent,
        payment_state=payment_state,
        authorization_id=authorization_id,
        authorization_status=authorization_status,
        capture_id=capture_id,
        case_reference=case_reference,
        raw_data=raw_data,
    )


def _capture_payment_state(raw_data: dict) -> str | None:
    status = str(raw_data.get("status", "")).upper()

    if status == "COMPLETED":
        return "PAID"
    if status in ("DECLINED", "FAILED"):
        return "FAILED"

    return None


def _to_response(row: PayPalTransaction) -> PayPalTransactionResponse:
    raw_data = row.raw_data or {}

    if "payment_state" in raw_data:
        information_type = "order"
    elif "final_capture" in raw_data:
        information_type = "capture"
    else:
        information_type = None

    payment_state = raw_data.get("payment_state")

    if payment_state is None and information_type == "capture":
        payment_state = _capture_payment_state(raw_data)

    capture_id = raw_data.get("capture_id")

    if capture_id is None and information_type == "capture":
        capture_id = row.paypal_transaction_id

    return PayPalTransactionResponse(
        id=row.id,
        project_id=row.project_id,
        paypal_transaction_id=row.paypal_transaction_id,
        amount=float(row.amount),
        currency=row.currency,
        status=row.status,
        raw_data=row.raw_data,
        created_at=row.created_at,
        information_type=information_type,
        intent=raw_data.get("intent"),
        payment_state=payment_state,
        authorization_id=raw_data.get("authorization_id"),
        authorization_status=raw_data.get("authorization_status"),
        capture_id=capture_id,
        case_reference=raw_data.get("reference_id"),
    )
