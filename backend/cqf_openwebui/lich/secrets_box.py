"""Application passwords are stored encrypted with the service key (Fernet)."""

from cryptography.fernet import Fernet, InvalidToken

from . import config


def _box() -> Fernet:
    if not config.SECRET_KEY:
        raise RuntimeError("LICH_SECRET_KEY is not set")
    return Fernet(config.SECRET_KEY.encode())


def seal(value: str) -> str:
    return _box().encrypt(value.encode()).decode()


def open_secret(value: str) -> str:
    try:
        return _box().decrypt(value.encode()).decode()
    except InvalidToken as error:
        raise RuntimeError("Không giải mã được application password; nhập lại trong Cài đặt.") from error
