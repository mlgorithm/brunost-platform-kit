from brunost_platform.identity import ExternalIdentityAdapter, ExternalPrincipal
from brunost_platform.models import User
from brunost_platform.policy import GLOBAL_TASK_LIBRARY, PlatformPolicy


def user(*roles: str) -> User:
    return User("u-1", "student@example.org", "Student", roles=roles)


def test_standalone_allows_only_admin_contest_creation() -> None:
    policy = PlatformPolicy()

    assert policy.can_create_contest(user("admin"))
    assert not policy.can_create_contest(user("student"))
    assert not policy.global_task_library_enabled
    assert policy.can_create_global_task(user("admin")) is False


def test_advanced_policy_allows_creator_roles_and_global_tasks() -> None:
    policy = PlatformPolicy("advanced")

    assert policy.can_create_contest(user("teacher"))
    assert policy.can_manage_platform(user("organizer"))
    assert policy.global_task_library_enabled
    assert policy.can_create_global_task(user("teacher"))
    assert policy.enabled(GLOBAL_TASK_LIBRARY)


def test_external_identity_adapter_normalizes_principal_mapping() -> None:
    adapter = ExternalIdentityAdapter(
        lambda _request: {
            "sub": "oidc|42",
            "email": "operator@example.org",
            "display_name": "Country operator",
            "roles": "admin",
            "organization_id": "country-2026",
            "department": "olympiad",
        }
    )

    principal = adapter.resolve({})
    assert principal == ExternalPrincipal(
        subject_id="oidc|42",
        email="operator@example.org",
        display_name="Country operator",
        roles=("admin",),
        organization_id="country-2026",
        metadata={"department": "olympiad"},
    )
    assert adapter.get_subject({}) == "oidc|42"

