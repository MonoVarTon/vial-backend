"""Vial — бэкенд мини-приложения."""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.middleware.auth import TelegramAuthMiddleware
from app.routes import alchemy
from app import config

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Vial", description="AI-алхимия для NFT на TON")

app.add_middleware(TelegramAuthMiddleware, bot_token=config.BOT_TOKEN)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://t.me", "https://web.telegram.org"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)

app.include_router(alchemy.router)


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
