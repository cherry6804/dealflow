"""Contact API routes for DealFlow."""

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.contacts.schemas import (
    ContactCreateRequest,
    ContactListQuery,
    ContactListResponse,
    ContactResponse,
)
from app.contacts.service import create_contact, get_contact, list_contacts
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext

router = APIRouter(
    prefix="/api/v1/contacts",
    tags=["contacts"],
)


@router.post(
    "",
    response_model=ContactResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_contact_endpoint(
    payload: ContactCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("contacts.create"),
    ),
    db: Session = Depends(get_db_session),
) -> ContactResponse:
    """Create a Contact within the verified tenant."""
    contact = create_contact(
        db=db,
        organization_id=tenant_context.organization_id,
        payload=payload,
    )
    db.commit()
    db.refresh(contact)
    return ContactResponse.model_validate(contact)


@router.get(
    "",
    response_model=ContactListResponse,
    status_code=status.HTTP_200_OK,
)
def list_contacts_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1, max_length=320),
    is_active: bool | None = Query(default=None),
    tenant_context: TenantContext = Depends(
        require_permission("contacts.read"),
    ),
    db: Session = Depends(get_db_session),
) -> ContactListResponse:
    """List and search Contacts within the verified tenant."""
    query = ContactListQuery(
        page=page,
        page_size=page_size,
        search=search,
        is_active=is_active,
    )

    contacts, total = list_contacts(
        db=db,
        organization_id=tenant_context.organization_id,
        query=query,
    )

    total_pages = ceil(total / page_size) if total else 0

    return ContactListResponse(
        items=[
            ContactResponse.model_validate(contact)
            for contact in contacts
        ],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


@router.get(
    "/{contact_id}",
    response_model=ContactResponse,
    status_code=status.HTTP_200_OK,
)
def get_contact_endpoint(
    contact_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("contacts.read"),
    ),
    db: Session = Depends(get_db_session),
) -> ContactResponse:
    """Retrieve a Contact within the verified tenant."""
    contact = get_contact(
        db=db,
        organization_id=tenant_context.organization_id,
        contact_id=contact_id,
    )
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found.",
        )
    return ContactResponse.model_validate(contact)