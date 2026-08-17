"""
Vial — точки доступа для мини-приложения.

Три штуки:
  GET  /tonconnect-manifest.json  — кошелёк читает его перед подключением
  GET  /api/nfts                  — список NFT человека с оценкой
  POST /api/burn/prepare          — собрать транзакцию на подпись

Проверку Telegram делает middleware, здесь её дублировать не нужно.
Манифест — единственное исключение, он публичный (кошелёк читает его
до всякой авторизации).
"""
import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from app import config
from app.services import ton_api, burn_tx
from app.services.compositor import extract_palette

logger = logging.getLogger("vial.routes")
router = APIRouter()


class BurnRequest(BaseModel):
    owner: str = Field(min_length=48, max_length=68)
    nfts: list[str] = Field(min_length=2, max_length=4)


@router.get("/tonconnect-manifest.json")
async def manifest():
    """Кошелёк показывает эти данные человеку, когда спрашивает разрешение."""
    return {
        "url": "https://t.me/getvial_bot/alchemy",
        "name": "Vial",
        "iconUrl": "https://vial-backend.onrender.com/static/icon.png",
        "termsOfUseUrl": "https://t.me/getvial_bot",
        "privacyPolicyUrl": "https://t.me/getvial_bot",
    }


@router.get("/api/nfts")
async def list_nfts(address: str = Query(min_length=48, max_length=68)):
    """
    NFT человека, годные для сжигания. К каждой добавляем оценку ценности
    и главный цвет — фронтенд по ним рисует наполнение флакона.
    """
    try:
        items = ton_api.fetch_wallet_nfts(address)
    except Exception as e:
        logger.error(f"Не получили NFT: {e}")
        raise HTTPException(status_code=502, detail="Блокчейн не отвечает, попробуйте позже")

    # статистику по коллекции запрашиваем один раз на коллекцию, не на каждую NFT
    stats_cache: dict[str, dict] = {}
    result = []

    for nft in items:
        coll = nft.get("collection_address", "")
        if coll not in stats_cache:
            stats_cache[coll] = ton_api.fetch_collection_stats(coll)
        stats = stats_cache[coll]

        ok, reason = ton_api.is_eligible(nft, stats)
        if not ok:
            continue

        nft["score"] = ton_api.score_item(nft, stats)
        nft["floor"] = round(stats.get("floor", 0.0), 2)
        nft["color"] = _dominant_color(nft.get("image", ""))
        nft.pop("collection_address", None)
        result.append(nft)

    result.sort(key=lambda x: x["score"], reverse=True)
    return {"items": result, "count": len(result)}


def _dominant_color(image_url: str) -> list[int]:
    """
    Главный цвет картинки — для предпросмотра во флаконе.
    Если картинка не скачалась, отдаём цвета бренда: пусть предпросмотр
    будет неточным, но интерфейс не поедет.
    """
    if not image_url:
        return [127, 168, 156]
    try:
        import requests
        r = requests.get(image_url, timeout=6)
        r.raise_for_status()
        palette = extract_palette(r.content, colors=2)
        return list(palette[0])
    except Exception:
        return [127, 168, 156]


@router.post("/api/burn/prepare")
async def prepare_burn(req: BurnRequest):
    """
    Собирает транзакцию на подпись. Сама транзакция ничего не сжигает
    до того, как человек подпишет её в кошельке — здесь только подготовка.
    """
    if not config.VAULT_CONTRACT_ADDRESS:
        raise HTTPException(status_code=503, detail="Контракты ещё не развёрнуты")

    try:
        plan = burn_tx.build_burn_transaction(req.owner, req.nfts)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Не собрали транзакцию: {e}")
        raise HTTPException(status_code=500, detail="Не удалось собрать транзакцию")

    return plan
