"""Compute domain demo adapter: job submission, status, cancellation."""
import random

from app.request_context import get_iri_facility_project
from app.routers.compute import facility_adapter, models as compute_models
from app.routers.status import models as status_models
from app.types.user import User

from ..common import DemoAuthMixin, utc_timestamp


class ComputeDemoAdapter(DemoAuthMixin, facility_adapter.FacilityAdapter):
    """Demo implementation of the compute domain."""

    async def submit_job(
        self: "ComputeDemoAdapter",
        resource: status_models.Resource,
        user: User,
        job_spec: compute_models.JobSpec,
    ) -> compute_models.Job:
        facility_project = get_iri_facility_project()
        account = facility_project or (job_spec.attributes.account if job_spec.attributes else None)
        return compute_models.Job(
            id="job_123",
            status=compute_models.JobStatus(
                state=compute_models.JobState.NEW,
                time=utc_timestamp(),
                message="job submitted",
                exit_code=0,
                meta_data={"account": account},
            ),
        )

    async def update_job(
        self: "ComputeDemoAdapter",
        resource: status_models.Resource,
        user: User,
        job_spec: compute_models.JobSpec,
        job_id: str,
    ) -> compute_models.Job:
        facility_project = get_iri_facility_project()
        account = facility_project or (job_spec.attributes.account if job_spec.attributes else None)
        return compute_models.Job(
            id=job_id,
            status=compute_models.JobStatus(
                state=compute_models.JobState.ACTIVE,
                time=utc_timestamp(),
                message="job updated",
                exit_code=0,
                meta_data={"account": account},
            ),
        )

    async def get_job(
        self: "ComputeDemoAdapter",
        resource: status_models.Resource,
        user: User,
        job_id: str,
        historical: bool = False,
        include_spec: bool = False,
    ) -> compute_models.Job:
        return compute_models.Job(
            id=job_id,
            status=compute_models.JobStatus(
                state=compute_models.JobState.COMPLETED,
                time=utc_timestamp(),
                message="job completed successfully",
                exit_code=0,
                meta_data={"account": "account1"},
            ),
        )

    async def get_jobs(
        self: "ComputeDemoAdapter",
        resource: status_models.Resource,
        user: User,
        offset: int,
        limit: int,
        filters: dict[str, object] | None = None,
        historical: bool = False,
        include_spec: bool = False,
    ) -> list[compute_models.Job]:
        return [
            compute_models.Job(
                id=f"job_{i}",
                status=compute_models.JobStatus(
                    state=random.choice([s for s in compute_models.JobState]),
                    time=utc_timestamp() - int(random.random() * 100),
                    message="",
                    exit_code=random.choice([0, 0, 0, 0, 0, 1, 1, 128, 127]),
                    meta_data={"account": "account1"},
                ),
            )
            for i in range(random.randint(3, 10))
        ]

    async def cancel_job(
        self: "ComputeDemoAdapter",
        resource: status_models.Resource,
        user: User,
        job_id: str,
    ) -> bool:
        # call slurm/etc. to cancel job
        return True
