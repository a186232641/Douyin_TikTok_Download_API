import hmac
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


ROOT_DIR = Path(__file__).resolve().parent.parent
ROOT_CONFIG_PATH = ROOT_DIR / "config.yaml"
DOUYIN_CONFIG_PATH = ROOT_DIR / "crawlers" / "douyin" / "web" / "config.yaml"
RUNTIME_CONFIG_PATH = ROOT_DIR / "var" / "runtime_config.json"
MAX_COOKIE_LENGTH = 65536

_CONFIG_LOCK = threading.RLock()


class RuntimeConfigError(RuntimeError):
    pass


def _read_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _read_runtime_config() -> Dict[str, Any]:
    try:
        with RUNTIME_CONFIG_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise RuntimeConfigError("Runtime configuration file is invalid.") from exc

    if not isinstance(data, dict):
        raise RuntimeConfigError("Runtime configuration must be a JSON object.")
    return data


def _write_runtime_config(data: Dict[str, Any]) -> None:
    RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(RUNTIME_CONFIG_PATH.parent),
            prefix=f".{RUNTIME_CONFIG_PATH.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(data, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, RUNTIME_CONFIG_PATH)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def _runtime_douyin_cookie() -> Optional[str]:
    with _CONFIG_LOCK:
        data = _read_runtime_config()
    douyin = data.get("douyin", {})
    if not isinstance(douyin, dict):
        raise RuntimeConfigError("Runtime Douyin configuration must be a JSON object.")
    cookie = douyin.get("cookie")
    return cookie if isinstance(cookie, str) and cookie else None


def _fallback_douyin_cookie() -> Optional[str]:
    data = _read_yaml(DOUYIN_CONFIG_PATH)
    token_manager = data.get("TokenManager", {})
    douyin = token_manager.get("douyin", {}) if isinstance(token_manager, dict) else {}
    headers = douyin.get("headers", {}) if isinstance(douyin, dict) else {}
    cookie = headers.get("Cookie") if isinstance(headers, dict) else None
    return cookie if isinstance(cookie, str) and cookie else None


def get_douyin_cookie() -> str:
    return _runtime_douyin_cookie() or _fallback_douyin_cookie() or ""


def set_douyin_cookie(cookie: str) -> Dict[str, Any]:
    if not isinstance(cookie, str):
        raise ValueError("Cookie must be a string.")

    cookie = cookie.strip()
    if not cookie:
        raise ValueError("Cookie cannot be empty.")
    if len(cookie) > MAX_COOKIE_LENGTH:
        raise ValueError(f"Cookie cannot exceed {MAX_COOKIE_LENGTH} characters.")
    if "\r" in cookie or "\n" in cookie:
        raise ValueError("Cookie cannot contain line breaks.")

    with _CONFIG_LOCK:
        data = _read_runtime_config()
        douyin = data.setdefault("douyin", {})
        if not isinstance(douyin, dict):
            douyin = {}
            data["douyin"] = douyin
        douyin["cookie"] = cookie
        _write_runtime_config(data)

    return get_douyin_cookie_status()


def clear_douyin_cookie() -> Dict[str, Any]:
    with _CONFIG_LOCK:
        data = _read_runtime_config()
        douyin = data.get("douyin")
        if isinstance(douyin, dict):
            douyin.pop("cookie", None)
            if not douyin:
                data.pop("douyin", None)
        _write_runtime_config(data)

    return get_douyin_cookie_status()


def _mask_cookie(cookie: str) -> str:
    if not cookie:
        return ""
    if len(cookie) <= 8:
        return "*" * len(cookie)
    return f"{cookie[:4]}...{cookie[-4:]}"


def get_douyin_cookie_status() -> Dict[str, Any]:
    runtime_cookie = _runtime_douyin_cookie()
    fallback_cookie = _fallback_douyin_cookie()
    cookie = runtime_cookie or fallback_cookie or ""

    if runtime_cookie:
        source = "runtime"
    elif fallback_cookie:
        source = "yaml"
    else:
        source = "none"

    return {
        "configured": bool(cookie),
        "source": source,
        "runtime_override": bool(runtime_cookie),
        "length": len(cookie),
        "masked_preview": _mask_cookie(cookie),
    }


def get_access_password() -> Optional[str]:
    environment_password = os.getenv("WEB_ACCESS_PASSWORD")
    if environment_password is not None:
        return environment_password or None

    data = _read_yaml(ROOT_CONFIG_PATH)
    web = data.get("Web", {})
    if not isinstance(web, dict):
        return None
    password = web.get("Access_Password")
    if password is None:
        return None

    password = str(password)
    return password or None


def is_access_password_configured() -> bool:
    return get_access_password() is not None


def verify_access_password(candidate: Optional[str]) -> bool:
    configured_password = get_access_password()
    if configured_password is None or candidate is None:
        return False
    return hmac.compare_digest(configured_password, candidate)
