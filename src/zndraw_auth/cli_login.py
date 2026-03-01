"""CLI login (device-code flow) router."""

import logging
import secrets
import string
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter

from zndraw_auth.db import CLILoginChallenge, SessionDep
from zndraw_auth.schemas import CLILoginCreateResponse

log = logging.getLogger(__name__)

cli_login_router = APIRouter()

CHALLENGE_LIFETIME_SECONDS = 300  # 5 minutes
CODE_LENGTH = 8
CODE_ALPHABET = string.ascii_uppercase + string.digits


def _generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


@cli_login_router.post("", response_model=CLILoginCreateResponse)
async def create_cli_login_challenge(
    session: SessionDep,
) -> CLILoginCreateResponse:
    """Create a CLI login challenge (no auth required)."""
    now = datetime.now(UTC)
    code = _generate_code()
    secret = secrets.token_urlsafe(32)

    challenge = CLILoginChallenge(
        code=code,
        secret=secret,
        status="pending",
        created_at=now,
        expires_at=now + timedelta(seconds=CHALLENGE_LIFETIME_SECONDS),
    )
    session.add(challenge)
    await session.commit()

    return CLILoginCreateResponse(
        code=code,
        secret=secret,
        approve_url=f"/auth/cli-login/{code}",
    )
