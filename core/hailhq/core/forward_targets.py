"""Forward-target verification: an address receives forwards only after it
proves it wants them.

Why: ``email_domains.forward_to`` used to accept any address. A tenant
could point a Hail inbox at a stranger, subscribe the inbox to newsletters,
and Hail relayed that mail under its own DKIM signature. One spam click at
the stranger's provider lands on the shared sender domain's reputation.

One ``email_forward_targets`` row per (organization, address):

* ``pending``  — a confirm link was sent, not yet clicked. Forwards skip it.
* ``verified`` — a verified member's login email (auto), or the link was
  clicked. Forwards flow.
* ``stopped``  — a spam complaint came back on a forward to it. Forwards
  skip it until the address re-confirms by link.

Rows are never deleted when an address leaves ``forward_to``: a stopped
address that is removed and re-added stays stopped.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from hailhq.core.db import org_lock
from hailhq.core.models import Email, EmailForwardTarget, OrganizationMember, User
from hailhq.core.system_email import SYSTEM_KIND_FORWARD_CONFIRM
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "MAX_CONFIRM_MAILS_PER_ADDRESS_PER_DAY",
    "MAX_CONFIRM_MAILS_PER_DAY",
    "MAX_PENDING_TARGETS",
    "RESEND_COOLDOWN",
    "TOKEN_TTL",
    "AlreadyVerified",
    "ConfirmBudgetExceeded",
    "IssuedToken",
    "PendingLimitExceeded",
    "ResendTooSoon",
    "confirm_target",
    "find_by_token",
    "list_targets",
    "member_emails",
    "normalize_address",
    "promote_verified_members",
    "reissue_token",
    "statuses_for",
    "stop_targets",
    "sync_targets",
    "verified_member_emails",
]

# A confirm link stays valid for a week; a re-save never re-issues one, so
# the tenant uses "resend" (cooldown below) if the first mail got lost.
TOKEN_TTL = timedelta(days=7)
RESEND_COOLDOWN = timedelta(minutes=10)

# Abuse caps, per organization. The 10-address cap on one forward_to list
# would otherwise be defeated by saving a fresh list of strangers on every
# PATCH: count the pending rows whose confirm link is still live (rows are
# never deleted, so an expired link must not block the org forever), and
# count the confirm mails actually queued in the last day (resends included).
# The per-org caps multiply with orgs (one account may own a few), so one
# recipient address is also capped across every org. An org's FIRST mail to
# an address always goes through — otherwise one org could mail an address
# three times and lock every other org out of it for a day. The cross-org
# cap bites on repeats (resends), so a flood costs one org per mail and the
# website caps orgs per account.
MAX_PENDING_TARGETS = 10
MAX_CONFIRM_MAILS_PER_DAY = 20
MAX_CONFIRM_MAILS_PER_ADDRESS_PER_DAY = 3
CONFIRM_WINDOW = timedelta(hours=24)


class AlreadyVerified(Exception):
    """Resend requested for an address that already receives forwards."""


class PendingLimitExceeded(Exception):
    """The org already has MAX_PENDING_TARGETS unconfirmed addresses."""


class ConfirmBudgetExceeded(Exception):
    """The org queued MAX_CONFIRM_MAILS_PER_DAY confirm mails in the last day
    (``scope == "org"``), or a repeat mail to one recipient would pass
    MAX_CONFIRM_MAILS_PER_ADDRESS_PER_DAY counted over every org
    (``scope == "address"``). ``str(exc)`` is safe to show the caller: it
    never says what other orgs did."""

    def __init__(self, scope: str, *, address: str | None = None) -> None:
        self.scope = scope
        self.address = address
        if scope == "address":
            msg = f"confirm mails to {address} are paused for today; try again tomorrow"
        else:
            msg = (
                f"confirm-mail limit reached ({MAX_CONFIRM_MAILS_PER_DAY} per day); "
                "try again tomorrow"
            )
        super().__init__(msg)


class ResendTooSoon(Exception):
    """Resend requested inside the cooldown window."""

    def __init__(self, retry_after: timedelta) -> None:
        super().__init__(f"retry after {retry_after}")
        self.retry_after = retry_after


@dataclass(frozen=True)
class IssuedToken:
    target: EmailForwardTarget
    raw_token: str


def normalize_address(address: str) -> str:
    return address.strip().lower()


def _hash(raw_token: str) -> str:
    return sha256(raw_token.encode("ascii")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _issue(target: EmailForwardTarget, now: datetime) -> str:
    raw = secrets.token_urlsafe(32)
    target.token_hash = _hash(raw)
    target.token_expires_at = now + TOKEN_TTL
    target.token_sent_at = now
    target.updated_at = now
    return raw


async def member_emails(
    db: AsyncSession,
    organization_id: UUID,
    *,
    verified: bool | None = None,
    roles: tuple[str, ...] | None = None,
) -> set[str]:
    """Login emails of the org's members. ``verified=True`` keeps only those
    better-auth has verified; ``None`` returns all."""
    stmt = (
        select(User.email)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(OrganizationMember.organization_id == organization_id)
    )
    if verified is not None:
        stmt = stmt.where(User.email_verified.is_(verified))
    if roles is not None:
        stmt = stmt.where(OrganizationMember.role.in_(roles))
    rows = (await db.execute(stmt)).scalars().all()
    return {normalize_address(e) for e in rows}


async def verified_member_emails(
    db: AsyncSession, organization_id: UUID, *, roles: tuple[str, ...] | None = None
) -> set[str]:
    """Login emails of the org's members whose email better-auth has verified."""
    return await member_emails(db, organization_id, verified=True, roles=roles)


async def promote_verified_members(db: AsyncSession, organization_id: UUID) -> int:
    """Flip pending rows to verified once their address is a verified member
    login. A password signup is signed in before clicking the account verify
    link; its "forward to me" row waits here (no confirm mail) and starts
    the moment the account is verified. Stopped rows are never promoted: a
    complaint stop ends only with a fresh link. One UPDATE; returns the count.
    The caller commits."""
    now = _now()
    verified_logins = (
        select(func.lower(func.trim(User.email)))
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(OrganizationMember.organization_id == organization_id)
        .where(User.email_verified.is_(True))
    )
    result = await db.execute(
        update(EmailForwardTarget)
        .where(EmailForwardTarget.organization_id == organization_id)
        .where(EmailForwardTarget.status == "pending")
        .where(EmailForwardTarget.address.in_(verified_logins))
        .values(
            status="verified",
            verified_at=now,
            token_hash=None,
            token_expires_at=None,
            updated_at=now,
        )
        .execution_options(synchronize_session="fetch")
    )
    return int(result.rowcount or 0)


async def _pending_count(db: AsyncSession, organization_id: UUID) -> int:
    """Pending rows whose confirm link can still be clicked."""
    stmt = (
        select(func.count())
        .select_from(EmailForwardTarget)
        .where(EmailForwardTarget.organization_id == organization_id)
        .where(EmailForwardTarget.status == "pending")
        .where(EmailForwardTarget.token_expires_at > _now())
    )
    return int((await db.execute(stmt)).scalar_one())


def _confirm_mails_last_day_stmt():
    return (
        select(func.count())
        .select_from(Email)
        .where(Email.direction == "outbound")
        .where(Email.metadata_["system_kind"].astext == SYSTEM_KIND_FORWARD_CONFIRM)
        .where(Email.created_at >= _now() - CONFIRM_WINDOW)
    )


async def _confirm_mails_last_day(db: AsyncSession, organization_id: UUID) -> int:
    stmt = _confirm_mails_last_day_stmt().where(
        Email.organization_id == organization_id
    )
    return int((await db.execute(stmt)).scalar_one())


async def _confirm_mails_to_address_last_day(
    db: AsyncSession, address: str, *, organization_id: UUID | None = None
) -> int:
    """Confirm mails queued to one recipient in the last day: every org, or
    only ``organization_id`` when given."""
    stmt = _confirm_mails_last_day_stmt().where(Email.to_addresses.any(address))
    if organization_id is not None:
        stmt = stmt.where(Email.organization_id == organization_id)
    return int((await db.execute(stmt)).scalar_one())


async def check_confirm_budget(
    db: AsyncSession, organization_id: UUID, *, addresses: list[str]
) -> None:
    """Raise :class:`ConfirmBudgetExceeded` when queueing one confirm mail to
    each of ``addresses`` would pass the org's daily cap, or when a repeat
    mail to one address would pass that address's cross-org daily cap. The
    org's first mail to an address today is never refused by the address
    cap. The org cap runs under the org lock; the address cap is best-effort
    across orgs (no cross-org lock), which is enough to stop a flood."""
    if not addresses:
        return
    sent = await _confirm_mails_last_day(db, organization_id)
    if sent + len(addresses) > MAX_CONFIRM_MAILS_PER_DAY:
        raise ConfirmBudgetExceeded("org")
    for address in addresses:
        own = await _confirm_mails_to_address_last_day(
            db, address, organization_id=organization_id
        )
        if own == 0:
            continue
        total = await _confirm_mails_to_address_last_day(db, address)
        if total + 1 > MAX_CONFIRM_MAILS_PER_ADDRESS_PER_DAY:
            raise ConfirmBudgetExceeded("address", address=address)


async def list_targets(
    db: AsyncSession, organization_id: UUID
) -> list[EmailForwardTarget]:
    await promote_verified_members(db, organization_id)
    stmt = (
        select(EmailForwardTarget)
        .where(EmailForwardTarget.organization_id == organization_id)
        .order_by(EmailForwardTarget.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def _rows_for(
    db: AsyncSession, organization_id: UUID, addresses: list[str]
) -> dict[str, EmailForwardTarget]:
    normalized = {normalize_address(a) for a in addresses}
    if not normalized:
        return {}
    stmt = (
        select(EmailForwardTarget)
        .where(EmailForwardTarget.organization_id == organization_id)
        .where(EmailForwardTarget.address.in_(normalized))
    )
    return {t.address: t for t in (await db.execute(stmt)).scalars().all()}


async def statuses_for(
    db: AsyncSession, organization_id: UUID, addresses: list[str]
) -> dict[str, str]:
    """``{normalized address: status}``. Addresses with no row are absent —
    callers treat that as not verified."""
    await promote_verified_members(db, organization_id)
    rows = await _rows_for(db, organization_id, addresses)
    return {addr: t.status for addr, t in rows.items()}


async def sync_targets(
    db: AsyncSession, organization_id: UUID, addresses: list[str]
) -> list[IssuedToken]:
    """Ensure one row per address. Returns the rows that got a fresh confirm
    token — only brand-new non-member addresses. An existing row (pending,
    verified or stopped) is never touched, so re-saving the same list sends
    no mail. Flushes, does not commit."""
    # Lock first (hailhq.core.db.org_lock, transaction-scoped): the console
    # saves one list to every domain row of the org in parallel, so two
    # requests with the same new address arrive together. The second one
    # waits here, then reads the first one's committed row and has nothing
    # new to do — no duplicate row, no second confirm mail. The same lock
    # serializes the count-then-insert cap checks below.
    await org_lock(db, organization_id)
    existing = await _rows_for(db, organization_id, addresses)
    wanted: list[str] = []
    for a in addresses:
        n = normalize_address(a)
        if n and n not in wanted:
            wanted.append(n)
    new = [a for a in wanted if a not in existing]
    if not new:
        return []
    members = await member_emails(db, organization_id, verified=True)
    # A member whose login email is not yet verified gets a pending row with
    # no confirm mail: the account verify click promotes it (see
    # promote_verified_members). One email for the signup, not two.
    unverified_members = await member_emails(db, organization_id, verified=False)
    strangers = [a for a in new if a not in members and a not in unverified_members]
    if strangers:
        # Caps apply before any row is written so a rejected save leaves
        # the org exactly as it was.
        if await _pending_count(db, organization_id) + len(strangers) > (
            MAX_PENDING_TARGETS
        ):
            raise PendingLimitExceeded(organization_id)
        await check_confirm_budget(db, organization_id, addresses=strangers)
    now = _now()
    issued: list[IssuedToken] = []
    for addr in new:
        target = EmailForwardTarget(
            organization_id=organization_id,
            address=addr,
            created_at=now,
            updated_at=now,
        )
        if addr in members:
            target.status = "verified"
            target.verified_at = now
            db.add(target)
            continue
        if addr in unverified_members:
            target.status = "pending"
            db.add(target)
            continue
        target.status = "pending"
        raw = _issue(target, now)
        db.add(target)
        issued.append(IssuedToken(target=target, raw_token=raw))
    await db.flush()
    return issued


async def reissue_token(db: AsyncSession, target: EmailForwardTarget) -> str:
    """New confirm token for a pending or stopped row. Raises
    :class:`AlreadyVerified` / :class:`ResendTooSoon` /
    :class:`ConfirmBudgetExceeded`."""
    # Lock before reading the row's timestamps: two resends arriving together
    # must not both pass the cooldown on the same stale token_sent_at.
    await org_lock(db, target.organization_id)
    await db.refresh(target)
    if target.status == "verified":
        raise AlreadyVerified(target.address)
    now = _now()
    if target.token_sent_at is not None:
        elapsed = now - target.token_sent_at
        if elapsed < RESEND_COOLDOWN:
            raise ResendTooSoon(RESEND_COOLDOWN - elapsed)
    await check_confirm_budget(db, target.organization_id, addresses=[target.address])
    raw = _issue(target, now)
    await db.flush()
    return raw


async def find_by_token(db: AsyncSession, raw_token: str) -> EmailForwardTarget | None:
    """The row this token confirms, or None when unknown, expired or already
    verified. Lookup is by hash; the raw token is never stored."""
    if not raw_token:
        return None
    stmt = select(EmailForwardTarget).where(
        EmailForwardTarget.token_hash == _hash(raw_token)
    )
    target = (await db.execute(stmt)).scalar_one_or_none()
    if target is None or target.status == "verified":
        return None
    if target.token_expires_at is None or target.token_expires_at < _now():
        return None
    return target


async def confirm_target(db: AsyncSession, target: EmailForwardTarget) -> None:
    """Mark verified and drop the token. Clears a prior stop. Flushes."""
    now = _now()
    target.status = "verified"
    target.verified_at = now
    target.token_hash = None
    target.token_expires_at = None
    target.stopped_at = None
    target.stopped_reason = None
    target.stopped_email_id = None
    target.updated_at = now
    await db.flush()


async def stop_targets(
    db: AsyncSession,
    organization_id: UUID,
    addresses: list[str],
    *,
    reason: str,
    email_id: UUID | None,
) -> list[EmailForwardTarget]:
    """Set ``stopped`` on each address. A missing row is created stopped so
    the console can show why forwards no longer fire. Flushes."""
    existing = await _rows_for(db, organization_id, addresses)
    now = _now()
    stopped: list[EmailForwardTarget] = []
    seen: set[str] = set()
    for a in addresses:
        addr = normalize_address(a)
        if not addr or addr in seen:
            continue
        seen.add(addr)
        target = existing.get(addr)
        if target is None:
            target = EmailForwardTarget(
                organization_id=organization_id, address=addr, created_at=now
            )
            db.add(target)
        target.status = "stopped"
        target.stopped_at = now
        target.stopped_reason = reason
        target.stopped_email_id = email_id
        target.token_hash = None
        target.token_expires_at = None
        target.updated_at = now
        stopped.append(target)
    await db.flush()
    return stopped
