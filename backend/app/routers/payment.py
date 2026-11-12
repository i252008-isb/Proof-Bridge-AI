import logging
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PayPalTransaction, Project, User
from app.schemas import (
    PaymentCaptureRequest,
    PaymentCaptureResponse,
    PaymentCreateResponse,
    PaymentDetailResponse,
)
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    require_role,
)
from app.services.project_service import (
    ensure_project_access,
    ensure_project_owner,
    get_project_or_404,
)
from paypal_module.paypal_module.payments import (
    capture_payment,
    create_payment,
    get_payment_details,
)


logger = logging.getLogger("proofbridge.payment")

router = APIRouter(
    prefix="/projects/{project_id}/payment",
    tags=["Payment"],
)

client_only = require_role(ROLE_CLIENT)
project_reader = require_role(
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
)


def _get_paid_transaction(db: Session, project_id: int) -> Optional[PayPalTransaction]:
    return (
        db.query(PayPalTransaction)
        .filter(
            PayPalTransaction.project_id == project_id,
            PayPalTransaction.status.in_(["PAID", "COMPLETED"]),
        )
        .first()
    )


@router.post(
    "/create",
    response_model=PaymentCreateResponse,
    status_code=status.HTTP_200_OK,
    summary="Create PayPal order for project",
)
def create_project_payment(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(client_only),
):
    project = get_project_or_404(db, project_id)
    ensure_project_owner(project, current_user)

    if not project.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project has no payment amount specified.",
        )

    paid_tx = _get_paid_transaction(db, project.id)
    if paid_tx:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order is already paid.",
        )

    try:
        result = create_payment(
            amount=project.amount,
            currency=project.currency or "USD",
            case_id=str(project.id),
            mode="capture",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("PayPal order creation failed upstream for project %s", project.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PayPal upstream error: {exc}",
        ) from exc

    order_id = result.get("order_id")
    if not order_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal did not return an order ID.",
        )

    project.paypal_order_id = order_id
    db.commit()
    db.refresh(project)

    return PaymentCreateResponse(
        order_id=order_id,
        approval_link=result.get("approval_link"),
        payment_state=result.get("payment_state") or "PENDING_APPROVAL",
    )


@router.post(
    "/capture",
    response_model=PaymentCaptureResponse,
    status_code=status.HTTP_200_OK,
    summary="Capture PayPal payment for project",
)
def capture_project_payment(
    project_id: int,
    payload: Optional[PaymentCaptureRequest] = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(client_only),
):
    project = get_project_or_404(db, project_id)
    ensure_project_owner(project, current_user)

    if not project.paypal_order_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No PayPal order has been created for this project.",
        )

    if payload and payload.token and payload.token != project.paypal_order_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provided token does not match the project's PayPal order.",
        )

    # Idempotent check: if already recorded as paid
    existing_tx = _get_paid_transaction(db, project.id)
    if existing_tx:
        return PaymentCaptureResponse(
            order_id=project.paypal_order_id,
            capture_id=existing_tx.paypal_transaction_id,
            status="PAID",
            payment_state="PAID",
            amount=project.amount,
            currency=project.currency or "USD",
        )

    try:
        result = capture_payment(project.paypal_order_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("PayPal capture failed upstream for project %s", project.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PayPal upstream error: {exc}",
        ) from exc

    captured_amount = result.get("amount")
    captured_currency = result.get("currency")
    reference_id = result.get("case_id")

    if captured_amount is not None:
        try:
            if Decimal(str(captured_amount)) != Decimal(str(project.amount)):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Captured amount does not match project amount.",
                )
        except (ValueError, TypeError):
            pass

    if captured_currency is not None:
        if captured_currency.upper() != (project.currency or "USD").upper():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Captured currency does not match project currency.",
            )

    if reference_id is not None and str(reference_id) != str(project.id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Captured payment reference does not match project.",
        )

    capture_id = result.get("capture_id") or project.paypal_order_id

    # Sanitize raw_data: store transaction fields only, never personal payer details
    sanitized_raw = {
        "order_id": project.paypal_order_id,
        "capture_id": capture_id,
        "status": result.get("status") or "COMPLETED",
        "payment_state": "PAID",
        "amount": project.amount,
        "currency": project.currency or "USD",
    }

    # Upsert PayPalTransaction
    tx = (
        db.query(PayPalTransaction)
        .filter(PayPalTransaction.project_id == project.id)
        .first()
    )
    if tx:
        tx.paypal_transaction_id = capture_id
        tx.amount = Decimal(str(project.amount)) if project.amount else Decimal("0.00")
        tx.currency = project.currency or "USD"
        tx.status = "PAID"
        tx.raw_data = sanitized_raw
    else:
        tx = PayPalTransaction(
            project_id=project.id,
            paypal_transaction_id=capture_id,
            amount=Decimal(str(project.amount)) if project.amount else Decimal("0.00"),
            currency=project.currency or "USD",
            status="PAID",
            raw_data=sanitized_raw,
        )
        db.add(tx)

    db.commit()
    db.refresh(tx)

    return PaymentCaptureResponse(
        order_id=project.paypal_order_id,
        capture_id=capture_id,
        status="PAID",
        payment_state="PAID",
        amount=project.amount,
        currency=project.currency or "USD",
    )


@router.get(
    "",
    response_model=PaymentDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get payment details for project",
)
def get_project_payment(
    project_id: int,
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader),
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    tx = (
        db.query(PayPalTransaction)
        .filter(PayPalTransaction.project_id == project.id)
        .first()
    )

    if tx and tx.status in ("PAID", "COMPLETED"):
        return PaymentDetailResponse(
            payment_state="PAID",
            amount=project.amount,
            currency=project.currency or "USD",
            order_id=project.paypal_order_id,
            capture_id=tx.paypal_transaction_id,
        )

    if refresh and project.paypal_order_id:
        try:
            details = get_payment_details(project.paypal_order_id)
            state = details.get("payment_state") or "PENDING_APPROVAL"
            cap_id = details.get("capture_id")
            if state == "PAID" and cap_id:
                # Synchronize if paid on refresh
                sanitized_raw = {
                    "order_id": project.paypal_order_id,
                    "capture_id": cap_id,
                    "status": "COMPLETED",
                    "payment_state": "PAID",
                    "amount": project.amount,
                    "currency": project.currency or "USD",
                }
                if tx:
                    tx.paypal_transaction_id = cap_id
                    tx.status = "PAID"
                    tx.raw_data = sanitized_raw
                else:
                    tx = PayPalTransaction(
                        project_id=project.id,
                        paypal_transaction_id=cap_id,
                        amount=Decimal(str(project.amount)) if project.amount else Decimal("0.00"),
                        currency=project.currency or "USD",
                        status="PAID",
                        raw_data=sanitized_raw,
                    )
                    db.add(tx)
                db.commit()

            return PaymentDetailResponse(
                payment_state=state,
                amount=project.amount,
                currency=project.currency or "USD",
                order_id=project.paypal_order_id,
                capture_id=cap_id,
            )
        except Exception as exc:
            logger.warning("Could not refresh payment details for project %s: %s", project.id, exc)

    if project.paypal_order_id:
        payment_state = "PENDING_APPROVAL"
    else:
        payment_state = "UNPAID"

    return PaymentDetailResponse(
        payment_state=payment_state,
        amount=project.amount,
        currency=project.currency or "USD",
        order_id=project.paypal_order_id,
        capture_id=None,
    )
