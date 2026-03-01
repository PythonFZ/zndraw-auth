"""CLI login (device-code flow) router."""

import logging
import secrets
import string
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from zndraw_auth.db import CLILoginChallenge, SessionDep
from zndraw_auth.schemas import CLILoginCreateResponse, CLILoginStatusResponse

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


@cli_login_router.get("/{code}", response_model=CLILoginStatusResponse)
async def poll_cli_login_challenge(
    code: str,
    secret: str = Query(...),
    *,
    session: SessionDep,
) -> CLILoginStatusResponse:
    """Poll a CLI login challenge status."""
    now = datetime.now(UTC).replace(tzinfo=None)

    result = await session.execute(
        select(CLILoginChallenge).where(CLILoginChallenge.code == code)
    )
    challenge = result.scalar_one_or_none()

    if challenge is None or challenge.secret != secret:
        raise HTTPException(status_code=404, detail="Challenge not found")

    if now > challenge.expires_at:
        raise HTTPException(status_code=410, detail="Challenge expired")

    if challenge.status == "redeemed":
        raise HTTPException(status_code=404, detail="Challenge not found")

    if challenge.status == "approved" and challenge.token is not None:
        token = challenge.token
        challenge.token = None
        challenge.secret = None
        challenge.status = "redeemed"
        await session.commit()
        return CLILoginStatusResponse(status="approved", token=token)

    return CLILoginStatusResponse(status="pending")
