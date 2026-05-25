"""thesis-generator — verify-first multi-agent thesis pipeline.

Public surface:
    from thesis_generator import ThesisProject, run_pipeline
"""

from thesis_generator.config import ThesisProject
from thesis_generator.pipeline import run_pipeline

__version__ = "0.1.0"
__all__ = ["ThesisProject", "run_pipeline", "__version__"]
