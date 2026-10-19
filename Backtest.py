from Analysis import analyze_candles


def run_backtest(candles):

    # Need enough candles for indicators
    if len(candles) < 40:
        raise ValueError(
            "Not enough candles for backtest"
        )

    results = []

    wins = 0
    losses = 0
    draws = 0

    buy_wins = 0
    buy_losses = 0

    sell_wins = 0
    sell_losses = 0

    confidence_stats = {
        60: {"wins": 0, "losses": 0, "draws": 0},
        80: {"wins": 0, "losses": 0, "draws": 0},
        100: {"wins": 0, "losses": 0, "draws": 0}
    }


    # Start after enough history exists.
    #
    # Stop one candle before the end because
    # the next candle is used as the result.

    for i in range(
        35,
        len(candles) - 1
    ):

        history = candles[:i + 1]

        analysis = analyze_candles(
            history
        )

        signal = analysis["signal"]

        confidence = int(
            analysis["confidence"]
        )


        # ==========================================
        # ENTRY
        # ==========================================

        current_candle = candles[i]

        entry_price = float(
            current_candle["close"]
        )


        # ==========================================
        # 1-MINUTE EXPIRY
        # ==========================================

        next_candle = candles[i + 1]

        expiry_price = float(
            next_candle["close"]
        )


        # ==========================================
        # RESULT
        # ==========================================

        if expiry_price > entry_price:

            actual_direction = "BUY"

        elif expiry_price < entry_price:

            actual_direction = "SELL"

        else:

            actual_direction = "DRAW"


        if actual_direction == "DRAW":

            result = "DRAW"
            draws += 1

        elif signal == actual_direction:

            result = "WIN"
            wins += 1

        else:

            result = "LOSS"
            losses += 1


        # ==========================================
        # BUY STATS
        # ==========================================

        if signal == "BUY":

            if result == "WIN":
                buy_wins += 1

            elif result == "LOSS":
                buy_losses += 1


        # ==========================================
        # SELL STATS
        # ==========================================

        elif signal == "SELL":

            if result == "WIN":
                sell_wins += 1

            elif result == "LOSS":
                sell_losses += 1


        # ==========================================
        # CONFIDENCE STATS
        # ==========================================

        if confidence not in confidence_stats:

            confidence_stats[confidence] = {
                "wins": 0,
                "losses": 0,
                "draws": 0
            }


        if result == "WIN":

            confidence_stats[
                confidence
            ]["wins"] += 1

        elif result == "LOSS":

            confidence_stats[
                confidence
            ]["losses"] += 1

        else:

            confidence_stats[
                confidence
            ]["draws"] += 1


        results.append({

            "signal":
                signal,

            "confidence":
                confidence,

            "entry_price":
                entry_price,

            "expiry_price":
                expiry_price,

            "actual_direction":
                actual_direction,

            "result":
                result
        })


    # ==============================================
    # TOTAL TRADES
    # ==============================================

    decided_trades = (
        wins + losses
    )


    if decided_trades > 0:

        win_rate = round(
            (
                wins
                / decided_trades
            )
            * 100,
            2
        )

    else:

        win_rate = 0


    # ==============================================
    # BUY WIN RATE
    # ==============================================

    buy_total = (
        buy_wins
        + buy_losses
    )


    if buy_total > 0:

        buy_win_rate = round(
            (
                buy_wins
                / buy_total
            )
            * 100,
            2
        )

    else:

        buy_win_rate = 0


    # ==============================================
    # SELL WIN RATE
    # ==============================================

    sell_total = (
        sell_wins
        + sell_losses
    )


    if sell_total > 0:

        sell_win_rate = round(
            (
                sell_wins
                / sell_total
            )
            * 100,
            2
        )

    else:

        sell_win_rate = 0


    # ==============================================
    # CONFIDENCE WIN RATES
    # ==============================================

    confidence_summary = {}


    for confidence, stats in (
        confidence_stats.items()
    ):

        total = (
            stats["wins"]
            + stats["losses"]
        )


        if total > 0:

            rate = round(
                (
                    stats["wins"]
                    / total
                )
                * 100,
                2
            )

        else:

            rate = 0


        confidence_summary[
            str(confidence)
        ] = {

            "trades":
                total,

            "wins":
                stats["wins"],

            "losses":
                stats["losses"],

            "draws":
                stats["draws"],

            "win_rate":
                rate
        }


    # ==============================================
    # FINAL REPORT
    # ==============================================

    return {

        "candles":
            len(candles),

        "trades_tested":
            len(results),

        "decided_trades":
            decided_trades,

        "wins":
            wins,

        "losses":
            losses,

        "draws":
            draws,

        "win_rate":
            win_rate,

        "buy": {

            "wins":
                buy_wins,

            "losses":
                buy_losses,

            "win_rate":
                buy_win_rate
        },

        "sell": {

            "wins":
                sell_wins,

            "losses":
                sell_losses,

            "win_rate":
                sell_win_rate
        },

        "confidence_levels":
            confidence_summary
    }
