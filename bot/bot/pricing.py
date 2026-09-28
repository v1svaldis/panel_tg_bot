def validate_percent(percent) -> int:
    if isinstance(percent, bool) or not isinstance(percent, int):
        raise ValueError("Скидка должна быть целым числом от 5 до 100")
    if percent < 5 or percent > 100:
        raise ValueError("Скидка должна быть целым числом от 5 до 100")
    return percent


def discounted_price(price: int, percent: int) -> int:
    validate_percent(percent)
    if isinstance(price, bool) or not isinstance(price, int) or price < 0:
        raise ValueError("Некорректная цена")
    return int(round(price * (100 - percent) / 100))
