"""Open-source application layer for Brunost Judge.

The kit is intentionally small and dependency-free.  Generated applications
may choose FastAPI, a Node framework, or another web stack while using the same
judge gateway and platform module contracts.
"""

from brunost_platform.artifacts import artifact_id, pack_directory
from brunost_platform.callbacks import verify_judge_callback
from brunost_platform.contracts import (
    ArtifactSubmission,
    ContractValidationError,
    EvaluationRequest,
    ResultArtifact,
    ResultEnvelope,
    TaskRegistration,
    normalize_result,
)
from brunost_platform.gateway import HttpJudgeGateway, JudgeGateway, JudgeGatewayError
from brunost_platform.identity import ExternalIdentityAdapter, ExternalPrincipal, LocalIdentityAdapter
from brunost_platform.leaderboard_policy import LeaderboardPolicy, normalize_policy, project_leaderboard
from brunost_platform.models import Contest, LeaderboardEntry, Submission, User, WorkerOperation
from brunost_platform.policy import (
    COURSES,
    CREATE_CONTEST,
    CREATE_NESTED_TASK,
    GLOBAL_TASK_LIBRARY,
    MANAGE_CONTEST,
    USER_CREATED_CONTESTS,
    PlatformPolicy,
)
from brunost_platform.postgres import PostgresPlatformStore
from brunost_platform.store import SQLitePlatformStore

__all__ = [
    "COURSES",
    "CREATE_CONTEST",
    "CREATE_NESTED_TASK",
    "GLOBAL_TASK_LIBRARY",
    "MANAGE_CONTEST",
    "USER_CREATED_CONTESTS",
    "ArtifactSubmission",
    "Contest",
    "ContractValidationError",
    "EvaluationRequest",
    "ExternalIdentityAdapter",
    "ExternalPrincipal",
    "HttpJudgeGateway",
    "JudgeGateway",
    "JudgeGatewayError",
    "LeaderboardEntry",
    "LeaderboardPolicy",
    "LocalIdentityAdapter",
    "PlatformPolicy",
    "PostgresPlatformStore",
    "ResultArtifact",
    "ResultEnvelope",
    "SQLitePlatformStore",
    "Submission",
    "TaskRegistration",
    "User",
    "WorkerOperation",
    "artifact_id",
    "normalize_policy",
    "normalize_result",
    "pack_directory",
    "project_leaderboard",
    "verify_judge_callback",
]

__version__ = "0.2.0"
