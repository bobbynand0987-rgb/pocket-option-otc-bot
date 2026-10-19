from Analysis import analyze_candles

MIN_HISTORY = 35
TRAIN_RATIO = 0.70


def safe_rate(wins, losses):
    total = wins + losses
    return round((wins / total) * 100, 2) if total else 0


# ------------------------------------------------------
# SELECTIVE STRATEGIES
# Return None = skip this trade
# ------------------------------------------------------

def original_all(history):
    a = analyze_candles(history)

    return {
        "signal": a["signal"],
        "confidence": int(a.get("confidence", 0))
    }


def confidence_80_plus(history):
    a = analyze_candles(history)

    confidence = int(a.get("confidence", 0))

    if confidence < 80:
        return None

    return {
        "signal": a["signal"],
        "confidence": confidence
    }


def confidence_100_only(history):
    a = analyze_candles(history)

    confidence = int(a.get("confidence", 0))

    if confidence != 100:
        return None

    return {
        "signal": a["signal"],
        "confidence": confidence
    }


def trend_macd_rsi(history):
    a = analyze_candles(history)

    signal = a["signal"]

    ema9 = float(a["ema9"])
    ema21 = float(a["ema21"])
    rsi = float(a["rsi"])
    macd = float(a["macd"])
    macd_signal = float(a["macd_signal"])

    if (
        signal == "BUY"
        and ema9 > ema21
        and macd > macd_signal
        and rsi >= 52
    ):
        return {
            "signal": "BUY",
            "confidence": int(a.get("confidence", 0))
        }

    if (
        signal == "SELL"
        and ema9 < ema21
        and macd < macd_signal
        and rsi <= 48
    ):
        return {
            "signal": "SELL",
            "confidence": int(a.get("confidence", 0))
        }

    return None


def strong_trend(history):
    a = analyze_candles(history)

    signal = a["signal"]

    ema9 = float(a["ema9"])
    ema21 = float(a["ema21"])
    price = float(a["price"])

    if price == 0:
        return None

    separation = abs(
        ema9 - ema21
    ) / price

    # 0.02% EMA separation
    minimum_separation = 0.0002

    if separation < minimum_separation:
        return None

    if signal == "BUY" and ema9 > ema21:
        return {
            "signal": "BUY",
            "confidence": int(a.get("confidence", 0))
        }

    if signal == "SELL" and ema9 < ema21:
        return {
            "signal": "SELL",
            "confidence": int(a.get("confidence", 0))
        }

    return None


def strong_combination(history):
    a = analyze_candles(history)

    signal = a["signal"]
    confidence = int(a.get("confidence", 0))

    ema9 = float(a["ema9"])
    ema21 = float(a["ema21"])
    rsi = float(a["rsi"])
    macd = float(a["macd"])
    macd_signal = float(a["macd_signal"])
    price = float(a["price"])

    if price == 0:
        return None

    separation = abs(
        ema9 - ema21
    ) / price

    if confidence < 80:
        return None

    if separation < 0.00015:
        return None

    if (
        signal == "BUY"
        and ema9 > ema21
        and macd > macd_signal
        and rsi >= 52
    ):
        return {
            "signal": "BUY",
            "confidence": confidence
        }

    if (
        signal == "SELL"
        and ema9 < ema21
        and macd < macd_signal
        and rsi <= 48
    ):
        return {
            "signal": "SELL",
            "confidence": confidence
        }

    return None


STRATEGIES = {
    "original_all": original_all,
    "confidence_80_plus": confidence_80_plus,
    "confidence_100_only": confidence_100_only,
    "trend_macd_rsi": trend_macd_rsi,
    "strong_trend": strong_trend,
    "strong_combination": strong_combination
}


# ------------------------------------------------------
# TEST STRATEGY
# ------------------------------------------------------

def test_strategy(
    candles,
    strategy_function,
    start_index,
    end_index
):

    wins = 0
    losses = 0
    draws = 0
    skipped = 0

    buy_wins = 0
    buy_losses = 0

    sell_wins = 0
    sell_losses = 0

    signals = 0

    for i in range(start_index, end_index):

        if i + 1 >= len(candles):
            break

        history = candles[:i + 1]

        result = strategy_function(history)

        if result is None:
            skipped += 1
            continue

        signal = str(
            result["signal"]
        ).upper()

        if signal not in ["BUY", "SELL"]:
            skipped += 1
            continue

        # Signal is generated after candle i closes.
        # Entry is simulated at the NEXT candle open.
        # Expiry is that same candle's close.

        next_candle = candles[i + 1]

        entry_price = float(
            next_candle["open"]
        )

        expiry_price = float(
            next_candle["close"]
        )

        signals += 1

        if expiry_price > entry_price:
            actual = "BUY"

        elif expiry_price < entry_price:
            actual = "SELL"

        else:
            actual = "DRAW"

        if actual == "DRAW":
            draws += 1
            continue

        if signal == actual:

            wins += 1

            if signal == "BUY":
                buy_wins += 1
            else:
                sell_wins += 1

        else:

            losses += 1

            if signal == "BUY":
                buy_losses += 1
            else:
                sell_losses += 1

    decided = wins + losses

    return {
        "signals": signals,
        "skipped": skipped,
        "wins": wins,
        "losses": losses,
        "draws": draws,

        "decided_trades": decided,

        "win_rate": safe_rate(
            wins,
            losses
        ),

        "buy": {
            "wins": buy_wins,
            "losses": buy_losses,
            "win_rate": safe_rate(
                buy_wins,
                buy_losses
            )
        },

        "sell": {
            "wins": sell_wins,
            "losses": sell_losses,
            "win_rate": safe_rate(
                sell_wins,
                sell_losses
            )
        }
    }


# ------------------------------------------------------
# MAIN BACKTEST
# ------------------------------------------------------

def run_backtest(candles):

    if len(candles) < 100:
        raise ValueError(
            "Not enough candles for backtest"
        )

    split_index = int(
        len(candles) * TRAIN_RATIO
    )

    development_results = {}
    unseen_results = {}

    # DEVELOPMENT DATA

    for name, strategy in STRATEGIES.items():

        development_results[name] = test_strategy(
            candles,
            strategy,
            MIN_HISTORY,
            split_index
        )

    # Select highest development win rate,
    # but require at least 50 decided trades
    # to reduce tiny-sample selection.

    eligible = {
        name: result
        for name, result
        in development_results.items()
        if result["decided_trades"] >= 50
    }

    if not eligible:
        raise ValueError(
            "No strategy produced enough trades"
        )

    selected_strategy = max(
        eligible,
        key=lambda name:
        eligible[name]["win_rate"]
    )

    # UNSEEN TEST DATA

    for name, strategy in STRATEGIES.items():

        unseen_results[name] = test_strategy(
            candles,
            strategy,
            split_index,
            len(candles) - 1
        )

    selected_development = (
        development_results[
            selected_strategy
        ]
    )

    selected_unseen = (
        unseen_results[
            selected_strategy
        ]
    )

    original_unseen = (
        unseen_results[
            "original_all"
        ]
    )

    improvement = round(
        selected_unseen["win_rate"]
        - original_unseen["win_rate"],
        2
    )

    return {
        "candles": len(candles),

        "timing_model":
            "signal after close -> next candle open entry -> next candle close expiry",

        "split":
            "70% development / 30% unseen",

        "development_results":
            development_results,

        "selected_strategy":
            selected_strategy,

        "selected_development_win_rate":
            selected_development[
                "win_rate"
            ],

        "selected_development_trades":
            selected_development[
                "decided_trades"
            ],

        "unseen_results":
            unseen_results,

        "selected_unseen_win_rate":
            selected_unseen[
                "win_rate"
            ],

        "selected_unseen_trades":
            selected_unseen[
                "decided_trades"
            ],

        "original_unseen_win_rate":
            original_unseen[
                "win_rate"
            ],

        "improvement_percentage_points":
            improvement,

        "important":
            (
                "Higher historical win rate does not "
                "guarantee future results. Small trade "
                "samples should not be treated as reliable."
            )
    }
