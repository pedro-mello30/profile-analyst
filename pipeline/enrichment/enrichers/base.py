"""EnrichmentEnricher ABC — pure data transformer, no I/O (spec-0019 §5.3)."""
from __future__ import annotations
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

_REQUIRED = ("enricher_id", "adapter_id", "min_confidence")


class EnricherContractError(RuntimeError):
    pass


class EnrichmentEnricher(ABC):
    """Base class for pure data-transformation enrichers. No network calls allowed.

    extract() is a pure function: no HTTP, no file I/O, no randomness.
    extract() never raises for partial data — missing fields return fewer entities.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Skip intermediate abstract classes
        if any(getattr(v, "__isabstractmethod__", False) for v in cls.__dict__.values()):
            return
        errors = []
        for attr in _REQUIRED:
            if not hasattr(cls, attr):
                errors.append(f"missing required attribute: {attr!r}")
        if hasattr(cls, "min_confidence"):
            mc = cls.min_confidence
            if isinstance(mc, (int, float)) and not (0.0 <= mc <= 1.0):
                errors.append(f"min_confidence={mc!r} out of [0.0, 1.0]")
        if errors:
            raise EnricherContractError(
                f"Enricher {cls.__name__!r} has {len(errors)} violation(s):\n"
                + "\n".join(f"  • {e}" for e in errors)
            )

    @abstractmethod
    def extract(self, raw_data: dict) -> list:
        """Extract entities from raw_data. Pure — no I/O, no side effects."""
        ...

    def safe_extract(self, raw_data: dict) -> list:
        """Wraps extract() catching all exceptions; returns [] on error."""
        try:
            return self.extract(raw_data)
        except Exception as exc:
            logger.warning("%s.safe_extract() failed: %s", self.__class__.__name__, exc)
            return []
