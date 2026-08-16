"""
Vial backend — конфигурация.
Все значения приходят из .env, ничего не хардкодится.
"""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
PINATA_JWT = os.getenv("PINATA_JWT", "")

TON_MNEMONIC = os.getenv("TON_MNEMONIC", "")
NFT_WALLET_SEED_ENCRYPTED = os.getenv("NFT_WALLET_SEED_ENCRYPTED", "")
NFT_SEED_KEY = os.getenv("NFT_SEED_KEY", "")

VAULT_CONTRACT_ADDRESS = os.getenv("VAULT_CONTRACT_ADDRESS", "")
CONTROLLER_CONTRACT_ADDRESS = os.getenv("CONTROLLER_CONTRACT_ADDRESS", "")
COLLECTION_CONTRACT_ADDRESS = os.getenv("COLLECTION_CONTRACT_ADDRESS", "")

TON_NETWORK = os.getenv("TON_NETWORK", "testnet")  # testnet | mainnet
DEBUG = os.getenv("DEBUG", "false").lower() == "true"


def check_required():
    """Падаем громко при старте, если чего-то не хватает — не тихо где-то в середине запроса."""
    required = {
        "BOT_TOKEN": BOT_TOKEN,
        "PINATA_JWT": PINATA_JWT,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(f"Не заполнены обязательные переменные в .env: {', '.join(missing)}")
