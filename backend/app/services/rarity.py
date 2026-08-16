"""
Vial — система редкости.

Главное решение (обсуждалось отдельно): тир НЕ роллится случайно каждый раз.
Если бросать кубик на каждый минт, "3 мифика на коллекцию" превращается в
"в среднем около 3, а по факту может быть 0, а может 7". Вероятность не умеет
обещать точное число.

Поэтому: заранее готовим колоду ровно на CAP карточек, где Mythic лежит ровно
3 раза, Legendary — ровно 6, и так далее. Каждый минт вытягивает следующую
карту. Числа гарантированы по построению, а не по удаче.

Ценность сожжённого влияет не на "повезёт/не повезёт", а на то, из какой
части колоды тянем — кто сжигает дорогое, тянет из утяжелённой к верху
подколоды. Когда мифики кончились — их физически неоткуда взять.
"""
import hashlib
import random
from enum import Enum
from dataclasses import dataclass


class Tier(str, Enum):
    COMMON = "Common"
    UNCOMMON = "Uncommon"
    RARE = "Rare"
    EPIC = "Epic"
    LEGENDARY = "Legendary"
    MYTHIC = "Mythic"


# Размер коллекции и точное число экземпляров каждого тира.
# Верхние два — жёсткое требование владельца: 3 мифика, 6 легенд, навсегда.
COLLECTION_CAP = 10_000

TIER_SUPPLY = {
    Tier.MYTHIC: 3,
    Tier.LEGENDARY: 6,
    Tier.EPIC: 191,
    Tier.RARE: 800,
    Tier.UNCOMMON: 2_000,
    Tier.COMMON: 7_000,
}

assert sum(TIER_SUPPLY.values()) == COLLECTION_CAP, "Сумма тиров должна равняться размеру коллекции"


@dataclass
class BurnedItem:
    """Один сожжённый NFT — то, что удалось узнать о нём до сжигания."""
    address: str
    collection_floor_ton: float = 0.0
    is_verified_collection: bool = False
    collection_volume_ton: float = 0.0
    image_url: str = ""


def value_score(items: list[BurnedItem]) -> float:
    """
    Оценка "насколько ценное сожгли", 0..100.

    Считаем не сырой флор в TON (он у разных коллекций несопоставим),
    а нормализованную величину: флор + бонусы за верификацию и реальный
    объём торгов. Мусор без истории торгов даёт близкий к нулю балл —
    по конструкции формулы, а не потому что мы его запретили.
    """
    if not items:
        return 0.0

    total = 0.0
    for item in items:
        score = min(item.collection_floor_ton * 4.0, 60.0)
        if item.is_verified_collection:
            score += 20.0
        if item.collection_volume_ton >= 1.0:
            score += 10.0
        if item.collection_volume_ton >= 100.0:
            score += 10.0
        total += score

    return min(total / len(items), 100.0)


def guaranteed_floor_tier(score: float) -> Tier:
    """
    Гарантированный минимум ("что пришло, то и вышло, или чуть выше").
    Сжёг ценное — плохого исхода не будет физически, дальше уже рандом вверх.
    """
    if score >= 80:
        return Tier.RARE
    if score >= 50:
        return Tier.UNCOMMON
    return Tier.COMMON


def derive_seed(session_id: int, parent_addresses: list[str]) -> int:
    """
    Сид выводится из данных сессии, а не из random() на бэкенде.
    Смысл: результат воспроизводим и проверяем — кто угодно может пересчитать
    и убедиться, что мы не подкрутили исход задним числом.
    """
    raw = f"{session_id}|" + "|".join(sorted(parent_addresses))
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return int(digest[:16], 16)


class TierAllocator:
    """
    Колода тиров. Тянет карты по одной, ведёт учёт остатка.

    В боевом варианте остаток должен жить в базе данных, а не в памяти
    процесса — иначе перезапуск сервера обнулит счётчик и мификов станет
    больше трёх. Здесь пока in-memory, для тестов; переезд в БД — отдельная
    задача перед mainnet.
    """

    def __init__(self, remaining: dict[Tier, int] | None = None):
        self.remaining = dict(remaining or TIER_SUPPLY)

    def total_left(self) -> int:
        return sum(self.remaining.values())

    def draw(self, seed: int, floor_tier: Tier) -> Tier:
        """
        Тянет тир не ниже floor_tier. Если карт нужного уровня не осталось —
        спускаемся ниже, но никогда не выдаём больше, чем заложено в тираж.
        """
        rng = random.Random(seed)
        order = [Tier.MYTHIC, Tier.LEGENDARY, Tier.EPIC, Tier.RARE, Tier.UNCOMMON, Tier.COMMON]
        floor_index = order.index(floor_tier)

        # доступные тиры не ниже пола
        pool = [(t, self.remaining[t]) for t in order[: floor_index + 1] if self.remaining[t] > 0]

        if not pool:
            # пол недостижим — берём что осталось вообще
            pool = [(t, self.remaining[t]) for t in order if self.remaining[t] > 0]
        if not pool:
            raise RuntimeError("Коллекция полностью раскуплена — свободных слотов не осталось")

        tiers, weights = zip(*pool)
        chosen = rng.choices(tiers, weights=weights, k=1)[0]
        self.remaining[chosen] -= 1
        return chosen


def resolve_tier(
    allocator: TierAllocator,
    session_id: int,
    items: list[BurnedItem],
) -> tuple[Tier, float, int]:
    """
    Полный расчёт: оценили сожжённое → определили гарантированный пол →
    вытянули карту из колоды.

    Возвращает (тир, оценка ценности, сид) — сид пригодится дальше для
    выбора конкретных трейтов, чтобы вся картинка была воспроизводима.
    """
    score = value_score(items)
    floor = guaranteed_floor_tier(score)
    seed = derive_seed(session_id, [i.address for i in items])
    tier = allocator.draw(seed, floor)
    return tier, score, seed
