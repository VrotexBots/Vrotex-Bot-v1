from datetime import datetime, timezone, timedelta


def utc_now():
    return datetime.now(timezone.utc)


def utc_timestamp():
    return utc_now().timestamp()


def utc_iso():
    return utc_now().isoformat()


def to_utc(dt):
    if dt is None:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def timestamp_to_datetime(timestamp):
    return datetime.fromtimestamp(
        float(timestamp),
        timezone.utc
    )


def datetime_to_timestamp(dt):
    return to_utc(dt).timestamp()


def timeframe_to_seconds(timeframe):
    mapping = {
        "M1": 60,
        "M5": 300,
        "M15": 900,
        "M30": 1800,
        "H1": 3600,
        "H4": 14400,
        "D1": 86400,
    }

    return mapping.get(timeframe.upper())


def candle_close_time(open_time, timeframe):
    seconds = timeframe_to_seconds(timeframe)

    if seconds is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    return open_time + timedelta(seconds=seconds)


def is_candle_closed(open_time, timeframe, now=None):
    now = to_utc(now or utc_now())

    close_time = candle_close_time(
        to_utc(open_time),
        timeframe
    )

    return now >= close_time


def seconds_until_next_candle(timeframe, now=None):
    now = to_utc(now or utc_now())

    seconds = timeframe_to_seconds(timeframe)

    if seconds is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    current_timestamp = now.timestamp()

    next_boundary = (
        (int(current_timestamp) // seconds) + 1
    ) * seconds

    return max(0, next_boundary - current_timestamp)
