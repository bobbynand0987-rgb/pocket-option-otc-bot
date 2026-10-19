from Analysis import analyze_candles


MIN_HISTORY = 35
TRAIN_RATIO = 0.70


# ======================================================
# HELPERS
# ======================================================

def ema(values, period):
    multiplier = 2 / (period + 1)
    result = values[0]

    for value in values[1:]:
        result = (
            value * multiplier
            + result * (1 - multiplier)
        )

    return result


def calculate_rsi(values, period=14):
    if len(values) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    gains = gains[-period:]
    losses = losses[-period:]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


def get_market_values(history):
    closes = [
        float(candle["close"])
        for candle in history
    ]

    price = closes[-1]

    ema9 = ema(
        closes[-35:],
        9
    )

    ema21 = ema(
        closes[-35:],
        21
    )

    rsi = calculate_rsi(
        closes,
        14
    )

    return {
        "price": price,
        "ema9": ema9,
        "ema21": ema21,
        "rsi": rsi
    }


# ======================================================
# STRATEGIES
# ======================================================

def strategy_original(history):
    analysis = analyze_candles(
        history
    )

    return {
        "signal":
            analysis["signal"],

        "strength":
            int(
                analysis.get(
                    "confidence",
                    0
                )
            )
    }


def strategy_ema(history):
    data = get_market_values(
        history
    )

    if data["ema9"] >= data["ema21"]:
        signal = "BUY"
    else:
        signal = "SELL"

    return {
        "signal": signal,
        "strength": 0
    }


def strategy_ema_rsi(history):
    data = get_market_values(
        history
    )

    bullish_trend = (
        data["ema9"]
        > data["ema21"]
    )

    bearish_trend = (
        data["ema9"]
        < data["ema21"]
    )

    if (
        bullish_trend
        and data["rsi"] >= 50
    ):
        signal = "BUY"

    elif (
        bearish_trend
        and data["rsi"] < 50
    ):
        signal = "SELL"

    else:
        # Always produce a direction.
        signal = (
            "BUY"
            if data["rsi"] >= 50
            else "SELL"
        )

    return {
        "signal": signal,
        "strength": 0
    }


def strategy_momentum(history):
    closes = [
        float(candle["close"])
        for candle in history
    ]

    current = closes[-1]

    previous = closes[-4]

    if current >= previous:
        signal = "BUY"
    else:
        signal = "SELL"

    return {
        "signal": signal,
        "strength": 0
    }


def strategy_mean_reversion(history):
    data = get_market_values(
        history
    )

    # Short-term overbought/oversold
    # contrarian test.

    if data["rsi"] >= 60:
        signal = "SELL"

    elif data["rsi"] <= 40:
        signal = "BUY"

    else:
        # Around neutral, use price vs EMA.
        if data["price"] < data["ema21"]:
            signal = "BUY"
        else:
            signal = "SELL"

    return {
        "signal": signal,
        "strength": 0
    }


STRATEGIES = {
    "original_5_vote":
        strategy_original,

    "ema_trend":
        strategy_ema,

    "ema_rsi":
        strategy_ema_rsi,

    "momentum_3":
        strategy_momentum,

    "rsi_mean_reversion":
        strategy_mean_reversion
}


# ======================================================
# TEST ONE STRATEGY
# ======================================================

def test_strategy(
    candles,
    strategy_function,
    start_index,
    end_index
):

    wins = 0
    losses = 0
    draws = 0

    buy_wins = 0
    buy_losses = 0

    sell_wins = 0
    sell_losses = 0

    trades = 0

    strength_stats = {}

    for i in range(
        start_index,
        end_index
    ):

        if i + 1 >= len(candles):
            break

        history = candles[:i + 1]

        result = strategy_function(
            history
        )

        signal = str(
            result["signal"]
        ).upper()

        strength = int(
            result.get(
                "strength",
                0
            )
        )

        if signal not in [
            "BUY",
            "SELL"
        ]:
            continue

        # Signal becomes available after candle i
        # closes.
        #
        # We then evaluate the following
        # 1-minute candle.

        entry_price = float(
            candles[i]["close"]
        )

        expiry_price = float(
            candles[i + 1]["close"]
        )

        trades += 1

        if expiry_price > entry_price:
            actual = "BUY"

        elif expiry_price < entry_price:
            actual = "SELL"

        else:
            actual = "DRAW"

        if actual == "DRAW":

            outcome = "DRAW"
            draws += 1

        elif signal == actual:

            outcome = "WIN"
            wins += 1

        else:

            outcome = "LOSS"
            losses += 1

        if signal == "BUY":

            if outcome == "WIN":
                buy_wins += 1

            elif outcome == "LOSS":
                buy_losses += 1

        else:

            if outcome == "WIN":
                sell_wins += 1

            elif outcome == "LOSS":
                sell_losses += 1

        if strength not in strength_stats:

            strength_stats[strength] = {
                "wins": 0,
                "losses": 0,
                "draws": 0
            }

        if outcome == "WIN":
            strength_stats[strength]["wins"] += 1

        elif outcome == "LOSS":
            strength_stats[strength]["losses"] += 1

        else:
            strength_stats[strength]["draws"] += 1

    decided = wins + losses

    win_rate = (
        round(
            wins / decided * 100,
            2
        )
        if decided > 0
        else 0
    )

    buy_total = (
        buy_wins
        + buy_losses
    )

    sell_total = (
        sell_wins
        + sell_losses
    )

    buy_rate = (
        round(
            buy_wins / buy_total * 100,
            2
        )
        if buy_total > 0
        else 0
    )

    sell_rate = (
        round(
            sell_wins / sell_total * 100,
            2
        )
        if sell_total > 0
        else 0
    )

    return {
        "trades": trades,
        "decided": decided,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": win_rate,

        "buy": {
            "wins": buy_wins,
            "losses": buy_losses,
            "win_rate": buy_rate
        },

        "sell": {
            "wins": sell_wins,
            "losses": sell_losses,
            "win_rate": sell_rate
        }
    }


# ======================================================
# MAIN STRATEGY COMPARISON
# ======================================================

def run_backtest(candles):

    if len(candles) < 100:

        raise ValueError(
            "Not enough candles for strategy test"
        )

    usable_start = MIN_HISTORY

    split_index = int(
        len(candles)
        * TRAIN_RATIO
    )

    # Make sure both sections have enough data.

    if split_index <= usable_start:

        raise ValueError(
            "Not enough development candles"
        )

    if (
        len(candles)
        - split_index
        < 50
    ):

        raise ValueError(
            "Not enough test candles"
        )

    development_results = {}
    test_results = {}

    # ==================================================
    # DEVELOPMENT SECTION
    # ==================================================

    for name, strategy in (
        STRATEGIES.items()
    ):

        development_results[name] = (
            test_strategy(
                candles,
                strategy,
                usable_start,
                split_index
            )
        )

    # ==================================================
    # CHOOSE BEST USING DEVELOPMENT DATA ONLY
    # ==================================================

    best_strategy_name = max(
        development_results,
        key=lambda name:
            development_results[
                name
            ]["win_rate"]
    )

    # ==================================================
    # TEST EVERY STRATEGY ON UNSEEN SECTION
    # ==================================================

    for name, strategy in (
        STRATEGIES.items()
    ):

        test_results[name] = (
            test_strategy(
                candles,
                strategy,
                split_index,
                len(candles) - 1
            )
        )

    best_development = (
        development_results[
            best_strategy_name
        ]
    )

    best_unseen = (
        test_results[
            best_strategy_name
        ]
    )

    # ==================================================
    # ORIGINAL STRATEGY REFERENCE
    # ==================================================

    original_test = (
        test_results[
            "original_5_vote"
        ]
    )

    improvement = round(
        best_unseen["win_rate"]
        - original_test["win_rate"],
        2
    )

    # ==================================================
    # FINAL REPORT
    # ==================================================

    return {
        "candles":
            len(candles),

        "method":
            "70% development / 30% unseen test",

        "development_candles":
            split_index,

        "unseen_test_candles":
            len(candles)
            - split_index,

        "development_results":
            development_results,

        "selected_strategy":
            best_strategy_name,

        "selected_strategy_development_win_rate":
            best_development[
                "win_rate"
            ],

        "unseen_test_results":
            test_results,

        "selected_strategy_unseen_win_rate":
            best_unseen[
                "win_rate"
            ],

        "original_unseen_win_rate":
            original_test[
                "win_rate"
            ],

        "unseen_improvement_percentage_points":
            improvement,

        "warning":
            (
                "The selected strategy was chosen "
                "using development data only. "
                "Unseen test performance is the "
                "more important result and does "
                "not guarantee future results."
            )
    }
