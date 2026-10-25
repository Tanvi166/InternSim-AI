import os
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

# Try importing Supabase client; if unavailable (e.g., in test environment), provide a lightweight stub.
try:
    from supabase import create_client, Client  # type: ignore
except ImportError:  # pragma: no cover
    # Minimal in‑memory mock that satisfies the subset of Supabase methods used in the codebase.
    class _StubAuth:
        def get_user(self, token: str):
            class _User:
                def __init__(self):
                    self.id = "stub-user-id"
            class _Response:
                def __init__(self):
                    self.user = _User()
            return _Response()

    class _StubTable:
        def __init__(self, name: str):
            self.name = name
            self._rows: list[dict] = []

        def select(self, *args, **kwargs):
            return self

        def ilike(self, *args, **kwargs):
            # No-op stub for case-insensitive LIKE filter
            return self

        def limit(self, *args, **kwargs):
            # No-op stub for limiting results
            return self

        def eq(self, col: str, val: Any):
            self._eq_filters = getattr(self, "_eq_filters", {})
            self._eq_filters[col] = val
            return self

        def order(self, *args, **kwargs):
            return self

        def in_(self, *args, **kwargs):
            return self

        def gte(self, *args, **kwargs):
            return self

        def insert(self, row: dict):
            row = row.copy()
            row.setdefault("submission_id", f"sub_{len(self._rows)+1}")
            row.setdefault("created_at", "1970-01-01T00:00:00Z")
            self._rows.append(row)
            return self

        def delete(self):
            filters = getattr(self, "_eq_filters", {})
            if filters:
                self._rows = [
                    r for r in self._rows
                    if not all(r.get(k) == v for k, v in filters.items())
                ]
            else:
                self._rows.clear()
            self._eq_filters = {}
            return self

        def update(self, updates: dict):
            for r in self._rows:
                r.update(updates)
            return self

        def execute(self):
            filters = getattr(self, "_eq_filters", {})
            rows = self._rows
            if filters:
                rows = [
                    r for r in rows
                    if all(r.get(k) == v for k, v in filters.items())
                ]
            self._eq_filters = {}
            return type("Res", (), {"data": rows})()



    class _StubClient:
        def __init__(self):
            self.auth = _StubAuth()
            self._tables: dict[str, _StubTable] = {}
        def table(self, name: str):
            if name not in self._tables:
                self._tables[name] = _StubTable(name)
            return self._tables[name]

    def create_client(url: str, key: str) -> "_StubClient":  # type: ignore
        return _StubClient()

    Client = _StubClient  # type: ignore

# Explicitly load .env from the backend directory.
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_SERVICE_KEY")
    or os.environ.get("SUPABASE_KEY")
    or os.environ.get("SUPABASE_ANON_KEY")
)

if not SUPABASE_URL or not SUPABASE_KEY:
    print("WARNING: Supabase credentials not found in environment.")

def get_supabase_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase credentials (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY) not found in environment.")
    return create_client(SUPABASE_URL, SUPABASE_KEY)
