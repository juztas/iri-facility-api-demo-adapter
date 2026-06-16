"""Shared helpers and the authentication mixin used by every per-domain demo adapter."""
import datetime
import uuid

from fastapi import HTTPException

from app.types.user import User

DEMO_USER = User(id="gtorok", name="Gabor Torok", api_key="12345", client_ip="1.2.3.4")


def demo_uuid(kind: str, name: str) -> str:
    """Generate a deterministic UUID based on the kind and name."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"demo:{kind}:{name}"))


def utc_now() -> datetime.datetime:
    """Return current UTC datetime timestamp"""
    return datetime.datetime.now(datetime.timezone.utc)


def utc_timestamp() -> int:
    """Return current UTC datetime timestamp as integer"""
    return int(utc_now().timestamp())


def paginate_list(items, offset: int | None, limit: int | None):
    """Return a sliced items using offset and limit."""
    if offset is not None and offset > 0:
        items = items[offset:]
    if limit is not None and limit >= 0:
        items = items[:limit]
    return items


class DemoAuthMixin:
    """Demo authentication, mixed into every per-domain demo adapter.

    Every FacilityAdapter ABC extends AuthenticatedAdapter (see
    app.routers.iri_router.AuthenticatedAdapter), so each independently
    configured domain adapter must implement these three methods itself.
    All seven demo adapters resolve to the same fake user via DEMO_USER.
    """

    async def get_current_user(self: "DemoAuthMixin", api_key: str, client_ip: str | None) -> str:
        if api_key != DEMO_USER.api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return DEMO_USER.id

    async def get_current_user_globus(
        self: "DemoAuthMixin",
        api_key: str,
        client_ip: str | None,
        globus_introspect: dict | None,
    ) -> str:
        return DEMO_USER.id

    async def get_user(
        self: "DemoAuthMixin",
        user_id: str,
        api_key: str,
        client_ip: str | None,
        globus_introspect: dict | None,
    ) -> User:
        if user_id != DEMO_USER.id:
            raise HTTPException(status_code=403, detail="User not found")
        return DEMO_USER
