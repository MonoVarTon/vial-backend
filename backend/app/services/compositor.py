"""
Vial — сборка картинки.

Принцип слоёв взят из ai-sticker-factory (там он рабочий): фон → задний
эффект → персонаж → передний эффект, всё склеивается в один RGBA.

Отличие от донора: цвет персонажа не выбирается из пресетов, а берётся
из того, что пользователь сжёг. При этом форма сожжённого НИКОГДА не
попадает в картинку — только палитра. Даже если сожгли визуальный мусор,
худший случай — блёклый оттенок внутри нашего узнаваемого силуэта, а не
каша на экране.

Никакой генеративной модели на минте нет. Это осознанно: живая генерация
дала бы 30-90 секунд ожидания, счёт за GPU на каждую попытку и риск, что
из мусора на входе выйдет мусор на выходе.
"""
import io
import logging
from PIL import Image
from app.services.rarity import Tier

logger = logging.getLogger("vial.compositor")

CANVAS_SIZE = (1000, 1000)  # getgems любит квадрат; 1000px с запасом

# Насколько ярко бликует стекло — единственное, что зависит от тира напрямую.
# Чем выше тир, тем глубже стекло: Mythic видно с первого взгляда в ленте.
GLASS_INTENSITY = {
    Tier.COMMON: 0.35,
    Tier.UNCOMMON: 0.45,
    Tier.RARE: 0.60,
    Tier.EPIC: 0.75,
    Tier.LEGENDARY: 0.88,
    Tier.MYTHIC: 1.00,
}


def extract_palette(image_bytes: bytes, colors: int = 3) -> list[tuple[int, int, int]]:
    """
    Достаёт доминирующие цвета картинки.

    Обычное квантование цветов, не нейросеть — работает на любом изображении,
    хоть на пиксель-арте, хоть на фотографии, хоть на бессмысленной генерации.
    Именно поэтому оно и выбрано: не может "не понять" вход.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img.thumbnail((150, 150))  # для скорости, точность цвета не страдает

        quantized = img.quantize(colors=colors, method=Image.Quantize.FASTOCTREE)
        palette = quantized.getpalette()[: colors * 3]

        result = []
        for i in range(colors):
            r, g, b = palette[i * 3 : i * 3 + 3]
            result.append((r, g, b))

        # У однотонных картинок квантование добивает палитру чистым чёрным —
        # это не цвет изображения, а пустая ячейка. Если её оставить,
        # градиент уходит в чёрный и вещь выглядит грязной.
        meaningful = [c for c in result if sum(c) > 90]

        # Отдельно: если сожжённая NFT сама по себе почти чёрная, честная
        # палитра даст неразличимую тёмную кляксу. Подтягиваем яркость,
        # сохраняя оттенок — вещь должна остаться читаемой в ленте.
        lifted = []
        for c in meaningful:
            if sum(c) < 180:
                factor = 180 / max(sum(c), 1)
                c = tuple(min(int(v * factor), 255) for v in c)
            lifted.append(c)

        if not lifted:
            return [(127, 168, 156), (75, 67, 104)]
        while len(lifted) < colors:
            lifted.append(lifted[-1])
        return lifted

    except Exception as e:
        logger.warning(f"Не удалось извлечь палитру: {e}")
        return [(127, 168, 156), (75, 67, 104)]  # запасной вариант — цвета бренда


def blend_palettes(palettes: list[list[tuple[int, int, int]]]) -> tuple[tuple, tuple]:
    """
    Смешивает палитры всех сожжённых в один градиент (верхний и нижний цвет).

    Простое усреднение намеренно: результат предсказуем и воспроизводим,
    а "художественность" даёт не хитрость смешивания, а сам стекольный слой.
    """
    if not palettes:
        return (127, 168, 156), (75, 67, 104)

    tops = [p[0] for p in palettes if p]
    bottoms = [p[-1] for p in palettes if p]

    def avg(colors):
        n = len(colors)
        return tuple(sum(c[i] for c in colors) // n for i in range(3))

    return avg(tops), avg(bottoms)


def desaturate_toward(color: tuple, target: tuple, amount: float = 0.25) -> tuple:
    """
    Слегка тянет цвет к нейтральному.

    Зачем: кислотные цвета из чужих NFT ломают вид коллекции. Небольшой
    сдвиг к нашей палитре держит вещи в одном визуальном языке, но не
    стирает то, что пришло от сожжённого.
    """
    return tuple(int(c * (1 - amount) + t * amount) for c, t in zip(color, target))


def make_gradient(size: tuple, top: tuple, bottom: tuple) -> Image.Image:
    """Вертикальный градиент — это и есть 'заливка' силуэта персонажа."""
    grad = Image.new("RGB", (1, size[1]))
    for y in range(size[1]):
        ratio = y / max(size[1] - 1, 1)
        pixel = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        grad.putpixel((0, y), pixel)
    return grad.resize(size, Image.Resampling.BILINEAR)


def compose_nft(
    silhouette_mask: Image.Image,
    glass_overlay: Image.Image,
    background: Image.Image,
    palette_top: tuple,
    palette_bottom: tuple,
    tier: Tier,
    front_effect: Image.Image | None = None,
) -> bytes:
    """
    Собирает финальную картинку.

    Порядок слоёв:
      1. фон-карточка
      2. силуэт персонажа, залитый градиентом из сожжённого
      3. запечённое стекло (блик, преломление) — прозрачность по тиру
      4. передний эффект, если есть

    silhouette_mask — чёрно-белая маска формы капли (белое = тело).
    glass_overlay — заранее отрендеренный слой бликов с прозрачностью.
    Оба готовятся художником один раз и переиспользуются всегда.
    """
    canvas = background.convert("RGBA").resize(CANVAS_SIZE, Image.Resampling.LANCZOS)

    # тело персонажа: градиент, обрезанный маской силуэта
    gradient = make_gradient(CANVAS_SIZE, palette_top, palette_bottom).convert("RGBA")
    mask = silhouette_mask.convert("L").resize(CANVAS_SIZE, Image.Resampling.LANCZOS)
    body = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    body.paste(gradient, (0, 0), mask)
    canvas = Image.alpha_composite(canvas, body)

    # стекло поверх — чем выше тир, тем заметнее
    glass = glass_overlay.convert("RGBA").resize(CANVAS_SIZE, Image.Resampling.LANCZOS)
    intensity = GLASS_INTENSITY.get(tier, 0.5)
    alpha = glass.getchannel("A").point(lambda a: int(a * intensity))
    glass.putalpha(alpha)
    canvas = Image.alpha_composite(canvas, glass)

    if front_effect is not None:
        fx = front_effect.convert("RGBA").resize(CANVAS_SIZE, Image.Resampling.LANCZOS)
        canvas = Image.alpha_composite(canvas, fx)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def make_placeholder(palette_top: tuple, palette_bottom: tuple, tier: Tier) -> bytes:
    """
    Заглушка, пока художник не отдал настоящие слои.

    Просто градиент из сожжённого + подпись тира. Нужна, чтобы можно было
    гонять весь цикл целиком (сжёг → получил NFT) не дожидаясь финального арта.
    """
    from PIL import ImageDraw

    img = make_gradient(CANVAS_SIZE, palette_top, palette_bottom).convert("RGB")
    draw = ImageDraw.Draw(img)

    label = f"VIAL · {tier.value}"
    draw.text((CANVAS_SIZE[0] // 2 - 90, CANVAS_SIZE[1] - 80), label, fill=(255, 255, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
