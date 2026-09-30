from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import UserResponse
from app.auth.security import (
    generate_token,
    hash_password_async,
    hash_token,
    verify_dummy_password_async,
    verify_password_async,
)
from app.models.auth import AuthAccount, AuthSession, OAuthConnection, PasswordResetToken
from app.models.user import User


class EmailAlreadyExistsError(ValueError):
    """Raised when a user tries to register an email already in use."""


class InvalidResetTokenError(ValueError):
    """Raised when a password reset token is invalid, expired, or already used."""


@dataclass(frozen=True)
class SessionPair:
    raw_token: str
    session: AuthSession


@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    session: AuthSession


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified_at is not None,
        is_active=user.is_active,
        created_at=user.created_at,
    )


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create_password_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str | None,
) -> User:
    normalized_email = normalize_email(email)
    password_hash = await hash_password_async(password)
    user = User(
        email=normalized_email,
        display_name=display_name.strip() if display_name else None,
        is_active=True,
    )
    db.add(user)

    try:
        await db.flush()
        db.add(
            AuthAccount(
                user_id=user.id,
                provider="password",
                provider_account_id=str(user.id),
                password_hash=password_hash,
            )
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise EmailAlreadyExistsError("An account already exists for this email.") from exc

    await db.refresh(user)
    return user


async def authenticate_password(
    db: AsyncSession,
    *,
    email: str,
    password: str,
) -> User | None:
    normalized_email = normalize_email(email)
    result = await db.execute(select(User).where(User.email == normalized_email))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        await verify_dummy_password_async(password)
        return None

    account_result = await db.execute(
        select(AuthAccount).where(
            AuthAccount.user_id == user.id,
            AuthAccount.provider == "password",
        )
    )
    account = account_result.scalar_one_or_none()
    if account is None or not account.password_hash:
        await verify_dummy_password_async(password)
        return None
    if not await verify_password_async(account.password_hash, password):
        return None

    user.last_login_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user)
    return user


async def create_session(
    db: AsyncSession,
    *,
    user: User,
    user_agent: str | None,
    ip_address: str | None,
    ttl_days: int,
) -> SessionPair:
    raw_token = generate_token()
    now = datetime.now(UTC)
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=now + timedelta(days=ttl_days),
        last_seen_at=now,
        user_agent=user_agent[:512] if user_agent else None,
        ip_address=ip_address[:64] if ip_address else None,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return SessionPair(raw_token=raw_token, session=session)


async def get_authenticated_session(
    db: AsyncSession,
    *,
    raw_token: str,
) -> AuthenticatedSession | None:
    now = datetime.now(UTC)
    result = await db.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.token_hash == hash_token(raw_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
            User.is_active.is_(True),
        )
    )
    row = result.first()
    if row is None:
        return None

    session, user = row
    if session.last_seen_at is None or session.last_seen_at < now - timedelta(minutes=5):
        session.last_seen_at = now
        await db.commit()

    return AuthenticatedSession(user=user, session=session)


async def revoke_session(db: AsyncSession, *, raw_token: str) -> None:
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.token_hash == hash_token(raw_token),
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


async def revoke_user_sessions(db: AsyncSession, *, user_id: UUID) -> None:
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


async def list_user_sessions(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> list[AuthSession]:
    result = await db.execute(
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
        )
        .order_by(AuthSession.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_user_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    session_id: UUID,
) -> bool:
    result = await db.execute(
        update(AuthSession)
        .where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()
    return result.rowcount == 1


async def create_password_reset_token(
    db: AsyncSession,
    *,
    email: str,
    ttl_minutes: int = 30,
) -> str | None:
    result = await db.execute(
        select(User)
        .where(User.email == normalize_email(email))
        .with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None

    now = datetime.now(UTC)
    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    raw_token = generate_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=now + timedelta(minutes=ttl_minutes),
        )
    )
    await db.commit()
    return raw_token


async def reset_password(
    db: AsyncSession,
    *,
    raw_token: str,
    new_password: str,
) -> User:
    now = datetime.now(UTC)
    result = await db.execute(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == hash_token(raw_token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .with_for_update()
    )
    reset_token = result.scalar_one_or_none()
    if reset_token is None:
        raise InvalidResetTokenError("Password reset token is invalid or expired.")

    user_result = await db.execute(select(User).where(User.id == reset_token.user_id))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise InvalidResetTokenError("Password reset token is invalid or expired.")

    account_result = await db.execute(
        select(AuthAccount).where(
            AuthAccount.user_id == user.id,
            AuthAccount.provider == "password",
        )
    )
    account = account_result.scalar_one_or_none()
    if account is None:
        account = AuthAccount(
            user_id=user.id,
            provider="password",
            provider_account_id=str(user.id),
        )
        db.add(account)
    account.password_hash = await hash_password_async(new_password)
    reset_token.used_at = now
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await db.commit()
    await db.refresh(user)
    return user


async def get_or_create_google_user(
    db: AsyncSession,
    *,
    provider_account_id: str,
    email: str,
    display_name: str | None,
    email_verified: bool,
    scopes: list[str],
    provider_metadata: dict[str, object] | None = None,
) -> User | None:
    if not email_verified:
        return None

    normalized_email = normalize_email(email)
    account_result = await db.execute(
        select(AuthAccount).where(
            AuthAccount.provider == "google",
            AuthAccount.provider_account_id == provider_account_id,
        )
    )
    account = account_result.scalar_one_or_none()
    if account is not None:
        user_result = await db.execute(select(User).where(User.id == account.user_id))
        user = user_result.scalar_one_or_none()
        if user is None or not user.is_active:
            return None
    else:
        user_result = await db.execute(select(User).where(User.email == normalized_email))
        user = user_result.scalar_one_or_none()
        if user is None:
            user = User(
                email=normalized_email,
                display_name=display_name,
                is_active=True,
                email_verified_at=datetime.now(UTC),
            )
            db.add(user)
            await db.flush()
        elif not user.email_verified_at:
            user.email_verified_at = datetime.now(UTC)

        account = AuthAccount(
            user_id=user.id,
            provider="google",
            provider_account_id=provider_account_id,
        )
        db.add(account)

    connection_result = await db.execute(
        select(OAuthConnection).where(
            OAuthConnection.provider == "google",
            OAuthConnection.provider_account_id == provider_account_id,
        )
    )
    connection = connection_result.scalar_one_or_none()
    if connection is not None and connection.user_id != user.id:
        return None
    if connection is None:
        connection = OAuthConnection(
            user_id=user.id,
            provider="google",
            provider_account_id=provider_account_id,
        )
        db.add(connection)
    connection.email = normalized_email
    connection.scopes = scopes
    connection.provider_metadata = provider_metadata or {}
    user.last_login_at = datetime.now(UTC)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return None
    await db.refresh(user)
    return user
