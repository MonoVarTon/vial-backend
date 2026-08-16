"""Vial — бэкенд мини-приложения."""
import logging
from fastapi import FastAPI
from app.middleware.auth import TelegramAuthMiddleware
from app import config

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Vial", description="AI-алхимия для NFT на TON")
app.add_middleware(TelegramAuthMiddleware, bot_token=config.BOT_TOKEN)


@app.get("/")
async def root():
    """Render стучится в корень для проверки живости — отвечаем, а не 404."""
    return {"service": "vial", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "ok", "network": config.TON_NETWORK}
