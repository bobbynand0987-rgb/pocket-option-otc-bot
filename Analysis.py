def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (price - result) * multiplier + result

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(values):
    if len(values) < 35:
        return None, None

    def ema_series(data, period):
        result = [None] * (period - 1)
        current = sum(data[:period]) / period
        result.append(current)

        multiplier = 2 / (period + 1)

        for price in data[period:]:
            current = (price - current) * multiplier + current
            result.append(current)

        return result

    fast = ema_series(values, 12)
    slow = ema_series(values, 26)

    macd_values = []

    for i in range(25, len(values)):
        macd_values.append(fast[i] - slow[i])

    if len(macd_values) < 9:
        return None, None

    macd_line = macd_values[-1]
    signal_line = ema(macd_values, 9)

    return macd_line, signal_line


def bollinger(values, period=20, multiplier=2):
    if len(values) < period:
        return None, None, None

    recent = values[-period:]
    middle = sum(recent) / period

    variance = sum((x - middle) ** 2 for x in recent) / period
    deviation = variance ** 0.5

    upper = middle + multiplier * deviation
    lower = middle - multiplier * deviation

    return upper, middle, lower


def analyze_candles(candles):
    if not candles or len(candles) < 35:
        return {
            "signal": "WAIT",
            "reason": "Not enough candle data"
        }

    try:
        closes = [float(c["close"]) for c in candles]
        opens = [float(c["open"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
    except (KeyError, TypeError, ValueError):
        return {
            "signal": "WAIT",
            "reason": "Invalid candle data"
        }

    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)
    rsi14 = rsi(closes, 14)
    macd_line, macd_signal = macd(closes)
    upper, middle, lower = bollinger(closes)

    last = len(candles) - 1
    previous = last - 1

    bullish_candle = (
        closes[last] > opens[last] and
        closes[last] > highs[previous]
    )

    bearish_candle = (
        closes[last] < opens[last] and
        closes[last] < lows[previous]
    )

    bullish = [
        ema9 > ema21,
        rsi14 > 50,
        macd_line > macd_signal,
        closes[last] > middle,
        bullish_candle
    ]

    bearish = [
        ema9 < ema21,
        rsi14 < 50,
        macd_line < macd_signal,
        closes[last] < middle,
        bearish_candle
    ]

    if all(bullish):
        signal = "BUY"
        confidence = 5
    elif all(bearish):
        signal = "SELL"
        confidence = 5
    else:
        signal = "WAIT"
        confidence = max(sum(bullish), sum(bearish))

    return {
        "signal": signal,
        "confirmations": confidence,
        "total_confirmations": 5,
        "price": closes[-1],
        "ema9": round(ema9, 6),
        "ema21": round(ema21, 6),
        "rsi": round(rsi14, 2),
        "macd": round(macd_line, 6),
        "macd_signal": round(macd_signal, 6),
        "bollinger_upper": round(upper, 6),
        "bollinger_middle": round(middle, 6),
        "bollinger_lower": round(lower, 6)
    }
