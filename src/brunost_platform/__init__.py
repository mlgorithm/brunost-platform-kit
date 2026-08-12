"""Open-source application layer for Brunost Judge.

The kit is intentionally small and dependency-free.  Generated applications
may choose FastAPI, a Node framework, or another web stack while using the same
judge gateway and platform module contracts.
"""

from brunost_platform.artifacts import artifact_id, pack_directory
from brunost_platform.callbacks import verify_judge_callback
from brunost_platform.gateway import HttpJudgeGateway, JudgeGateway, JudgeGatewayError
from brunost_platform.identity import ExternalIdentityAdapter, LocalIdentityAdapter
from brunost_platform.models import Contest, LeaderboardEntry, Submission, User
from brunost_platform.store import SQLitePlatformStore

__all__ = [
    "Contest",
    "ExternalIdentityAdapter",
    "HttpJudgeGateway",
    "JudgeGateway",
    "JudgeGatewayError",
    "LeaderboardEntry",
    "LocalIdentityAdapter",
    "SQLitePlatformStore",
    "Submission",
    "User",
    "artifact_id",
    "pack_directory",
    "verify_judge_callback",
]

__version__ = "0.1.0"
