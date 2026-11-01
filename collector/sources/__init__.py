from .csv_feed import CsvSource
from .portal import PortalSource
from .rera_tn import TnReraSource

REGISTRY = {
    "portal": PortalSource,
    "csv": CsvSource,
    "rera": TnReraSource,
}
