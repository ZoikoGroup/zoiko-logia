"""Start the isolated manual-test backend, or refuse to.

    python scripts/run_manual_test_server.py --test-env PATH --shared-env PATH [--port 8011] [--check]

--test-env    the test settings (template: manual-test.env.example). Never a
              file named .env: config.py would load it for every server.
--shared-env  the developer's normal backend/.env. Read for keys (Groq,
              Supabase public URL, connectors) and to know what is shared;
              its databases, caches, service-role key and email key are
              replaced or removed in this process only. The file is not changed.
--check       validate the configuration, then read the marker through every
              database connection the app would use (SELECTs only), and stop.
--reset-questions
              set the session's question count to 0 (tokens and limits kept)
              and stop; refused while a server holds the session lock.

Startup is refused, before any application module is imported, when the test
database or cache is missing or is the shared one (app/core/manual_test_server.py).
The server then verifies the database marker itself before it serves or
samples anything, and enforces the session's question and token limits; the
counts are kept in --state-file (default: next to the test env file).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _verify_marker() -> None:
    from app.core import manual_test_server
    from app.core.config import get_settings
    from app.core.database import async_engine, engine, request_engine

    async def run():
        try:
            await manual_test_server.verify_database(
                get_settings().MANUAL_TEST_DATABASE_MARKER, admin_engine=async_engine,
                request_engine=request_engine, sync_engine=engine)
        finally:
            await async_engine.dispose()
            await request_engine.dispose()
    asyncio.run(run())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test-env", type=Path, required=True)
    parser.add_argument("--shared-env", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--reset-questions", action="store_true",
                        help="set the session's question count to 0 (tokens and limits kept) and exit; "
                             "refused while a server holds the session")
    args = parser.parse_args(argv)

    from dotenv import dotenv_values
    from app.core.manual_test_server import (
        ManualTestBlocked, SessionLimits, add_question_limit, build_environment, describe_database,
    )
    from app.domains.model_gateway.session_meter import install_groq_meter

    try:
        if args.test_env.name == ".env":
            raise ManualTestBlocked(["the test env file must not be named .env"])
        for path in (args.test_env, args.shared_env):
            if not path.is_file():
                raise ManualTestBlocked([f"{path} does not exist"])
        env = build_environment(dotenv_values(args.test_env), dotenv_values(args.shared_env))
        state_file = args.state_file or args.test_env.with_name(args.test_env.name + ".state.json")
        limits = SessionLimits(int(env["MANUAL_TEST_MAX_QUESTIONS"]), int(env["MANUAL_TEST_MAX_TOTAL_TOKENS"]),
                               default_completion=int(env["AGENT_MAX_COMPLETION_TOKENS"]), state_file=state_file)
    except ManualTestBlocked as blocked:
        print("Manual test server NOT started:", *[f"  - {reason}" for reason in blocked.reasons], sep="\n")
        return 2

    if args.reset_questions:
        before = limits.summary()
        limits.reset_questions()
        print(f"Session questions reset: {before} -> {limits.summary()} (state: {state_file})")
        limits.close()
        return 0

    # Only now, with a validated environment, may application code load.
    os.environ.update(env)
    os.chdir(BACKEND)
    print(f"Test database: {describe_database(env['DATABASE_URL'])}; "
          f"requests as {describe_database(env['APP_DATABASE_URL']).rsplit(' as ', 1)[1]}")
    print(f"Session: {limits.summary()} (state: {state_file})")
    try:
        _verify_marker()
    except ManualTestBlocked as blocked:
        print("Manual test server NOT started:", *[f"  - {reason}" for reason in blocked.reasons], sep="\n")
        return 2
    print("Test database verified (marker readable on every connection; request role subject to RLS).")
    if args.check:
        return 0

    install_groq_meter(limits)
    from app.main import app
    add_question_limit(app, limits)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
