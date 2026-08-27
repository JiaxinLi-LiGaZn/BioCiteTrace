"""Typed errors used by the public citation-review workflow."""


class CitationReviewError(Exception):
    """Base class for deterministic workflow failures."""


class ContractError(CitationReviewError):
    """Raised when input or output violates a frozen scientific contract."""


class AgentExecutionError(CitationReviewError):
    """Raised when an external agent cannot produce a validated result."""


class UnknownInFlightError(CitationReviewError):
    """Raised when a durable claim exists without a terminal record."""
