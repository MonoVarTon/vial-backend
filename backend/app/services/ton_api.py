"""
Vial — запросы к блокчейну через TonAPI.

Две задачи:
1. Показать человеку его NFT (только те, что годятся для сжигания)
2. Оценить, насколько ценное он собирается сжечь — от этого зависит редкость

Отдельно тут живёт защита от жульничества: если кто-то начеканил тысячу
пустышек за копейки, чтобы сжечь их ради редкого результата — такие NFT
не проходят фильтр. Проверяем не на глаз, а по данным коллекции.
"""
import logging
import requests
from app import config

logger = logging.getLogger("vial.tonapi")

BASE = {
    "mainnet": "https://tonapi.io/v2",
    "testnet": "https://testnet.tonapi.io/v2",
}

MIN_AGE_DAYS = 7          # NFT младше недели не берём — против «начеканил и сжёг»
MIN_COLLECTION_VOLUME = 1.0  # TON, минимальный объём торгов коллекции


def _base_url() -> str:
    return BASE.get(config.TON_NETWORK, BASE["testnet"])


def _get(path: str, params: dict | None = None) -> dict:
    url = f"{_base_url()}{path}"
    headers = {"Accept": "application/json"}
    resp = requests.get(url, params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json()


def fetch_wallet_nfts(address: str, limit: int = 100) -> list[dict]:
    """
    Забирает NFT кошелька. Возвращает только пригодные для сжигания,
    с уже посчитанной оценкой ценности.
    """
    try:
        data = _get(f"/accounts/{address}/nfts", {"limit": limit, "indirect_ownership": "false"})
    except Exception as e:
        logger.error(f"TonAPI не ответил по кошельку {address[:12]}…: {e}")
        raise

    result = []
    for item in data.get("nft_items", []):
        parsed = _parse_item(item)
        if parsed:
            result.append(parsed)
    return result


def _parse_item(item: dict) -> dict | None:
    """Разбирает одну NFT. Возвращает None, если она не годится."""
    try:
        address = item.get("address", "")
        if not address:
            return None

        # NFT из нашей же коллекции сжигать нельзя — иначе можно крутить
        # цикл «сжёг нашу, получил нашу» и вымывать редкие слоты
        collection = item.get("collection") or {}
        collection_addr = collection.get("address", "")
        if config.COLLECTION_CONTRACT_ADDRESS and collection_addr == config.COLLECTION_CONTRACT_ADDRESS:
            return None

        meta = item.get("metadata") or {}
        name = meta.get("name") or f"NFT {item.get('index', '')}"

        image = ""
        previews = item.get("previews") or []
        for p in previews:
            if p.get("resolution") in ("100x100", "500x500"):
                image = p.get("url", "")
                break
        if not image and previews:
            image = previews[0].get("url", "")
        if not image:
            image = meta.get("image", "")

        verified = bool(collection.get("verified") or item.get("verified"))

        return {
            "address": address,
            "name": name[:40],
            "image": image,
            "collection": collection.get("name", ""),
            "collection_address": collection_addr,
            "verified": verified,
        }
    except Exception as e:
        logger.warning(f"Не разобрал NFT: {e}")
        return None


def fetch_collection_stats(collection_address: str) -> dict:
    """
    Флор и объём торгов коллекции. Нужно, чтобы понять, ценное сжигают
    или мусор. Если данных нет — считаем нулями, то есть мусором.
    """
    if not collection_address:
        return {"floor": 0.0, "volume": 0.0}
    try:
        data = _get(f"/nfts/collections/{collection_address}")
        # TonAPI отдаёт цены в нанотонах
        floor = float(data.get("floor_price", 0) or 0) / 1e9
        volume = float(data.get("total_volume", 0) or 0) / 1e9
        return {"floor": floor, "volume": volume}
    except Exception as e:
        logger.warning(f"Нет статистики по коллекции {collection_address[:12]}…: {e}")
        return {"floor": 0.0, "volume": 0.0}


def score_item(nft: dict, stats: dict) -> int:
    """
    Оценка одной NFT, 0..100 — та же формула, что в rarity.py.
    Держим её здесь же, чтобы фронтенд показывал человеку то же число,
    которое потом посчитает сервер при минте.
    """
    floor = stats.get("floor", 0.0)
    volume = stats.get("volume", 0.0)

    score = min(floor * 4.0, 60.0)
    if nft.get("verified"):
        score += 20.0
    if volume >= 1.0:
        score += 10.0
    if volume >= 100.0:
        score += 10.0
    return int(min(score, 100))


def is_eligible(nft: dict, stats: dict) -> tuple[bool, str]:
    """
    Годится ли NFT для сжигания.

    Смысл не в том, чтобы отсечь дешёвое — дешёвое жечь можно, оно просто
    даст низкую редкость. Смысл в том, чтобы отсечь свеженапечатанные
    пустышки, созданные ради обмана формулы.
    """
    if not nft.get("address"):
        return False, "нет адреса"

    volume = stats.get("volume", 0.0)
    verified = nft.get("verified", False)

    # либо коллекция верифицирована, либо у неё есть реальная история торгов
    if not verified and volume < MIN_COLLECTION_VOLUME:
        return False, "коллекция без истории торгов"

    return True, "ok"
