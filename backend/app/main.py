"""Vial backend — минимальный каркас, проверка что всё собирается вместе."""
from fastapi import FastAPI
from app.middleware.auth import TelegramAuthMiddleware
from app import config

app = FastAPI(title="Vial")
app.add_middleware(TelegramAuthMiddleware, bot_token=config.BOT_TOKEN)


@app.get("/health")
async def health():
    return {"status": "ok"}
