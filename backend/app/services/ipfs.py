"""
Vial backend — загрузка на IPFS (Pinata).
Основа взята из ai-sticker-factory/nft_mint_service/ipfs.py — там код был
рабочий и простой, я его не переписывал ради переписывания. Изменено:
- аутентификация через JWT вместо старой пары api_key/secret_key (актуальнее)
- схема метаданных под нашу механику (Lineage — адреса сожжённых родителей)
"""
import requests
import logging
from app import config

logger = logging.getLogger("vial.ipfs")


def upload_file_to_ipfs(data: bytes, filename: str = "vial.png") -> str:
    """Загружает файл на Pinata. Возвращает ipfs://<hash> или пустую строку при ошибке."""
    if not config.PINATA_JWT:
        logger.error("PINATA_JWT не задан")
        return ""

    try:
        url = "https://api.pinata.cloud/pinning/pinFileToIPFS"
        files = {"file": (filename, data)}
        headers = {"Authorization": f"Bearer {config.PINATA_JWT}"}

        resp = requests.post(url, files=files, headers=headers, timeout=30)
        resp.raise_for_status()

        ipfs_hash = resp.json()["IpfsHash"]
        uri = f"ipfs://{ipfs_hash}"
        logger.info(f"Залито на IPFS: {ipfs_hash}")
        return uri

    except Exception as e:
        logger.error(f"Ошибка загрузки на IPFS: {e}")
        return ""


def upload_json_to_ipfs(data: dict, name: str = "metadata.json") -> str:
    """Загружает JSON-метаданные на Pinata. Возвращает ipfs://<hash>."""
    if not config.PINATA_JWT:
        logger.error("PINATA_JWT не задан")
        return ""

    try:
        url = "https://api.pinata.cloud/pinning/pinJSONToIPFS"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.PINATA_JWT}",
        }
        payload = {"pinataContent": data, "pinataMetadata": {"name": name}}

        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()

        ipfs_hash = resp.json()["IpfsHash"]
        uri = f"ipfs://{ipfs_hash}"
        logger.info(f"JSON залит на IPFS: {ipfs_hash}")
        return uri

    except Exception as e:
        logger.error(f"Ошибка загрузки JSON на IPFS: {e}")
        return ""


def create_nft_metadata(
    name: str,
    description: str,
    image_ipfs_uri: str,
    item_index: int,
    tier: str,
    parent_addresses: list[str],
    attributes: list = None,
) -> dict:
    """
    Собирает TEP-64 метаданные для итоговой NFT.
    parent_addresses — адреса сожжённых родителей, это и есть трейт Lineage
    из раздела 4.2 брифа: нарративная и рыночная ценность происхождения.
    """
    base_attributes = attributes or []
    base_attributes.append({"trait_type": "Rarity", "value": tier})
    for i, addr in enumerate(parent_addresses):
        base_attributes.append({"trait_type": f"Lineage {i+1}", "value": addr})

    return {
        "name": name,
        "description": description,
        "image": image_ipfs_uri,
        "attributes": base_attributes,
    }
