"""Status domain demo adapter: resources, events, incidents."""
import datetime

from app.routers.status import facility_adapter, models as status_models
from app.types.models import Capability

from ..common import DemoAuthMixin, paginate_list
from ..state import STATE


class StatusDemoAdapter(DemoAuthMixin, facility_adapter.FacilityAdapter):
    """Demo implementation of the status domain. Reads from the shared DemoState."""

    async def get_resources(
        self: "StatusDemoAdapter",
        offset: int,
        limit: int,
        name: str | None = None,
        description: str | None = None,
        group: str | None = None,
        modified_since: datetime.datetime | None = None,
        resource_type: status_models.ResourceType | None = None,
        current_status: status_models.Status | None = None,
        capability: Capability | None = None,
        site_id: str | None = None,
    ) -> list[status_models.Resource]:
        resources = status_models.Resource.find(
            STATE.resources,
            name=name,
            description=description,
            group=group,
            modified_since=modified_since,
            resource_type=resource_type,
            current_status=current_status,
            capability=capability,
            site_id=site_id,
        )
        return paginate_list(resources, offset, limit)

    async def get_resource(self: "StatusDemoAdapter", id_: str) -> status_models.Resource:
        return status_models.Resource.find_by_id(STATE.resources, id_)

    async def get_resources_for_endpoint(self: "StatusDemoAdapter", endpoint: status_models.Endpoint) -> list[status_models.Resource]:
        return [r for r in STATE.resources if endpoint in r.supported_endpoints]

    async def get_events(
        self: "StatusDemoAdapter",
        offset: int,
        limit: int,
        incident_id: str | None = None,
        resource_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
        status: status_models.Status | None = None,
        from_: datetime.datetime | None = None,
        to: datetime.datetime | None = None,
        time_: datetime.datetime | None = None,
        modified_since: datetime.datetime | None = None,
    ) -> list[status_models.Event]:
        events = status_models.Event.find(
            STATE.events,
            incident_id=incident_id,
            resource_id=resource_id,
            name=name,
            description=description,
            status=status,
            from_=from_,
            to=to,
            time_=time_,
            modified_since=modified_since,
        )
        return paginate_list(events, offset, limit)

    async def get_event(self: "StatusDemoAdapter", id_: str) -> status_models.Event:
        return status_models.Event.find_by_id(STATE.events, id_)

    async def get_incidents(
        self: "StatusDemoAdapter",
        offset: int,
        limit: int,
        name: str | None = None,
        description: str | None = None,
        status: status_models.Status | None = None,
        type_: status_models.IncidentType | None = None,
        from_: datetime.datetime | None = None,
        to: datetime.datetime | None = None,
        time_: datetime.datetime | None = None,
        modified_since: datetime.datetime | None = None,
        resource_id: str | None = None,
        resolution: status_models.Resolution | None = None,
    ) -> list[status_models.Incident]:
        incidents = status_models.Incident.find(
            STATE.incidents,
            name=name,
            description=description,
            status=status,
            type_=type_,
            from_=from_,
            to=to,
            time_=time_,
            modified_since=modified_since,
            resource_id=resource_id,
            resolution=resolution,
        )
        return paginate_list(incidents, offset, limit)

    async def get_incident(self: "StatusDemoAdapter", id_: str) -> status_models.Incident:
        return status_models.Incident.find_by_id(STATE.incidents, id_)
