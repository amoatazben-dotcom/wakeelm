import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class SecretManager:
    def __init__(self, key: str, previous_keys=()):
        self._key_material = (key, *previous_keys)
        self.key_id = hashlib.sha256(key.encode()).hexdigest()[:12]
        self._cipher = Fernet(key.encode())
        self._keys = {
            hashlib.sha256(k.encode()).hexdigest()[:12]: Fernet(k.encode())
            for k in [key, *previous_keys]
        }
        self._legacy = MultiFernet(list(self._keys.values()))

    def encrypt(self, value: str) -> str:
        return "enc:v1:" + self.key_id + ":" + self._cipher.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        if value.startswith("enc:"):
            parts = value.split(":", 3)
            if len(parts) != 4 or parts[1] != "v1" or parts[2] not in self._keys:
                raise InvalidToken()
            return self._keys[parts[2]].decrypt(parts[3].encode()).decode()
        return self._legacy.decrypt(value.encode()).decode()

    def encrypt_headers(self, value: dict[str, str]) -> str:
        return self.encrypt(json.dumps(value))


def token_hint(value: str) -> str:
    return "***" if len(value) < 8 else "***…" + value[-4:]
