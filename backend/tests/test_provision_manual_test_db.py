"""Manual-test database provisioning script, offline (23 Oct 2026).

No database is opened here: every step's guard is exercised with the
connection function replaced by one that fails the test if called.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from tests.test_manual_test_server import SHARED, VALID

spec = importlib.util.spec_from_file_location(
    "provision_manual_test_db", Path(__file__).resolve().parents[1] / "scripts" / "provision_manual_test_db.py")
provision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provision)


@pytest.fixture
def files(tmp_path, monkeypatch):
    def no_connection(*args, **kwargs):
        raise AssertionError("a database connection was opened")
    monkeypatch.setattr(provision, "_connect", no_connection)

    def write(test_values):
        test_env, shared_env = tmp_path / ".env.manual-test", tmp_path / "shared.env"
        test_env.write_text("".join(f"{k}={v}\n" for k, v in test_values.items()))
        shared_env.write_text("".join(f"{k}={v}\n" for k, v in SHARED.items() if v))
        return ["--test-env", str(test_env), "--shared-env", str(shared_env)]
    return write


@pytest.mark.parametrize("step", list(provision.STEPS))
def test_every_step_refuses_a_shared_or_missing_test_database_before_connecting(step, files, capsys):
    args = files({**VALID, "KRITON_TEST_DATABASE_URL": SHARED["DATABASE_URL"]})
    assert provision.main([step, *args]) == 2
    assert "NOT run" in capsys.readouterr().out
    assert provision.main([step, *files({})]) == 2


def test_plan_prints_every_step_and_connects_nowhere(files, capsys):
    assert provision.main(["plan", *files(VALID)]) == 0
    out = capsys.readouterr().out
    for step in ("create", "setup", "marker", "seed", "copy-kb", "check"):
        assert step in out
    assert "BYPASSRLS NOSUPERUSER" in out and "NOBYPASSRLS" in out


@pytest.mark.parametrize("step", ["create", "setup", "marker", "seed", "copy-kb"])
def test_writing_steps_need_a_local_test_database(step, files, capsys):
    remote = "postgresql://postgres.testproject9:pw@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"
    app = "postgresql://kriton_test_app.testproject9:pw@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"
    args = files({**VALID, "KRITON_TEST_DATABASE_URL": remote, "KRITON_TEST_APP_DATABASE_URL": app})
    assert provision.main([step, *args, "--user-id", "u", "--email", "e@x", "--name", "N"]) == 2
    assert "must be on this machine" in capsys.readouterr().out


def test_the_superuser_connection_must_be_local(files, capsys):
    args = files(VALID)
    assert provision.main(["create", *args, "--superuser-url", "postgresql://admin@db.example.com/postgres"]) == 2
    assert "must be on this machine" in capsys.readouterr().out


def test_seed_needs_your_identity(files, capsys, tmp_path):
    assert provision.main(["seed", *files(VALID), "--identity-file", str(tmp_path / "none.json")]) == 2
    assert "--user-id" in capsys.readouterr().out


# ── Seed hardening and the read-only identity lookup ─────────────────────

ROLES = frozenset({"Admin", "Learner"})
UID = "8F14E45F-CEEA-467A-9575-3B3C2F1E2D4A"


def test_identity_is_normalised():
    assert provision.validate_identity(UID, "  Me@Example.COM ", " Ada   Lovelace ", "Admin", ROLES) == (
        UID.lower(), "me@example.com", "Ada Lovelace", "Admin")


@pytest.mark.parametrize("user_id, email, name, role, problem", [
    ("not-a-uuid", "me@example.com", "Ada", "Admin", "not a UUID"),
    (UID, "me@example", "Ada", "Admin", "not a valid address"),
    (UID, "me example.com", "Ada", "Admin", "not a valid address"),
    (UID, "me@example.com", "   ", "Admin", "name is empty"),
    (UID, "me@example.com", "Ada", "Superuser", "is not one of"),
    (UID, "me@example.com", "Ada", "admin", "is not one of"),
])
def test_invalid_identity_is_refused(user_id, email, name, role, problem):
    with pytest.raises(provision.StepRefused, match=problem):
        provision.validate_identity(user_id, email, name, role, ROLES)


def test_the_real_role_registry_is_the_allowlist():
    assert {"Admin", "Learner", "SME Reviewer"} <= provision.known_roles()


def test_output_shows_only_short_ids_and_masked_email():
    assert provision.short_id(UID.lower()) == "8f14e45f…"
    assert provision.mask_email("someone@example.com") == "s***@e***.com"


class _ScriptedCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.statements.append(sql.strip().split()[0].upper() + " " + sql.strip()[:60])
        self.last = sql

    def fetchone(self):
        if "current_database()" in self.last:
            return self.conn.identity
        if "transaction_read_only" in self.last:
            return ("on",)
        return None

    def fetchall(self):
        return self.conn.rows


class _ScriptedConnection:
    def __init__(self, identity=("kriton_manual_test", "kriton_test_owner"), rows=()):
        self.identity, self.rows, self.statements = identity, list(rows), []

    def cursor(self):
        return _ScriptedCursor(self)

    def set_session(self, **kwargs):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _seed_args(files, tmp_path, **identity):
    path = tmp_path / "seed-identity.json"
    path.write_text(json.dumps({"user_id": UID, "email": "me@example.com", "name": "Ada Lovelace", "role": "Admin",
                                **identity}))
    path.chmod(0o600)
    return ["seed", *files(VALID), "--identity-file", str(path)]


def test_seed_refuses_when_the_live_connection_is_another_database(files, tmp_path, monkeypatch, capsys):
    fake = _ScriptedConnection(identity=("stage10_db", "kriton_test_owner"))
    monkeypatch.setattr(provision, "_connect", lambda url, **o: fake)
    assert provision.main(_seed_args(files, tmp_path)) == 2
    assert "live connection is not kriton_manual_test" in capsys.readouterr().out
    assert not any(s.startswith("INSERT") for s in fake.statements)


def test_seed_refuses_a_bad_identity_before_connecting(files, tmp_path, capsys):
    assert provision.main(_seed_args(files, tmp_path, user_id="12345")) == 2   # _connect fails the test if called
    assert "not a UUID" in capsys.readouterr().out


def test_seed_refuses_an_identity_file_others_can_read(files, tmp_path, capsys):
    args = _seed_args(files, tmp_path)
    Path(args[-1]).chmod(0o644)
    assert provision.main(args) == 2
    assert "readable by other users" in capsys.readouterr().out


def test_seed_writes_the_tenant_then_the_profile_and_prints_short_ids(files, tmp_path, monkeypatch, capsys):
    fake = _ScriptedConnection()
    monkeypatch.setattr(provision, "_connect", lambda url, **o: fake)
    assert provision.main(_seed_args(files, tmp_path)) == 0
    inserts = [s for s in fake.statements if s.startswith("INSERT")]
    assert len(inserts) == 2 and "tenants" in inserts[0] and "users" in inserts[1]
    out = capsys.readouterr().out
    assert "8f14e45f…" in out and UID.lower() not in out and "me@example.com" not in out


def _lookup_args(files, tmp_path, email="Me@Example.com", mode=0o600):
    email_file = tmp_path / "lookup-email"
    email_file.write_text(email + "\n")
    email_file.chmod(mode)
    return ["lookup", *files(VALID), "--email-file", str(email_file), "--identity-file", str(tmp_path / "out.json")]


@pytest.mark.parametrize("rows, message", [([], "0 profiles match"), ([("a",) * 5, ("b",) * 5], "2 profiles match")])
def test_lookup_needs_exactly_one_match(files, tmp_path, monkeypatch, capsys, rows, message):
    monkeypatch.setattr(provision, "_connect", lambda url, **o: _ScriptedConnection(rows=rows))
    assert provision.main(_lookup_args(files, tmp_path)) == 2
    assert message in capsys.readouterr().out and not (tmp_path / "out.json").exists()


def test_lookup_refuses_an_inactive_profile(files, tmp_path, monkeypatch, capsys):
    rows = [(UID, "me@example.com", "Ada Lovelace", "Admin", False)]
    monkeypatch.setattr(provision, "_connect", lambda url, **o: _ScriptedConnection(rows=rows))
    assert provision.main(_lookup_args(files, tmp_path)) == 2
    assert "inactive" in capsys.readouterr().out


def test_lookup_reads_only_and_saves_a_private_identity(files, tmp_path, monkeypatch, capsys):
    fake = _ScriptedConnection(rows=[(UID.lower(), "me@example.com", "Ada Lovelace", "Admin", True)])
    monkeypatch.setattr(provision, "_connect", lambda url, **o: fake)
    assert provision.main(_lookup_args(files, tmp_path)) == 0
    assert all(s.startswith(("SHOW", "SELECT")) for s in fake.statements)
    saved = tmp_path / "out.json"
    assert saved.stat().st_mode & 0o777 == 0o600
    assert json.loads(saved.read_text()) == {"user_id": UID.lower(), "email": "me@example.com",
                                             "name": "Ada Lovelace", "role": "Admin"}
    out = capsys.readouterr().out
    assert "8f14e45f…" in out and "m***@e***.com" in out
    assert UID.lower() not in out and "me@example.com" not in out and "Lovelace" not in out


@pytest.mark.parametrize("shared_name, saved_name, fallback", [
    ("", "Kriton manual tester", "yes"),
    ("   ", "Kriton manual tester", "yes"),
    (None, "Kriton manual tester", "yes"),
    ("A" * 201, "Kriton manual tester", "yes"),
    ("A" * 200, "A" * 200, "no"),
    ("  Ada   Lovelace ", "Ada Lovelace", "no"),
])
def test_the_fallback_name_is_used_only_when_the_shared_name_is_unusable(
        files, tmp_path, monkeypatch, capsys, shared_name, saved_name, fallback):
    fake = _ScriptedConnection(rows=[(UID.lower(), "me@example.com", shared_name, "Admin", True)])
    monkeypatch.setattr(provision, "_connect", lambda url, **o: fake)
    assert provision.main(_lookup_args(files, tmp_path)) == 0
    saved = tmp_path / "out.json"
    assert json.loads(saved.read_text())["name"] == saved_name and saved.stat().st_mode & 0o777 == 0o600
    out = capsys.readouterr().out
    assert f"fallback name used: {fallback}" in out and "role Admin" in out
    assert UID.lower() not in out and "me@example.com" not in out and "Lovelace" not in out


@pytest.mark.parametrize("problem_row, message", [
    ((UID.lower(), "not-an-email", "", "Admin", True), "not a valid address"),
    ((UID.lower(), "me@example.com", "", "Superuser", True), "is not one of"),
    (("12345", "me@example.com", "", "Admin", True), "not a UUID"),
])
def test_the_fallback_does_not_relax_the_other_checks(files, tmp_path, monkeypatch, capsys, problem_row, message):
    monkeypatch.setattr(provision, "_connect", lambda url, **o: _ScriptedConnection(rows=[problem_row]))
    assert provision.main(_lookup_args(files, tmp_path)) == 2
    assert message in capsys.readouterr().out and not (tmp_path / "out.json").exists()


def test_lookup_refuses_an_email_file_others_can_read(files, tmp_path, capsys):
    assert provision.main(_lookup_args(files, tmp_path, mode=0o644)) == 2
    assert "readable by other users" in capsys.readouterr().out


def test_setup_refuses_when_a_dotenv_could_be_loaded(files, capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(provision, "BACKEND", tmp_path)
    (tmp_path / ".env").write_text("DATABASE_URL=shared\n")
    assert provision.main(["setup", *files(VALID)]) == 2
    assert ".env" in capsys.readouterr().out


def test_setup_receives_only_the_test_database():
    env = provision.setup_environment({"DATABASE_URL": "t", "APP_DATABASE_URL": "a", "GROQ_API_KEY": "k",
                                       "SUPABASE_SERVICE_ROLE_KEY": "s"})
    assert set(env) == {"PATH", "HOME", "DATABASE_URL", "APP_DATABASE_URL", "SKIP_STARTUP_FINGERPRINT_CHECK",
                        "HEALTH_SAMPLER_ENABLED"}
    assert env["DATABASE_URL"] == "t" and env["APP_DATABASE_URL"] == "a"


def test_the_shared_database_is_opened_read_only():
    options = provision.read_only_options()["options"]
    assert "default_transaction_read_only=on" in options


class _FakeConnection:
    def __init__(self, read_only):
        self.read_only, self.session, self.closed, self.statements = read_only, None, False, []

    def set_session(self, **kwargs):
        self.session = kwargs

    def cursor(self):
        connection = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                connection.statements.append(sql)

            def fetchone(self):
                return (connection.read_only,)
        return Cursor()

    def close(self):
        self.closed = True


@pytest.mark.parametrize("state", ["off", ""])
def test_a_shared_session_that_is_not_read_only_runs_nothing(monkeypatch, state):
    fake = _FakeConnection(state)
    monkeypatch.setattr(provision, "_connect", lambda url, **options: fake)
    with pytest.raises(provision.StepRefused, match="not run|nothing was run"):
        provision._shared_read_only("postgresql://x@shared/postgres")
    assert fake.closed and fake.statements == ["SHOW transaction_read_only"]


def test_the_shared_session_is_read_only_per_transaction_and_verified(monkeypatch):
    fake = _FakeConnection("on")
    seen = {}

    def connect(url, **options):
        seen.update(options)
        return fake
    monkeypatch.setattr(provision, "_connect", connect)
    assert provision._shared_read_only("postgresql://x@shared/postgres") is fake
    assert fake.session == {"readonly": True, "autocommit": False}
    assert "default_transaction_read_only=on" in seen["options"]


def test_the_expected_schema_includes_the_embedding_and_provenance():
    expected = provision.expected_columns()
    assert {"embedding", "derived_from_passage_id"} <= expected["source_passages"]
    assert {"submitted_by", "approved_by", "status"} <= expected["source_versions"]


def test_schema_differences_are_reported():
    notes = provision.compatibility({"sources": {"id", "title"}, "source_rights": {"id"}},
                                    {"sources": {"id", "legacy"}})
    assert "sources: shared database lacks title" in notes
    assert "sources: shared database has extra legacy (not copied)" in notes
    assert "source_rights: missing in the shared database" in notes


def test_passwords_are_sent_as_scram_verifiers_not_plaintext():
    import base64
    import hashlib
    import hmac
    salt = b"0123456789abcdef"
    verifier = provision.scram_verifier("s3cret-pass", salt=salt)
    assert "s3cret-pass" not in verifier
    method, rest = verifier.split("$", 1)
    params, keys = rest.split("$")
    iterations, salt64 = params.split(":")
    stored64, server64 = keys.split(":")
    assert method == "SCRAM-SHA-256" and iterations == "4096" and base64.b64decode(salt64) == salt
    # RFC 5802 / 7677 derivation, recomputed independently.
    salted = hashlib.pbkdf2_hmac("sha256", b"s3cret-pass", salt, 4096)
    client = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    assert base64.b64decode(stored64) == hashlib.sha256(client).digest()
    assert base64.b64decode(server64) == hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    assert provision.scram_verifier("s3cret-pass") != provision.scram_verifier("s3cret-pass")  # fresh salt


def test_the_plan_restricts_the_new_database_to_the_test_roles(files, capsys):
    provision.main(["plan", *files(VALID)])
    out = capsys.readouterr().out
    assert "REVOKE ALL ON DATABASE kriton_manual_test FROM PUBLIC" in out
    assert "GRANT CONNECT ON DATABASE kriton_manual_test TO kriton_test_app" in out
    assert "NOREPLICATION" in out and "SCRAM verifier" in out


@pytest.mark.parametrize("name", ["kriton_manual_test", "kriton_test_app"])
def test_plain_identifiers_are_accepted(name):
    assert provision.identifier(name, "role") == name


@pytest.mark.parametrize("name", ["Kriton", "x; DROP DATABASE postgres", "", "a-b", "1abc"])
def test_anything_else_is_refused(name):
    with pytest.raises(provision.StepRefused):
        provision.identifier(name, "role")


def test_rows_are_inserted_after_the_rows_they_reference():
    rows = [{"id": "translation", "translation_of_version_id": "original", "superseded_by_version_id": None},
            {"id": "old", "translation_of_version_id": None, "superseded_by_version_id": "new"},
            {"id": "original", "translation_of_version_id": None, "superseded_by_version_id": None},
            {"id": "new", "translation_of_version_id": None, "superseded_by_version_id": None},
            {"id": "outside", "translation_of_version_id": "not-copied", "superseded_by_version_id": None}]
    order = [r["id"] for r in provision.dependency_order(
        rows, "id", provision.SELF_REFERENCES["source_versions"])]
    assert order.index("original") < order.index("translation") and order.index("new") < order.index("old")
    assert sorted(order) == sorted(r["id"] for r in rows)


def test_a_reference_cycle_stops_the_copy():
    rows = [{"id": "a", "derived_from_passage_id": "b"}, {"id": "b", "derived_from_passage_id": "a"}]
    with pytest.raises(provision.StepRefused, match="cycle"):
        provision.dependency_order(rows, "id", ["derived_from_passage_id"])


def _column(name, nullable=True, default=False, generated=False):
    return {"name": name, "nullable": nullable, "has_default": default, "generated": generated, "type": "text"}


def test_only_shared_non_generated_columns_are_copied():
    target = [_column("id", nullable=False), _column("content", nullable=False),
              _column("search_vector", generated=True), _column("new_optional")]
    assert provision.column_plan("t", ["id", "content", "search_vector", "dropped"], target) == ["id", "content"]


def test_a_required_column_the_shared_rows_lack_stops_the_copy():
    target = [_column("id", nullable=False), _column("procedure", nullable=False)]
    with pytest.raises(provision.StepRefused, match="procedure"):
        provision.column_plan("source_passages", ["id"], target)


def test_provenance_users_are_collected_from_every_reference():
    rows = {"source_versions": [{"submitted_by": "u1", "approved_by": "u2"}, {"submitted_by": "u1",
                                                                                "approved_by": None}],
            "source_rights": [{"granted_by": "u3"}], "source_relationships": [{"created_by": None}]}
    assert provision.referenced_users(rows) == {"u1", "u2", "u3"}
