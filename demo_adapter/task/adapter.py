"""Task domain demo adapter: a simple in-memory async task queue.

`on_task` is intentionally not implemented here -- it's a concrete
@staticmethod already provided by the upstream `facility_adapter.FacilityAdapter`
ABC (app/routers/task/facility_adapter.py), which dispatches queued commands
to whatever `filesystem` adapter is currently configured. TaskDemoAdapter
inherits it unchanged, and DemoTaskQueue calls it directly off the ABC.
"""
import os

from pydantic import BaseModel

from app.apilogger import get_stream_logger
from app.routers.status import models as status_models
from app.routers.task import facility_adapter, models as task_models
from app.types.user import User

from ..common import DemoAuthMixin, utc_timestamp

logger = get_stream_logger(__name__)

DEMO_QUEUE_UPDATE_SECS = int(os.environ.get("DEMO_QUEUE_UPDATE_SECS", 5))


class DemoTask(BaseModel):
    """A single in-memory queued task."""
    id: str
    task: str
    resource: status_models.Resource
    user: User
    start: float
    status: task_models.TaskStatus = task_models.TaskStatus.pending
    result: dict | None = None


class DemoTaskQueue:
    """A simple in-memory task queue for demonstration purposes."""
    tasks: list[DemoTask] = []

    @staticmethod
    async def process_tasks():
        """Process tasks in the queue, simulating task execution and completion."""
        now = utc_timestamp()
        _tasks = []
        for t in DemoTaskQueue.tasks:
            if now - t.start > 5 * 60 and t.status in [task_models.TaskStatus.completed, task_models.TaskStatus.canceled, task_models.TaskStatus.failed]:
                # delete old tasks
                continue
            if t.status == task_models.TaskStatus.pending and now - t.start > DEMO_QUEUE_UPDATE_SECS:
                t.status = task_models.TaskStatus.active
                t.start = now
            elif t.status == task_models.TaskStatus.active and now - t.start > DEMO_QUEUE_UPDATE_SECS:
                cmd = task_models.TaskCommand.model_validate_json(t.task)
                (result, status) = await facility_adapter.FacilityAdapter.on_task(t.resource, t.user, cmd)
                if isinstance(result, BaseModel):
                    t.result = result.model_dump()
                elif isinstance(result, dict):
                    t.result = result
                else:
                    t.result = {"output": result}
                t.status = status
            _tasks.append(t)
        DemoTaskQueue.tasks = _tasks

    @staticmethod
    def create_task(user: User, resource: status_models.Resource, command: task_models.TaskCommand) -> task_models.TaskSubmitResponse:
        """Create a new task in the queue."""
        task_id = f"task_{len(DemoTaskQueue.tasks)}"
        DemoTaskQueue.tasks.append(DemoTask(id=task_id, task=command.model_dump_json(), user=user, resource=resource, start=utc_timestamp()))
        logger.info(f"Created task: {task_id}")
        return task_models.TaskSubmitResponse(task_id=task_id)


class TaskDemoAdapter(DemoAuthMixin, facility_adapter.FacilityAdapter):
    """Demo implementation of the task domain, backed by DemoTaskQueue."""

    async def get_task(self: "TaskDemoAdapter", user: User, task_id: str) -> task_models.Task | None:
        await DemoTaskQueue.process_tasks()
        return next((t for t in DemoTaskQueue.tasks if t.user.name == user.name and t.id == task_id), None)

    async def get_tasks(self: "TaskDemoAdapter", user: User) -> list[task_models.Task]:
        await DemoTaskQueue.process_tasks()
        return [t for t in DemoTaskQueue.tasks if t.user.name == user.name]

    async def put_task(self: "TaskDemoAdapter", user: User, resource: status_models.Resource, task: task_models.TaskCommand) -> task_models.TaskSubmitResponse:
        await DemoTaskQueue.process_tasks()
        return DemoTaskQueue.create_task(user, resource, task)

    async def delete_task(self: "TaskDemoAdapter", user: User, task_id: str) -> None:
        await DemoTaskQueue.process_tasks()
        for t in DemoTaskQueue.tasks:
            if t.user.name == user.name and t.id == task_id:
                t.status = task_models.TaskStatus.canceled
                t.result = None
                break
