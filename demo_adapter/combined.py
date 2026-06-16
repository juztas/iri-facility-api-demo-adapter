"""Convenience class combining all 7 per-domain demo adapters into one.

Equivalent to the original monolithic DemoAdapter in iri-facility-api-python.
Useful for wiring every IRI_API_ADAPTER_<domain> env var to a single class
when you want the full out-of-the-box demo. For real facility deployments,
prefer wiring each IRI_API_ADAPTER_<domain> to its own class (see the
per-domain adapter.py modules) so domains can be swapped independently.
"""
from .account.adapter import AccountDemoAdapter
from .common import DemoAuthMixin
from .compute.adapter import ComputeDemoAdapter
from .facility.adapter import FacilityDemoAdapter
from .filesystem.adapter import FilesystemDemoAdapter
from .status.adapter import StatusDemoAdapter
from .storage.adapter import StorageDemoAdapter
from .task.adapter import TaskDemoAdapter


class DemoAdapter(
    FacilityDemoAdapter,
    StatusDemoAdapter,
    AccountDemoAdapter,
    ComputeDemoAdapter,
    FilesystemDemoAdapter,
    StorageDemoAdapter,
    TaskDemoAdapter,
    DemoAuthMixin,
):
    """Implements every domain's FacilityAdapter at once, like the original demo_adapter.DemoAdapter."""
