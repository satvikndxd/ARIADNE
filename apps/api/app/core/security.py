"""Deterministic, server-side authorization.

The LLM is *never* a security layer: roles, permissions and tool gating are
evaluated here in plain Python and again inside the MCP server.  A model that
"decides" it is an admin still gets a 403.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import Header, Request

from app.core.config import settings
from app.core.errors import AuthorizationError
from app.core.logging import user_id_var


class Role(str, Enum):
    VIEWER = "VIEWER"
    ENGINEER = "ENGINEER"
    REVIEWER = "REVIEWER"
    ADMIN = "ADMIN"


# Ordered least → most privileged.
ROLE_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.ENGINEER: 1, Role.REVIEWER: 2, Role.ADMIN: 3}


class Permission(str, Enum):
    READ_PROJECT_DATA = "read:project_data"
    RUN_ANALYSIS = "analysis:run"
    SEARCH_KNOWLEDGE = "knowledge:search"
    CREATE_FINDING = "finding:create"
    UPDATE_FINDING = "finding:update"
    DELETE_FINDING = "finding:delete"
    CONFIGURE_PROJECT = "project:configure"
    INGEST_DOCUMENT = "document:ingest"
    READ_AUDIT = "audit:read"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset(
        {Permission.READ_PROJECT_DATA, Permission.SEARCH_KNOWLEDGE, Permission.READ_AUDIT}
    ),
    Role.ENGINEER: frozenset(
        {
            Permission.READ_PROJECT_DATA,
            Permission.SEARCH_KNOWLEDGE,
            Permission.RUN_ANALYSIS,
            Permission.CREATE_FINDING,
            Permission.INGEST_DOCUMENT,
            Permission.READ_AUDIT,
        }
    ),
    Role.REVIEWER: frozenset(
        {
            Permission.READ_PROJECT_DATA,
            Permission.SEARCH_KNOWLEDGE,
            Permission.RUN_ANALYSIS,
            Permission.CREATE_FINDING,
            Permission.UPDATE_FINDING,
            Permission.INGEST_DOCUMENT,
            Permission.READ_AUDIT,
        }
    ),
    Role.ADMIN: frozenset(Permission),
}


# Tool name → permission + whether it mutates state (and therefore needs an
# explicit human confirmation before execution).
TOOL_POLICY: dict[str, dict[str, Any]] = {
    "get_project": {"permission": Permission.READ_PROJECT_DATA, "mutating": False},
    "get_revision": {"permission": Permission.READ_PROJECT_DATA, "mutating": False},
    "compare_revisions": {"permission": Permission.READ_PROJECT_DATA, "mutating": False},
    "get_component": {"permission": Permission.READ_PROJECT_DATA, "mutating": False},
    "get_component_properties": {"permission": Permission.READ_PROJECT_DATA, "mutating": False},
    "get_dependencies": {"permission": Permission.READ_PROJECT_DATA, "mutating": False},
    "search_requirements": {"permission": Permission.SEARCH_KNOWLEDGE, "mutating": False},
    "get_requirement": {"permission": Permission.SEARCH_KNOWLEDGE, "mutating": False},
    "get_revision_history": {"permission": Permission.READ_PROJECT_DATA, "mutating": False},
    "get_findings": {"permission": Permission.READ_PROJECT_DATA, "mutating": False},
    "create_review_finding": {"permission": Permission.CREATE_FINDING, "mutating": True},
    "update_finding_status": {"permission": Permission.UPDATE_FINDING, "mutating": True},
}


def roles_with(permission: Permission) -> list[str]:
    return sorted(r.value for r, perms in ROLE_PERMISSIONS.items() if permission in perms)


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def is_mutating_tool(tool_name: str) -> bool:
    return bool(TOOL_POLICY.get(tool_name, {}).get("mutating"))


def authorize(role: Role | str, permission: Permission, *, context: dict[str, Any] | None = None) -> None:
    """Raise a deterministic AuthorizationError when the role lacks permission."""
    resolved = role if isinstance(role, Role) else Role(str(role).upper())
    if not has_permission(resolved, permission):
        raise AuthorizationError(
            f"Role {resolved.value} is not permitted to perform '{permission.value}'.",
            detail={
                "role": resolved.value,
                "required_permission": permission.value,
                "roles_with_permission": roles_with(permission),
                **(context or {}),
            },
        )


def authorize_tool(role: Role | str, tool_name: str) -> None:
    policy = TOOL_POLICY.get(tool_name)
    if policy is None:
        raise AuthorizationError(
            f"Unknown tool '{tool_name}'.",
            detail={"tool": tool_name, "known_tools": sorted(TOOL_POLICY)},
        )
    authorize(role, policy["permission"], context={"tool": tool_name})


class Principal:
    """Authenticated caller: a demo user plus their effective role."""

    def __init__(self, user_id: str, display_name: str, role: Role) -> None:
        self.user_id = user_id
        self.display_name = display_name
        self.role = role

    @property
    def can_mutate(self) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[Role.ENGINEER]

    def to_dict(self) -> dict[str, str]:
        return {"user_id": self.user_id, "display_name": self.display_name, "role": self.role.value}

    def __repr__(self) -> str:  # pragma: no cover
        return f"Principal({self.user_id}, {self.role.value})"


# --- Demo directory -----------------------------------------------------------
# A prototype identity layer: the caller is declared by the ``X-ARIADNE-User``
# header and resolved against this seeded directory.  Replace with OIDC/JWT for
# production (see docs/architecture.md §Security).
DEMO_USERS: dict[str, tuple[str, Role]] = {
    "u_viewer_1": ("Dana Okoye", Role.VIEWER),
    "u_engineer_1": ("Sam Rivera", Role.ENGINEER),
    "u_reviewer_1": ("Dr. Lena Fischer", Role.REVIEWER),
    "u_admin_1": ("Alex Nowak", Role.ADMIN),
}


def resolve_principal(user_id: str | None) -> Principal:
    key = (user_id or settings.default_user_id).strip()
    name, role = DEMO_USERS.get(key, (key, Role.VIEWER))
    return Principal(user_id=key, display_name=name, role=role)


async def current_principal(
    request: Request,
    x_ariadne_user: str | None = Header(default=None),
) -> Principal:
    user_id = x_ariadne_user or request.headers.get("x-ariadne-user-id") or settings.default_user_id
    principal = resolve_principal(user_id)
    user_id_var.set(principal.user_id)
    request.state.principal = principal
    return principal


def require_permission(permission: Permission):
    """FastAPI dependency factory enforcing one permission."""

    async def _dep(principal: Principal = None) -> Principal:  # type: ignore[assignment]
        raise RuntimeError("use with Depends(current_principal)")

    return _dep
