"""Storage domain demo adapter: resolves logical storage locations to facility paths."""
from fastapi import HTTPException

from app.routers.status import models as status_models
from app.routers.storage import facility_adapter, models as storage_models
from app.types.user import User

from ..common import DemoAuthMixin
from ..state import STATE


class StorageDemoAdapter(DemoAuthMixin, facility_adapter.FacilityAdapter):
    """Demo implementation of the storage domain. Reads from the shared DemoState."""

    @staticmethod
    def _slugify_project(name: str) -> str:
        """Convert a project name to a path-safe slug (real facilities use codes like 'm1234')."""
        return name.lower().replace(" ", "_")

    def _user_project_codes(self, user: User) -> list[str]:
        """Return the path-slug codes of all projects the user belongs to."""
        return [self._slugify_project(p.name) for p in STATE.projects if user.id in p.user_ids]

    def _user_member_of(self, user: User, project_code: str) -> bool:
        """Authorization check: is the user a member of the named project?"""
        return any(
            user.id in p.user_ids and self._slugify_project(p.name) == project_code
            for p in STATE.projects
        )

    def _resolve_path(self, template: str, user: User, project: str | None) -> str:
        first = user.id[0] if user.id else "u"
        path = template.replace("{user}", user.id).replace("{first}", first)
        if project:
            path = path.replace("{project}", project)
        return path

    def _apply_intent_filter(
        self,
        instance: storage_models.StorageInstance,
        intent: storage_models.StorageIntent | None,
    ) -> bool:
        """Return False if this storage instance should be excluded for the given intent."""
        if intent == storage_models.StorageIntent.long_term_storage:
            return instance.logical_name == storage_models.LogicalName.archive
        if intent == storage_models.StorageIntent.staging:
            return instance.logical_name != storage_models.LogicalName.archive
        if intent == storage_models.StorageIntent.write:
            return instance.access.write
        return True

    async def get_locations(
        self: "StorageDemoAdapter",
        resource: status_models.Resource,
        user: User,
        logicalpath: storage_models.LogicalName | None,
        project: str | None,
        allocation: str | None,
        intent: storage_models.StorageIntent | None,
    ) -> list[storage_models.StorageInstance]:
        templates = STATE.locations.get(resource.id, [])
        effective_project = project or allocation

        # Authorization: a user can only resolve paths for their own projects
        if effective_project and not self._user_member_of(user, effective_project):
            raise HTTPException(status_code=403, detail=f"User is not a member of project '{effective_project}'")

        # Expand project-scoped paths across ALL of the user's projects when none specified
        project_codes = [effective_project] if effective_project else self._user_project_codes(user)

        result = []
        for m in templates:
            if logicalpath and m.logical_name != logicalpath:
                continue
            if not self._apply_intent_filter(m, intent):
                continue

            is_project_scoped = "{project}" in m.path
            expand_over = project_codes if is_project_scoped else [None]

            for code in expand_over:
                result.append(storage_models.StorageInstance(
                    logical_name=m.logical_name,
                    path=self._resolve_path(m.path, user, code),
                    filesystem=m.filesystem,
                    performance_tier=m.performance_tier,
                    quota_bytes=m.quota_bytes,
                    available_bytes=m.available_bytes,
                    purge_policy_days=m.purge_policy_days,
                    shared=m.shared,
                    access=m.access,
                ))
        return result
