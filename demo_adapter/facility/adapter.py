"""Facility domain demo adapter: get_facility, list_sites, get_site."""
import datetime

from fastapi import HTTPException

from app.routers.facility import facility_adapter, models as facility_models

from ..common import DemoAuthMixin
from ..state import STATE


class FacilityDemoAdapter(DemoAuthMixin, facility_adapter.FacilityAdapter):
    """Demo implementation of the facility domain. Reads from the shared DemoState."""

    async def get_facility(self: "FacilityDemoAdapter", modified_since: str | None = None) -> facility_models.Facility:
        return STATE.facility

    async def list_sites(
        self: "FacilityDemoAdapter",
        modified_since: str | None = None,
        name: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
        short_name: str | None = None,
    ) -> list[facility_models.Site]:
        sites = STATE.sites

        if name:
            sites = [s for s in sites if name.lower() in s.name.lower()]  # pylint: disable=no-member

        if short_name:
            sites = [s for s in sites if s.short_name == short_name]

        if modified_since:
            ms = datetime.datetime.fromisoformat(str(modified_since))
            sites = [s for s in sites if s.last_modified > ms]

        o = offset or 0
        l = limit or len(sites)
        return sites[o : o + l]

    async def get_site(self: "FacilityDemoAdapter", site_id: str, modified_since: str | None = None) -> facility_models.Site:
        site = next((s for s in STATE.sites if s.id == site_id), None)
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")

        if modified_since:
            ms = datetime.datetime.fromisoformat(str(modified_since))
            if site.last_modified <= ms:
                raise HTTPException(status_code=304, headers={"Last-Modified": site.last_modified.isoformat()})

        return site
