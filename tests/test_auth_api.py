from __future__ import annotations

from backend.api.auth import login_payload, signup_payload, update_profile_payload
from backend.api.models import LoginRequest, SignupRequest, UpdateProfileRequest
from backend.auth import hash_password, verify_password
from backend.config import Settings
from backend.storage import UserContext
from fastapi import HTTPException
import pytest


class FakeAuthStore:
  def __init__(self):
    self.users = {}

  def email_exists(self, email, *, exclude_user_id=None):
    for user_id, record in self.users.items():
      if record["email"] == email and user_id != exclude_user_id:
        return True
    return False

  def create_registered_user(self, email, *, password_hash, display_name="", role="owner"):
    if self.email_exists(email):
      from backend.storage import StorageError

      raise StorageError("An account with this email already exists.")
    user_id = f"user-{len(self.users) + 1}"
    record = {
      "id": user_id,
      "email": email,
      "role": role,
      "display_name": display_name,
      "password_hash": password_hash,
      "is_active": True,
    }
    self.users[user_id] = record
    return UserContext(**{key: record[key] for key in ("id", "email", "role", "display_name", "is_active")})

  def get_user_auth_record_by_email(self, email):
    for record in self.users.values():
      if record["email"] == email:
        return record
    return None

  def get_user_usage_summary(self, user_id):
    record = self.users.get(user_id)
    if not record:
      from backend.storage import StorageError

      raise StorageError("User not found.")
    if record["role"] == "admin":
      return {"unlimited": True, "blocked_reason": ""}
    return {
      "unlimited": False,
      "blocked_reason": "",
      "daily": {"limit": 1000, "used": 0, "remaining": 1000},
      "weekly": {"limit": 5000, "used": 0, "remaining": 5000},
      "monthly": {"limit": 10000, "used": 0, "remaining": 10000},
    }

  def get_user_by_id(self, user_id):
    record = self.users.get(user_id)
    if not record:
      return None
    return UserContext(**{key: record[key] for key in ("id", "email", "role", "display_name", "is_active")})

  def get_user_password_hash(self, user_id):
    record = self.users.get(user_id)
    return record["password_hash"] if record else None

  def update_user_profile(self, user_id, *, email=None, display_name=None, password_hash=None):
    record = self.users.get(user_id)
    if not record:
      from backend.storage import StorageError

      raise StorageError("User not found.")
    if email is not None:
      if self.email_exists(email, exclude_user_id=user_id):
        from backend.storage import StorageError

        raise StorageError("An account with this email already exists.")
      record["email"] = email
    if display_name is not None:
      record["display_name"] = display_name
    if password_hash is not None:
      record["password_hash"] = password_hash
    return UserContext(**{key: record[key] for key in ("id", "email", "role", "display_name", "is_active")})


def test_password_hash_roundtrip():
  hashed = hash_password("secret-password")
  assert verify_password("secret-password", hashed)
  assert not verify_password("wrong-password", hashed)


def _settings(**overrides):
  base = dict(
    database_url="postgresql://example",
    frontend_origins=["http://localhost:5174"],
    dev_user_email="dev@vibe.local",
    gemini_api_key="",
    gemini_model="gemini-test",
    app_root=__import__("pathlib").Path("."),
    local_workspace_roots=[__import__("pathlib").Path(".")],
    jwt_secret="test-secret",
    auth_allow_signup=True,
  )
  base.update(overrides)
  return Settings(**base)


def test_signup_and_login_payload():
  store = FakeAuthStore()
  settings = _settings()
  signup = signup_payload(
    SignupRequest(email="builder@example.com", password="password123", display_name="Builder"),
    store,
    settings,
  )
  assert signup["user"]["email"] == "builder@example.com"
  assert signup["user"]["display_name"] == "Builder"
  assert signup["token"]

  login = login_payload(
    LoginRequest(email="builder@example.com", password="password123"),
    store,
    settings,
  )
  assert login["user"]["id"] == signup["user"]["id"]
  assert login["token"]


def test_signup_disabled_by_default():
  store = FakeAuthStore()
  settings = _settings(auth_allow_signup=False)
  with pytest.raises(HTTPException) as exc:
    signup_payload(
      SignupRequest(email="builder@example.com", password="password123", display_name="Builder"),
      store,
      settings,
    )
  assert exc.value.status_code == 403


def test_update_profile_payload_changes_email_and_password():
  store = FakeAuthStore()
  settings = _settings()
  created = signup_payload(
    SignupRequest(email="builder@example.com", password="password123", display_name="Builder"),
    store,
    settings,
  )
  user = UserContext(
    id=created["user"]["id"],
    email=created["user"]["email"],
    role=created["user"]["role"],
    display_name=created["user"]["display_name"],
  )
  updated = update_profile_payload(
    user,
    UpdateProfileRequest(
      email="new@example.com",
      display_name="New Name",
      current_password="password123",
      new_password="new-password-1",
    ),
    store,
  )
  assert updated["user"]["email"] == "new@example.com"
  assert updated["user"]["display_name"] == "New Name"
  record = store.get_user_auth_record_by_email("new@example.com")
  assert verify_password("new-password-1", record["password_hash"])
