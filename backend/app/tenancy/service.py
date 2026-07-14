"""Lógica de dominio de multi-tenancy: orgs, membresías y control de roles.

Todo async sobre AsyncSession. Los routers convierten PermissionError en HTTP 403.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenancy.models import Membership, Organization

# Roles de gestión: pueden administrar membresías de la organización.
MANAGE_ROLES: tuple[str, ...] = ("owner", "admin")


async def create_org(db: AsyncSession, *, name: str, owner_user_id: uuid.UUID) -> Organization:
    """Crea una organización y registra al creador como owner."""
    org = Organization(name=name)
    db.add(org)
    await db.flush()  # asegura org.id antes de crear la membresía
    db.add(Membership(org_id=org.id, user_id=owner_user_id, role="owner"))
    await db.commit()
    await db.refresh(org)
    return org


async def list_orgs_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[Organization]:
    """Organizaciones de las que el usuario es miembro."""
    result = await db.scalars(
        select(Organization)
        .join(Membership, Membership.org_id == Organization.id)
        .where(Membership.user_id == user_id)
        .order_by(Organization.created_at.desc())
    )
    return list(result)


async def get_membership(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> Membership | None:
    """Membresía del usuario en la org, o None si no pertenece."""
    return await db.scalar(
        select(Membership).where(
            Membership.org_id == org_id, Membership.user_id == user_id
        )
    )


def require_role(membership: Membership | None, *allowed: str) -> None:
    """Lanza PermissionError si la membresía no existe o su rol no está permitido."""
    if membership is None or membership.role not in allowed:
        raise PermissionError("Rol insuficiente para esta operación")


async def add_member(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID, role: str = "member"
) -> Membership:
    """Añade (o actualiza el rol de) un miembro en la organización."""
    existing = await get_membership(db, org_id, user_id)
    if existing is not None:
        existing.role = role
        await db.commit()
        await db.refresh(existing)
        return existing
    membership = Membership(org_id=org_id, user_id=user_id, role=role)
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return membership


async def remove_member(db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Elimina la membresía del usuario en la organización (si existe)."""
    membership = await get_membership(db, org_id, user_id)
    if membership is not None:
        await db.delete(membership)
        await db.commit()
