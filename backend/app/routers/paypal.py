"""Project-scoped read-only PayPal transaction-information endpoints.

The only outbound PayPal operations are authorized capture and order
lookups. There is deliberately no endpoint that creates, captures,
authorizes, voids, refunds, transfers, releases, or pays out money.
"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import (
    PayPalOrderSyncRequest,
    PayPalStatusResponse,
    PayPalSyncRequest,
    PayPalSyncResponse,
    PayPalTransactionResponse,
)
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    require_role,
)
from app.services.paypal_service import (
    PayPalClient,
    get_paypal_client_dependency,
    get_project_transaction,
    list_project_transactions,
    sync_project_order,
    sync_project_transaction,
)
from app.services.project_service import (
    ensure_project_access,
    ensure_project_owner,
    get_project_or_404,
)


router = APIRouter(
    prefix="/projects/{project_id}/paypal",
    tags=["PayPal"],
)

project_reader = require_role(
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
)

client_only = require_role(ROLE_CLIENT)


@router.get(
    "/status",
    response_model=PayPalStatusResponse,
    summary="Get read-only PayPal configuration status",
)
def get_paypal_status(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader),
    paypal: PayPalClient = Depends(get_paypal_client_dependency),
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return PayPalStatusResponse(
        configured=paypal.configured,
        environment=paypal.environment,
    )


@router.post(
    "/transactions/sync",
    response_model=PayPalSyncResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Retrieve and store PayPal transaction information",
)
def sync_paypal_transaction(
    project_id: int,
    payload: PayPalSyncRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(client_only),
    paypal: PayPalClient = Depends(get_paypal_client_dependency),
):
    """Retrieve one transaction from PayPal and store its information.

    Returns **201** when the transaction is stored for the first time and
    **200** when this project already has it. ProofBridge does not move
    money through PayPal.
    """
    project = get_project_or_404(db, project_id)
    ensure_project_owner(project, current_user)

    outcome = sync_project_transaction(
        db,
        project,
        payload.transaction_id,
        client=paypal,
    )

    if not outcome.created:
        response.status_code = status.HTTP_200_OK

    return PayPalSyncResponse(
        transaction=outcome.transaction,
        created=outcome.created,
    )


@router.post(
    "/orders/sync",
    response_model=PayPalSyncResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Retrieve and store read-only PayPal order information",
)
def sync_paypal_order(
    project_id: int,
    payload: PayPalOrderSyncRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(client_only),
    paypal: PayPalClient = Depends(get_paypal_client_dependency),
):
    """Read one PayPal order and store its information for this project.

    This endpoint only performs a PayPal order lookup. It never creates,
    captures, authorizes, voids, refunds, transfers, or pays out money.
    Returns **201** when the order is stored for the first time and **200**
    when this project already has it.
    """
    project = get_project_or_404(db, project_id)
    ensure_project_owner(project, current_user)

    outcome = sync_project_order(
        db,
        project,
        payload.order_id,
        client=paypal,
    )

    if not outcome.created:
        response.status_code = status.HTTP_200_OK

    return PayPalSyncResponse(
        transaction=outcome.transaction,
        created=outcome.created,
    )


@router.get(
    "/transactions",
    response_model=list[PayPalTransactionResponse],
    summary="List stored PayPal transaction information",
)
def list_paypal_transactions(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader),
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return list_project_transactions(db, project.id)


@router.get(
    "/transactions/{transaction_id}",
    response_model=PayPalTransactionResponse,
    summary="Get one stored PayPal transaction",
)
def get_paypal_transaction(
    project_id: int,
    transaction_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader),
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return get_project_transaction(db, project.id, transaction_id)
