"""Symmetric secret box (Fernet) for secrets stored at rest."""

from cryptography.fernet import Fernet, InvalidToken


class SecretBoxError(ValueError):
    """Raised on a bad key or a tampered / wrong-key token."""


class SecretBox:
    def __init__(self, key: bytes) -> None:
        try:
            self._fernet = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise SecretBoxError("invalid secret box key") from exc

    def seal(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def open(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except (InvalidToken, UnicodeError) as exc:
            raise SecretBoxError("token is invalid, tampered or sealed with another key") from exc
