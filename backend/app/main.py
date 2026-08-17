"""Vial — бэкенд мини-приложения."""
import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.middleware.auth import TelegramAuthMiddleware
from app.routes import alchemy
from app import config

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Vial", description="AI-алхимия для NFT на TON")

app.add_middleware(TelegramAuthMiddleware, bot_token=config.BOT_TOKEN)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://t.me",
        "https://web.telegram.org",
        "https://vial-app.onrender.com",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)

app.include_router(alchemy.router)

# Иконка для кошелька. Путь /static открыт без подписи Telegram —
# кошелёк читает манифест и иконку до всякой авторизации.
_static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
else:
    logging.warning("Папка static не найдена — иконка кошелька отдаст 404")


@app.get("/")
async def root():
    return {"service": "vial", "status": "running"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "network": config.TON_NETWORK,
        "contracts_ready": bool(config.VAULT_CONTRACT_ADDRESS),
    }
