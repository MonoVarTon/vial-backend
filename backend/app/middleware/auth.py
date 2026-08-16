"""
Vial backend — проверка подписи Telegram Mini App.

Ядро проверки (HMAC-SHA256) взято из ai-sticker-factory — там оно было
написано правильно, дословно совпадает с документацией Telegram.

ИСПРАВЛЕНО по сравнению с оригиналом: в старом whitelist пути "/generate"
и "/nft" были открыты для всех без проверки подписи — то есть ровно там,
где у нас происходит минт, охраны не было вообще. Список ниже — по-другому:
открыто только то, что объективно должно быть публичным (health-check,
tonconnect-manifest, статика). Всё остальное, включая любые пути минта/
сжигания — только с валидной подписью Telegram.
"""
import os
import hmac
import hashlib
import json
import logging
from urllib.parse import unquote
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("vial.auth")

# Единственные пути, которым разрешено работать без подписи Telegram.
# Сознательно короткий список — по умолчанию всё закрыто, открываем только
# то, что реально должно быть публичным.
PUBLIC_PATHS = ("/", "/health", "/tonconnect-manifest.json")
PUBLIC_PREFIXES = ("/static",)


def validate_telegram_init_data(init_data_raw: str, bot_token: str) -> dict:
    """
    Проверяет подпись initData от Telegram Mini App.
    Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    try:
        if not init_data_raw:
            return {"valid": False, "user": None, "reason": "empty init_data"}

        parsed = dict(
            pair.split("=", 1)
            for pair in unquote(init_data_raw).split("&")
            if "=" in pair
        )

        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return {"valid": False, "user": None, "reason": "no hash in init_data"}

        check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

        if computed_hash == received_hash:
            user_data = json.loads(parsed.get("user", "{}"))
            return {"valid": True, "user": user_data, "reason": "ok"}
        else:
            return {"valid": False, "user": None, "reason": "hash mismatch"}
    except Exception as e:
        return {"valid": False, "user": None, "reason": f"parse error: {e}"}


class TelegramAuthMiddleware(BaseHTTPMiddleware):
    """
    По умолчанию закрыто. Список открытых путей — короткий и явный,
    см. PUBLIC_PATHS/PUBLIC_PREFIXES выше. Новый публичный путь нужно
    добавлять туда осознанно, а не полагаться на широкий префикс вроде "/nft".
    """
    def __init__(self, app, bot_token: str):
        super().__init__(app)
        self.bot_token = bot_token

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if os.getenv("DEBUG", "false").lower() == "true" and path in ("/docs", "/openapi.json"):
            return await call_next(request)

        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        init_data = request.headers.get("X-Telegram-Init-Data", "") or request.query_params.get("initData", "")

        if not init_data:
            logger.warning(f"Отклонён запрос без initData | path={path}")
            return JSONResponse(
                status_code=401,
                content={"status": "error", "message": "Откройте приложение из Telegram."},
            )

        result = validate_telegram_init_data(init_data, self.bot_token)
        if not result["valid"]:
            logger.warning(f"Отклонён запрос с неверной подписью ({result['reason']}) | path={path}")
            return JSONResponse(
                status_code=401,
                content={"status": "error", "message": f"Неверная авторизация Telegram: {result['reason']}"},
            )

        request.state.telegram_user = result["user"]
        return await call_next(request)
