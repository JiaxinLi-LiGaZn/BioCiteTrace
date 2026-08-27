"""Evidence-grounded citation-use review utilities."""

# Package imports expose the stable validation and comparison entry points.
from .contracts import validate_capsule, validate_classification
from .comparison import compare_classifications

__all__ = ["compare_classifications", "validate_capsule", "validate_classification"]
__version__ = "0.2.0"
