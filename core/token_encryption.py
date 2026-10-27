"""Encryption helpers for OAuth tokens stored in the database."""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.types import Text, TypeDecorator

from core.config import settings


TOKEN_CIPHER_PREFIX = "fernet:"


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
	key = settings.TOKEN_ENCRYPTION_KEY
	if not key:
		raise RuntimeError(
			"TOKEN_ENCRYPTION_KEY must be set to a valid Fernet key"
		)
	try:
		return Fernet(key.encode("ascii"))
	except (ValueError, UnicodeEncodeError) as error:
		raise RuntimeError("TOKEN_ENCRYPTION_KEY is not a valid Fernet key") from error


def encrypt_token(value: str) -> str:
	"""Encrypt one token for storage without logging or exposing its contents."""
	return TOKEN_CIPHER_PREFIX + _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


class EncryptedToken(TypeDecorator[str]):
	"""Encrypt OAuth token values on write and decrypt them on database reads."""

	impl = Text
	cache_ok = True

	def process_bind_param(self, value: str | None, dialect) -> str | None:
		if value is None:
			return None
		return encrypt_token(value)

	def process_result_value(self, value: str | None, dialect) -> str | None:
		if value is None or not value.startswith(TOKEN_CIPHER_PREFIX):
			# Plaintext is accepted only to support the one-time legacy migration.
			return value
		try:
			encrypted_value = value[len(TOKEN_CIPHER_PREFIX) :].encode("ascii")
			return _get_fernet().decrypt(encrypted_value).decode("utf-8")
		except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as error:
			raise RuntimeError(
				"Stored OAuth token cannot be decrypted; verify TOKEN_ENCRYPTION_KEY"
			) from error


def encrypt_legacy_oauth_tokens(engine: Engine) -> int:
	"""Encrypt existing plaintext OAuth tokens once, before serving requests."""
	fernet = _get_fernet()
	updated_rows = 0
	with engine.begin() as connection:
		rows = connection.execute(
			text(
				"SELECT oauth_id, access_token, refresh_token "
				"FROM user_oauth"
			)
		).mappings()
		for row in rows:
			updates = {}
			for field in ("access_token", "refresh_token"):
				value = row[field]
				if value and not value.startswith(TOKEN_CIPHER_PREFIX):
					updates[field] = (
						TOKEN_CIPHER_PREFIX
						+ fernet.encrypt(value.encode("utf-8")).decode("ascii")
					)
			if updates:
				assignments = ", ".join(f"{field} = :{field}" for field in updates)
				connection.execute(
					text(
						f"UPDATE user_oauth SET {assignments} "
						"WHERE oauth_id = :oauth_id"
					),
					{"oauth_id": row["oauth_id"], **updates},
				)
				updated_rows += 1
	return updated_rows
