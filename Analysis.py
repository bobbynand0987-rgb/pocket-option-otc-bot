import math


# ======================================================
# BASIC HELPERS
# ======================================================

def get_close(candle):
    return float(candle["close"])


def get_open(candle):
    return float(candle["open"])


def get_high(candle):
    return float(candle["high"])


def get_low(candle):
    return float(candle["low"])


# ======================================================
# EMA
# ======================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    value = sum(values[:period]) / period

    for price in values[period:]:
        value = (
            (price - value)
            * multiplier
            + value
        )

    return value


def ema_series(values, period):

    if len(values) < period:
        return []

    result = []

    value = sum(values[:period]) / period

    result.append(value)

    multiplier = 2 / (period + 1)

    for price in values[period:]:

        value = (
            (price - value)
            * multiplier
            + value
        )

        result.append(value)

    return result


# ======================================================
# RSI - WILDER
# ======================================================

def rsi(values, period=14):

    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return (
        100
        - (100 / (1 + rs))
    )


# ======================================================
# MACD
# ======================================================

def macd(values):

    if len(values) < 35:
        return None, None

    fast_series = ema_series(
        values,
        12
    )

    slow_series = ema_series(
        values,
        26
    )

    offset = 26 - 12

    macd_values = []

    for i in range(
        len(slow_series)
    ):

        fast_index = i + offset

        if fast_index < len(
            fast_series
        ):

            macd_values.append(
                fast_series[fast_index]
                - slow_series[i]
            )

    if len(macd_values) < 9:
        return None, None

    macd_line = macd_values[-1]

    signal_line = ema(
        macd_values,
        9
    )

    return (
        macd_line,
        signal_line
    )


# ======================================================
# BOLLINGER BANDS
# ======================================================

def bollinger(values, period=20):

    if len(values) < period:
        return None, None, None

    recent = values[-period:]

    middle = (
        sum(recent)
        / period
    )

    variance = sum(
        (x - middle) ** 2
        for x in recent
    ) / period

    deviation = math.sqrt(
        variance
    )

    upper = (
        middle
        + 2 * deviation
    )

    lower = (
        middle
        - 2 * deviation
    )

    return (
        lower,
        middle,
        upper
    )


# ======================================================
# CANDLE DIRECTION
# ======================================================

def candle_direction(candle):

    open_price = get_open(candle)
    close_price = get_close(candle)

    if close_price > open_price:
        return "BUY"

    if close_price < open_price:
        return "SELL"

    return "NEUTRAL"


# ======================================================
# MAIN ANALYSIS
# ======================================================

def analyze_candles(candles):

    if len(candles) < 35:

        raise ValueError(
            "At least 35 candles are required"
        )

    closes = [
        get_close(c)
        for c in candles
    ]

    current_price = closes[-1]


    # --------------------------------------------------
    # INDICATORS
    # --------------------------------------------------

    ema9 = ema(
        closes,
        9
    )

    ema21 = ema(
        closes,
        21
    )

    rsi14 = rsi(
        closes,
        14
    )

    macd_line, macd_signal = (
        macd(closes)
    )

    bb_lower, bb_middle, bb_upper = (
        bollinger(
            closes,
            20
        )
    )


    # --------------------------------------------------
    # BUY / SELL SCORES
    # --------------------------------------------------

    buy_score = 0
    sell_score = 0

    reasons_buy = []
    reasons_sell = []


    # ==================================================
    # 1. EMA TREND
    # ==================================================

    if ema9 > ema21:

        buy_score += 1

        reasons_buy.append(
            "EMA trend bullish"
        )

    else:

        sell_score += 1

        reasons_sell.append(
            "EMA trend bearish"
        )


    # ==================================================
    # 2. RSI MOMENTUM
    # ==================================================

    if rsi14 >= 50:

        buy_score += 1

        reasons_buy.append(
            "RSI bullish"
        )

    else:

        sell_score += 1

        reasons_sell.append(
            "RSI bearish"
        )


    # ==================================================
    # 3. MACD
    # ==================================================

    if macd_line >= macd_signal:

        buy_score += 1

        reasons_buy.append(
            "MACD bullish"
        )

    else:

        sell_score += 1

        reasons_sell.append(
            "MACD bearish"
        )


    # ==================================================
    # 4. BOLLINGER POSITION
    # ==================================================

    if current_price >= bb_middle:

        buy_score += 1

        reasons_buy.append(
            "Price above Bollinger middle"
        )

    else:

        sell_score += 1

        reasons_sell.append(
            "Price below Bollinger middle"
        )


    # ==================================================
    # 5. LATEST CANDLE
    # ==================================================

    last_direction = (
        candle_direction(
            candles[-1]
        )
    )

    if last_direction == "BUY":

        buy_score += 1

        reasons_buy.append(
            "Latest candle bullish"
        )

    elif last_direction == "SELL":

        sell_score += 1

        reasons_sell.append(
            "Latest candle bearish"
        )

    else:

        # A neutral candle gives its point
        # to the prevailing EMA trend.

        if ema9 >= ema21:

            buy_score += 1

            reasons_buy.append(
                "Neutral candle; bullish trend"
            )

        else:

            sell_score += 1

            reasons_sell.append(
                "Neutral candle; bearish trend"
            )


    # ==================================================
    # FINAL DIRECTION
    # ==================================================

    if buy_score > sell_score:

        signal = "BUY"

        winning_score = (
            buy_score
        )

    elif sell_score > buy_score:

        signal = "SELL"

        winning_score = (
            sell_score
        )

    else:

        # Five voting conditions normally prevent
        # a tie, but keep a fallback anyway.

        if ema9 >= ema21:

            signal = "BUY"

        else:

            signal = "SELL"

        winning_score = max(
            buy_score,
            sell_score
        )


    # ==================================================
    # CONFIDENCE / SIGNAL STRENGTH
    # ==================================================

    confidence = round(
        (
            winning_score
            / 5
        )
        * 100
    )


    return {

        "signal":
            signal,

        "confidence":
            confidence,

        "buy_score":
            buy_score,

        "sell_score":
            sell_score,

        "confirmations":
            winning_score,

        "total_confirmations":
            5,

        "price":
            round(
                current_price,
                6
            ),

        "ema9":
            round(
                ema9,
                6
            ),

        "ema21":
            round(
                ema21,
                6
            ),

        "rsi":
            round(
                rsi14,
                2
            ),

        "macd":
            round(
                macd_line,
                6
            ),

        "macd_signal":
            round(
                macd_signal,
                6
            ),

        "bollinger_lower":
            round(
                bb_lower,
                6
            ),

        "bollinger_middle":
            round(
                bb_middle,
                6
            ),

        "bollinger_upper":
            round(
                bb_upper,
                6
            ),

        "buy_reasons":
            reasons_buy,

        "sell_reasons":
            reasons_sell
    }
