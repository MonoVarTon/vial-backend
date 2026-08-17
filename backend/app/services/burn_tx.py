"""
Vial — сборка транзакции сжигания.

Самое ответственное место всего проекта. Здесь собирается то, что человек
подпишет в кошельке. Ошибка в формате = NFT уходят и застревают навсегда.

Что происходит: на каждую сжигаемую NFT формируется обычный TEP-62 перевод
на адрес Vault. В forward_payload каждого перевода кладётся номер сессии
и заявленное количество — по этим данным контракт понимает, что 2-4 отдельных
перевода составляют одно сжигание.

Формат payload сверен построчно с alchemy_vault.fc:
    int session_id = in_msg_body~load_uint(64);
    int declared_expected = in_msg_body~load_uint(8);
"""
import time
import secrets
import logging
from pytoniq_core import Address, begin_cell
from app import config

logger = logging.getLogger("vial.burn_tx")

# Столько TON прикладывается к каждому переводу NFT.
# Из них часть уйдёт на газ самого перевода, остаток осядет на Vault.
# 0.06 — с запасом, лишнее не теряется, а остаётся на контракте.
TON_PER_TRANSFER = 60_000_000  # 0.06 TON в нанотонах

FORWARD_AMOUNT = 1  # 1 нанотон, чтобы Vault получил уведомление ownership_assigned

OP_TRANSFER = 0x5fcc3d14  # стандартный TEP-62, не наш


def new_session_id() -> int:
    """
    Номер сессии — 64 бита. Берём криптографически случайный, а не по
    порядку: последовательные номера позволяли бы подсмотреть чужую сессию
    и попытаться в неё вклиниться.
    """
    return secrets.randbits(63)  # 63, чтобы точно влезло в uint64 без знака


def build_burn_payload(session_id: int, expected_count: int) -> "Cell":
    """
    Наш собственный forward_payload. НЕ часть стандарта TEP-62 —
    контракт Vault читает именно эту структуру.
    """
    if not (2 <= expected_count <= 4):
        raise ValueError("Сжигать можно от 2 до 4 NFT")
    if not (0 <= session_id < 2**64):
        raise ValueError("Некорректный номер сессии")

    return (
        begin_cell()
        .store_uint(session_id, 64)
        .store_uint(expected_count, 8)
        .end_cell()
    )


def build_transfer_body(
    vault_address: str,
    owner_address: str,
    session_id: int,
    expected_count: int,
    query_id: int = 0,
) -> "Cell":
    """
    Тело сообщения op::transfer по TEP-62.

    Порядок полей строго по стандарту:
      op:uint32, query_id:uint64, new_owner:MsgAddress,
      response_destination:MsgAddress, custom_payload:Maybe ^Cell,
      forward_amount:Coins, forward_payload:Either Cell ^Cell
    """
    payload = build_burn_payload(session_id, expected_count)

    return (
        begin_cell()
        .store_uint(OP_TRANSFER, 32)
        .store_uint(query_id, 64)
        .store_address(Address(vault_address))    # новый владелец — Vault
        .store_address(Address(owner_address))    # остаток газа вернуть человеку
        .store_bit(0)                             # custom_payload отсутствует
        .store_coins(FORWARD_AMOUNT)              # чтобы Vault получил уведомление
        .store_bit(1)                             # forward_payload лежит ссылкой
        .store_ref(payload)
        .end_cell()
    )


def build_burn_transaction(owner_address: str, nft_addresses: list[str]) -> dict:
    """
    Собирает всё, что нужно отдать кошельку на подпись.

    Возвращает готовый список сообщений для TonConnect плюс номер сессии,
    чтобы бэкенд мог потом сопоставить событие из блокчейна с этим запросом.
    """
    vault = config.VAULT_CONTRACT_ADDRESS
    if not vault:
        raise RuntimeError("Адрес контракта Vault не настроен")

    count = len(nft_addresses)
    if not (2 <= count <= 4):
        raise ValueError(f"Нужно от 2 до 4 NFT, получено {count}")

    if len(set(nft_addresses)) != count:
        raise ValueError("Одна и та же NFT указана дважды")

    session_id = new_session_id()
    messages = []

    for i, nft_addr in enumerate(nft_addresses):
        body = build_transfer_body(
            vault_address=vault,
            owner_address=owner_address,
            session_id=session_id,
            expected_count=count,
            query_id=i,
        )
        messages.append({
            "address": nft_addr,
            "amount": str(TON_PER_TRANSFER),
            "payload": body.to_boc().hex(),
        })

    logger.info(f"Собрана сессия {session_id}: {count} NFT от {owner_address[:12]}…")

    return {
        "session_id": str(session_id),   # строкой: 64 бита не влезают в JS-число
        "expected_count": count,
        "messages": messages,
        "valid_seconds": 360,
    }
