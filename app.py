import os
import json
import urllib.request
import urllib.parse
import urllib.error

from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask

from Analysis import analyze_candles
from Backtest import run_backtest


app = Flask(__name__)


# ======================================================
# SETTINGS
# ======================================================

TIMEFRAME_SECONDS = 5

# Live signal candles
CANDLE_LIMIT = 60

# Historical candles per pair
BACKTEST_CANDLE_LIMIT = 1000

# Maximum acceptable age for 5-second feed
MAX_CANDLE_AGE_SECONDS = 20

# Timestamp correction that worked with current OTCharts feed
OTCHARTS_TIME_OFFSET_HOURS = float(
    os.environ.get(
        "OTCHARTS_TIME_OFFSET_HOURS",
        "-2"
    )
)

# These four pairs were confirmed working.
SYMBOLS = {
    "EURUSD_otc": "EUR/USD OTC",
    "GBPUSD_otc": "GBP/USD OTC",
    "AUDUSD_otc": "AUD/USD OTC",
    "USDJPY_otc": "USD/JPY OTC"
}


# ======================================================
# HOME
# ======================================================

@app.route("/")
def home():

    return {
        "status": "online",
        "bot": "Pocket Option OTC 5-Second Scanner",
        "market": "Pocket Option OTC",
        "timeframe": "5 seconds",
        "expiry_reference": "5 seconds",
        "pairs": list(SYMBOLS.values()),
        "source": "OTCharts"
    }


# ======================================================
# STATUS
# ======================================================

@app.route("/status")
def status():

    return {
        "status": "online",
        "market": "Pocket Option OTC",
        "scanner": "4-pair OTC scanner",
        "timeframe": "5 seconds",
        "expiry_reference": "5 seconds",
        "pairs": list(SYMBOLS.values()),
        "source": "OTCharts"
    }


# ======================================================
# GET API KEY
# ======================================================

def get_api_key():

    api_key = os.environ.get(
        "OTCHARTS_API_KEY",
        ""
    ).strip()

    if not api_key:

        raise Exception(
            "OTCHARTS_API_KEY is missing"
        )

    return api_key


# ======================================================
# DOWNLOAD OTC CANDLES
# ======================================================

def download_otc_candles(
    symbol,
    limit=CANDLE_LIMIT
):

    api_key = get_api_key()

    params = urllib.parse.urlencode({
        "venue": "otc",
        "symbol": symbol,
        "tf": TIMEFRAME_SECONDS,
        "limit": limit
    })

    url = (
        "https://otcharts.com/v1/candles?"
        + params
    )

    request = urllib.request.Request(
        url,
        headers={
            "Authorization":
                "Bearer " + api_key,

            "User-Agent":
                "OTC-5S-Scanner/2.0",

            "Accept":
                "application/json",

            "Connection":
                "keep-alive"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=10
    ) as response:

        body = (
            response
            .read()
            .decode("utf-8")
        )

    data = json.loads(body)

    candles = data.get(
        "candles",
        []
    )

    if not candles:

        raise Exception(
            "No candles returned for "
            + symbol
        )

    valid_candles = []

    for candle in candles:

        try:

            valid_candles.append({
                "time":
                    int(candle["time"]),

                "open":
                    float(candle["open"]),

                "high":
                    float(candle["high"]),

                "low":
                    float(candle["low"]),

                "close":
                    float(candle["close"])
            })

        except (
            KeyError,
            TypeError,
            ValueError
        ):

            continue

    valid_candles.sort(
        key=lambda candle:
            candle["time"]
    )

    if len(valid_candles) < 35:

        raise Exception(
            "Not enough valid candles for "
            + symbol
        )

    return valid_candles


# ======================================================
# CONVERT OTCHARTS TIME
# ======================================================

def convert_otcharts_time(timestamp):

    raw_datetime = (
        datetime.fromtimestamp(
            int(timestamp),
            tz=timezone.utc
        )
    )

    corrected_datetime = (
        raw_datetime
        + timedelta(
            hours=
                OTCHARTS_TIME_OFFSET_HOURS
        )
    )

    return (
        raw_datetime,
        corrected_datetime
    )


# ======================================================
# CHECK CANDLE GAPS
# ======================================================

def check_candle_gaps(candles):

    gaps = []

    for i in range(
        1,
        len(candles)
    ):

        previous_time = int(
            candles[i - 1]["time"]
        )

        current_time = int(
            candles[i]["time"]
        )

        difference = (
            current_time
            - previous_time
        )

        if difference != TIMEFRAME_SECONDS:

            gaps.append({
                "index":
                    i,

                "difference_seconds":
                    difference
            })

    return gaps


# ======================================================
# GET COMPLETED CANDLES
# ======================================================

def get_completed_candles(
    candles,
    current_utc
):

    if not candles:

        raise Exception(
            "No candles available"
        )

    latest_candle = candles[-1]

    (
        latest_raw_datetime,
        latest_corrected_datetime
    ) = convert_otcharts_time(
        latest_candle["time"]
    )

    latest_candle_end = (
        latest_corrected_datetime
        + timedelta(
            seconds=
                TIMEFRAME_SECONDS
        )
    )

    latest_candle_complete = (
        current_utc
        >= latest_candle_end
    )

    if latest_candle_complete:

        completed_candles = candles

    else:

        # Never analyze the currently forming candle.
        completed_candles = candles[:-1]

    if len(completed_candles) < 35:

        raise Exception(
            "Not enough completed candles"
        )

    return {
        "candles":
            completed_candles,

        "latest_candle_complete":
            latest_candle_complete,

        "latest_raw_datetime":
            latest_raw_datetime,

        "latest_corrected_datetime":
            latest_corrected_datetime,

        "latest_candle_end":
            latest_candle_end
    }


# ======================================================
# SIGNAL STRENGTH
# ======================================================

def get_signal_strength(analysis):

    try:

        value = int(
            round(
                float(
                    analysis.get(
                        "confidence",
                        0
                    )
                )
            )
        )

        return max(
            0,
            min(
                100,
                value
            )
        )

    except (
        TypeError,
        ValueError
    ):

        confirmations = int(
            analysis.get(
                "confirmations",
                0
            )
        )

        total = int(
            analysis.get(
                "total_confirmations",
                5
            )
        )

        if total <= 0:

            return 0

        value = round(
            (
                confirmations
                / total
            )
            * 100
        )

        return max(
            0,
            min(
                100,
                value
            )
        )


# ======================================================
# ANALYZE ONE SYMBOL
# ======================================================

def analyze_symbol(symbol):

    pair_name = SYMBOLS[symbol]

    start_time = datetime.now(
        timezone.utc
    )

    try:

        candles = download_otc_candles(
            symbol,
            CANDLE_LIMIT
        )

        current_utc = datetime.now(
            timezone.utc
        )

        gaps = check_candle_gaps(
            candles
        )

        latest_candle = candles[-1]

        (
            raw_datetime,
            corrected_datetime
        ) = convert_otcharts_time(
            latest_candle["time"]
        )

        candle_age_seconds = (
            current_utc
            - corrected_datetime
        ).total_seconds()

        data_fresh = (
            0
            <= candle_age_seconds
            <= MAX_CANDLE_AGE_SECONDS
        )

        completed_info = (
            get_completed_candles(
                candles,
                current_utc
            )
        )

        analysis_candles = (
            completed_info[
                "candles"
            ]
        )

        analysis = analyze_candles(
            analysis_candles
        )

        signal = str(
            analysis.get(
                "signal",
                ""
            )
        ).upper()

        # Fallback if Analysis.py does not return BUY/SELL.
        if signal not in [
            "BUY",
            "SELL"
        ]:

            buy_score = int(
                analysis.get(
                    "buy_score",
                    0
                )
            )

            sell_score = int(
                analysis.get(
                    "sell_score",
                    0
                )
            )

            if buy_score >= sell_score:

                signal = "BUY"

            else:

                signal = "SELL"

        signal_strength = (
            get_signal_strength(
                analysis
            )
        )

        usable_data = (
            data_fresh
            and len(gaps) == 0
        )

        response_ms = round(
            (
                datetime.now(
                    timezone.utc
                )
                - start_time
            ).total_seconds()
            * 1000,
            1
        )

        return {
            "success":
                True,

            "symbol":
                symbol,

            "pair":
                pair_name,

            "signal":
                signal,

            "signal_strength":
                signal_strength,

            "confidence":
                signal_strength,

            "confidence_type":
                "signal strength",

            "usable_data":
                usable_data,

            "data_fresh":
                data_fresh,

            "candle_gaps":
                len(gaps),

            "candles_received":
                len(candles),

            "completed_candles_used":
                len(analysis_candles),

            "latest_candle_complete":
                completed_info[
                    "latest_candle_complete"
                ],

            "candle_age_seconds":
                round(
                    candle_age_seconds,
                    2
                ),

            "response_ms":
                response_ms,

            "raw_otcharts_time":
                raw_datetime.isoformat(),

            "corrected_candle_time_utc":
                corrected_datetime.isoformat(),

            "analysis":
                analysis
        }

    except Exception as error:

        return {
            "success":
                False,

            "symbol":
                symbol,

            "pair":
                pair_name,

            "usable_data":
                False,

            "error":
                str(error)
        }


# ======================================================
# SCAN ALL PAIRS IN PARALLEL
# ======================================================

def scan_all_pairs():

    results = []

    # All four API calls happen concurrently.
    with ThreadPoolExecutor(
        max_workers=len(SYMBOLS)
    ) as executor:

        jobs = {
            executor.submit(
                analyze_symbol,
                symbol
            ): symbol

            for symbol in SYMBOLS
        }

        for future in as_completed(
            jobs
        ):

            symbol = jobs[future]

            try:

                result = (
                    future.result()
                )

            except Exception as error:

                result = {
                    "success":
                        False,

                    "symbol":
                        symbol,

                    "pair":
                        SYMBOLS[symbol],

                    "usable_data":
                        False,

                    "error":
                        str(error)
                }

            results.append(
                result
            )

    return results


# ======================================================
# CHOOSE STRONGEST VALID SIGNAL
# ======================================================

def choose_best_signal(results):

    usable_results = [
        result

        for result in results

        if (
            result.get(
                "success"
            ) is True

            and result.get(
                "usable_data"
            ) is True

            and result.get(
                "signal"
            ) in [
                "BUY",
                "SELL"
            ]
        )
    ]

    if not usable_results:

        return None

    usable_results.sort(
        key=lambda result:
            result.get(
                "signal_strength",
                0
            ),
        reverse=True
    )

    return usable_results[0]


# ======================================================
# CREATE SIGNAL MESSAGE
# ======================================================

def create_signal_message(best):

    signal = best["signal"]

    if signal == "BUY":

        icon = "🟢"

    else:

        icon = "🔴"

    return (
        best["pair"]
        + "\n\n"
        + icon
        + " "
        + signal
        + "\n"
        + "Signal Strength: "
        + str(
            best[
                "signal_strength"
            ]
        )
        + "%\n\n"
        + "Timeframe: 5 seconds\n"
        + "Expiry: 5 seconds\n\n"
        + "Data: LIVE ✓"
    )


# ======================================================
# LIVE SIGNAL
# ======================================================

@app.route("/signal")
@app.route("/test-otc")
def otc_signal():

    request_start = datetime.now(
        timezone.utc
    )

    try:

        results = scan_all_pairs()

        best = choose_best_signal(
            results
        )

        total_ms = round(
            (
                datetime.now(
                    timezone.utc
                )
                - request_start
            ).total_seconds()
            * 1000,
            1
        )

        if best is None:

            return {
                "success":
                    True,

                "usable_data":
                    False,

                "data_fresh":
                    False,

                "message":
                    None,

                "reason":
                    (
                        "No verified fresh "
                        "5-second market available"
                    ),

                "timeframe":
                    "5 seconds",

                "expiry_reference":
                    "5 seconds",

                "scan_time_ms":
                    total_ms,

                "markets":
                    results
            }

        message = (
            create_signal_message(
                best
            )
        )

        return {
            "success":
                True,

            "market":
                "Pocket Option OTC",

            "source":
                "OTCharts",

            "timeframe":
                "5 seconds",

            "expiry_reference":
                "5 seconds",

            "prediction_target":
                "next 5-second candle",

            "pair":
                best["pair"],

            "symbol":
                best["symbol"],

            "signal":
                best["signal"],

            "confidence":
                best[
                    "signal_strength"
                ],

            "signal_strength":
                best[
                    "signal_strength"
                ],

            "confidence_type":
                "signal strength",

            "usable_data":
                True,

            "data_fresh":
                True,

            "message":
                message,

            "scan_time_ms":
                total_ms,

            "analysis":
                best["analysis"],

            "markets":
                results
        }

    except Exception as error:

        return {
            "success":
                False,

            "usable_data":
                False,

            "message":
                None,

            "error":
                str(error)
        }, 500


# ======================================================
# SCAN ALL LIVE MARKETS
# ======================================================

@app.route("/scan")
def scan():

    start_time = datetime.now(
        timezone.utc
    )

    results = scan_all_pairs()

    best = choose_best_signal(
        results
    )

    elapsed_ms = round(
        (
            datetime.now(
                timezone.utc
            )
            - start_time
        ).total_seconds()
        * 1000,
        1
    )

    return {
        "success":
            True,

        "market":
            "Pocket Option OTC",

        "timeframe":
            "5 seconds",

        "expiry":
            "5 seconds",

        "pairs_scanned":
            len(SYMBOLS),

        "scan_time_ms":
            elapsed_ms,

        "best_signal":
            best,

        "markets":
            results
    }


# ======================================================
# BACKTEST ONE PAIR
# ======================================================

def backtest_one_symbol(
    symbol,
    pair_name
):

    try:

        candles = download_otc_candles(
            symbol,
            BACKTEST_CANDLE_LIMIT
        )

        current_utc = datetime.now(
            timezone.utc
        )

        # Remove forming candle.
        completed_info = (
            get_completed_candles(
                candles,
                current_utc
            )
        )

        completed = (
            completed_info[
                "candles"
            ]
        )

        gaps = check_candle_gaps(
            completed
        )

        if len(gaps) > 0:

            return {
                "success":
                    False,

                "symbol":
                    symbol,

                "pair":
                    pair_name,

                "error":
                    "Candle gaps detected",

                "candle_gaps":
                    len(gaps)
            }

        report = run_backtest(
            completed
        )

        selected_strategy = (
            report[
                "selected_strategy"
            ]
        )

        unseen = (
            report[
                "unseen_results"
            ][
                selected_strategy
            ]
        )

        return {
            "success":
                True,

            "symbol":
                symbol,

            "pair":
                pair_name,

            "candles_received":
                len(candles),

            "completed_candles":
                len(completed),

            "candle_gaps":
                len(gaps),

            "selected_strategy":
                selected_strategy,

            "development_win_rate":
                report[
                    "selected_development_win_rate"
                ],

            "development_trades":
                report[
                    "selected_development_trades"
                ],

            "unseen_win_rate":
                unseen[
                    "win_rate"
                ],

            "unseen_trades":
                unseen[
                    "decided_trades"
                ],

            "wins":
                unseen[
                    "wins"
                ],

            "losses":
                unseen[
                    "losses"
                ],

            "draws":
                unseen[
                    "draws"
                ],

            "buy":
                unseen[
                    "buy"
                ],

            "sell":
                unseen[
                    "sell"
                ],

            "full_report":
                report
        }

    except Exception as error:

        return {
            "success":
                False,

            "symbol":
                symbol,

            "pair":
                pair_name,

            "error":
                str(error)
        }


# ======================================================
# MULTI-PAIR 5-SECOND BACKTEST
# ======================================================

@app.route("/backtest")
def backtest():

    start_time = datetime.now(
        timezone.utc
    )

    results = {}

    # Backtest downloads can also run in parallel.
    with ThreadPoolExecutor(
        max_workers=len(SYMBOLS)
    ) as executor:

        jobs = {
            executor.submit(
                backtest_one_symbol,
                symbol,
                pair_name
            ): symbol

            for symbol, pair_name
            in SYMBOLS.items()
        }

        for future in as_completed(
            jobs
        ):

            symbol = jobs[future]

            try:

                result = (
                    future.result()
                )

            except Exception as error:

                result = {
                    "success":
                        False,

                    "symbol":
                        symbol,

                    "pair":
                        SYMBOLS[symbol],

                    "error":
                        str(error)
                }

            results[symbol] = result


    # ==================================================
    # COMBINE UNSEEN RESULTS
    # ==================================================

    combined_wins = 0
    combined_losses = 0

    combined_buy_wins = 0
    combined_buy_losses = 0

    combined_sell_wins = 0
    combined_sell_losses = 0

    ranking = []


    for symbol, result in results.items():

        if not result.get(
            "success"
        ):

            continue

        combined_wins += int(
            result["wins"]
        )

        combined_losses += int(
            result["losses"]
        )


        # BUY
        combined_buy_wins += int(
            result["buy"]["wins"]
        )

        combined_buy_losses += int(
            result["buy"]["losses"]
        )


        # SELL
        combined_sell_wins += int(
            result["sell"]["wins"]
        )

        combined_sell_losses += int(
            result["sell"]["losses"]
        )


        ranking.append({
            "symbol":
                symbol,

            "pair":
                result["pair"],

            "strategy":
                result[
                    "selected_strategy"
                ],

            "unseen_win_rate":
                result[
                    "unseen_win_rate"
                ],

            "unseen_trades":
                result[
                    "unseen_trades"
                ],

            "buy_win_rate":
                result[
                    "buy"
                ][
                    "win_rate"
                ],

            "sell_win_rate":
                result[
                    "sell"
                ][
                    "win_rate"
                ]
        })


    # ==================================================
    # CALCULATE COMBINED RATES
    # ==================================================

    total_decided = (
        combined_wins
        + combined_losses
    )

    if total_decided > 0:

        combined_win_rate = round(
            (
                combined_wins
                / total_decided
            )
            * 100,
            2
        )

    else:

        combined_win_rate = 0


    buy_total = (
        combined_buy_wins
        + combined_buy_losses
    )

    if buy_total > 0:

        combined_buy_rate = round(
            (
                combined_buy_wins
                / buy_total
            )
            * 100,
            2
        )

    else:

        combined_buy_rate = 0


    sell_total = (
        combined_sell_wins
        + combined_sell_losses
    )

    if sell_total > 0:

        combined_sell_rate = round(
            (
                combined_sell_wins
                / sell_total
            )
            * 100,
            2
        )

    else:

        combined_sell_rate = 0


    # Rank highest unseen performance first.
    ranking.sort(
        key=lambda item:
            item[
                "unseen_win_rate"
            ],
        reverse=True
    )


    elapsed_seconds = round(
        (
            datetime.now(
                timezone.utc
            )
            - start_time
        ).total_seconds(),
        2
    )


    return {
        "success":
            True,

        "market":
            "Pocket Option OTC",

        "timeframe":
            "5 seconds",

        "expiry":
            "next 5-second candle",

        "timing_model":
            (
                "signal after completed candle -> "
                "next candle open entry -> "
                "next candle close expiry"
            ),

        "pairs_tested":
            len(SYMBOLS),

        "pair_ranking":
            ranking,

        "combined_unseen": {

            "wins":
                combined_wins,

            "losses":
                combined_losses,

            "trades":
                total_decided,

            "win_rate":
                combined_win_rate,

            "buy": {

                "wins":
                    combined_buy_wins,

                "losses":
                    combined_buy_losses,

                "trades":
                    buy_total,

                "win_rate":
                    combined_buy_rate
            },

            "sell": {

                "wins":
                    combined_sell_wins,

                "losses":
                    combined_sell_losses,

                "trades":
                    sell_total,

                "win_rate":
                    combined_sell_rate
            }
        },

        "backtest_time_seconds":
            elapsed_seconds,

        "results":
            results,

        "important":
            (
                "Historical performance does not "
                "guarantee future results. "
                "Signal strength measures indicator "
                "agreement and is not win probability."
            )
    }


# ======================================================
# START SERVER
# ======================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
