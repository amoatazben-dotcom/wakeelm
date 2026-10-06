import json

from cryptography.fernet import Fernet


class SecretManager:
    def __init__(self, key: str):
        self._cipher = Fernet(key.encode())

    def encrypt(self, value: str) -> str:
        return self._cipher.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self._cipher.decrypt(value.encode()).decode()

    def encrypt_headers(self, value: dict[str, str]) -> str:
        return self.encrypt(json.dumps(value))


def token_hint(value: str) -> str:
    return "***" if len(value) < 8 else "***…" + value[-4:]
