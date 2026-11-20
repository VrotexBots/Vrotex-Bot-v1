import re


APPROVED_INSTRUMENTS = {
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "EURJPY",
    "EURGBP",
    "BTCUSD",
}

APPROVED_TIMEFRAMES = {
    "D1",
    "H4",
    "H1",
    "M30",
    "M15",
    "M5",
    "M1",
}


def validate_instrument(symbol: str) -> bool:
    if not isinstance(symbol, str):
        return False

    return symbol.upper().strip() in APPROVED_INSTRUMENTS


def validate_timeframe(timeframe: str) -> bool:
    if not isinstance(timeframe, str):
        return False

    return timeframe.upper().strip() in APPROVED_TIMEFRAMES


def validate_price(price) -> bool:
    try:
        value = float(price)
        return value > 0 and value != float("inf")
    except (TypeError, ValueError):
        return False


def validate_percentage(value, minimum=0, maximum=100) -> bool:
    try:
        number = float(value)
        return minimum <= number <= maximum
    except (TypeError, ValueError):
        return False


def validate_positive_number(value) -> bool:
    try:
        number = float(value)
        return number > 0 and number != float("inf")
    except (TypeError, ValueError):
        return False


def validate_trade_direction(direction: str) -> bool:
    if not isinstance(direction, str):
        return False

    return direction.upper().strip() in {"BUY", "SELL"}


def validate_score(score) -> bool:
    try:
        value = float(score)
        return 0 <= value <= 100
    except (TypeError, ValueError):
        return False


def validate_order_id(order_id) -> bool:
    if order_id is None:
        return False

    return bool(str(order_id).strip())


def validate_api_key(api_key: str) -> bool:
    if not isinstance(api_key, str):
        return False

    return len(api_key.strip()) >= 8


def validate_account_id(account_id) -> bool:
    if account_id is None:
        return False

    return bool(re.fullmatch(r"[0-9]+", str(account_id).strip()))
