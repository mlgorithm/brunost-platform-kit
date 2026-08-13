from pathlib import Path

from brunost_platform.identity import LocalIdentityAdapter
from brunost_platform.models import User
from brunost_platform.notifications import MemoryNotificationAdapter
from brunost_platform.store import SQLitePlatformStore


def test_identity_and_notification_adapters(tmp_path: Path):
    identity = LocalIdentityAdapter(SQLitePlatformStore(tmp_path / "identity.db"))
    identity.provision(User("u1", "u@example.test", "Student"))
    assert identity.get_subject({"x-user-id": "u1"}) == "u1"
    mail = MemoryNotificationAdapter()
    mail.send(recipient="u@example.test", subject="Result", body="Done")
    assert mail.messages[0]["subject"] == "Result"


def test_bootstrap_password_can_be_changed_and_flag_is_cleared(tmp_path: Path):
    store = SQLitePlatformStore(tmp_path / "bootstrap.db")
    identity = LocalIdentityAdapter(store)
    user = identity.register(
        email="admin@example.test",
        password="change-me-now",
        display_name="Country operator",
        roles=("admin",),
        metadata={"must_change_password": True},
    )
    updated = identity.change_password(user_id=user.user_id, current_password="change-me-now", new_password="new-secure-password")
    assert updated.metadata["must_change_password"] is False
    assert identity.authenticate(email=user.email, password="change-me-now") is None
    assert identity.authenticate(email=user.email, password="new-secure-password")


def test_callback_event_deduplication(tmp_path: Path):
    store = SQLitePlatformStore(tmp_path / "callbacks.db")
    assert store.accept_callback_event("execution:1:result") is True
    assert store.accept_callback_event("execution:1:result") is False
