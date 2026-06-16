"""Account domain demo adapter: capabilities, projects, allocations."""
from app.routers.account import facility_adapter, models as account_models
from app.types.models import Capability
from app.types.user import User

from ..common import DemoAuthMixin
from ..state import STATE


class AccountDemoAdapter(DemoAuthMixin, facility_adapter.FacilityAdapter):
    """Demo implementation of the account domain. Reads from the shared DemoState."""

    async def get_capabilities(
        self: "AccountDemoAdapter",
        name: str | None = None,
        modified_since: str | None = None,
        offset: int = 0,
        limit: int = 1000,
    ) -> list[Capability]:
        return STATE.capabilities.values()

    async def get_projects(self: "AccountDemoAdapter", user: User) -> list[account_models.Project]:
        return STATE.projects

    async def get_project_allocations(
        self: "AccountDemoAdapter",
        project: account_models.Project,
        user: User,
    ) -> list[account_models.ProjectAllocation]:
        return [pa for pa in STATE.project_allocations if pa.project_id == project.id]

    async def get_user_allocations(
        self: "AccountDemoAdapter",
        user: User,
        project_allocation: account_models.ProjectAllocation,
    ) -> list[account_models.UserAllocation]:
        return [ua for ua in STATE.user_allocations if ua.project_allocation_id == project_allocation.id]
