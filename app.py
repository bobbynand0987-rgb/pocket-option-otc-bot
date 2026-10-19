import os
import json
import urllib.request
import urllib.parse
import urllib.error

from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, request

from Analysis import analyze_candles
from Backtest import run_backtest


app = Flask(__name__)


# ======================================================
# SETTINGS
# ======================================================

TIMEFRAME_SECONDS = 5

# Live candles
CANDLE_LIMIT = 60

# Historical candles
BACKTEST_CANDLE_LIMIT = 1000

# 5-second feed freshness limit
MAX_CANDLE_AGE_SECONDS = 20

# Timestamp correction already verified with your feed
OTCHARTS_TIME_OFFSET_HOURS = float(
    os.environ.get(
        "OTCHARTS_TIME_OFFSET_HOURS",
        "-2"
    )
)

# Four pairs confirmed working with your API access
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
# API KEY
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

    req = urllib.request.Request(
        url,
        headers={
            "Authorization":
                "Bearer " + api_key,

            "User-Agent":
                "OTC-5S-Scanner/3.0",

            "Accept":
                "application/json",

            "Connection":
                "keep-alive"
        }
    )

    with urllib.request.urlopen(
        req,
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

        # Do not analyze forming candle
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
# ANALYZE ONE LIVE PAIR
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

        # Safety fallback
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

    except urllib.error.HTTPError as error:

        return {
            "success":
                False,

            "symbol":
                symbol,

            "pair":
                pair_name,

            "usable_data":
                False,

            "http_status":
                error.code,

            "error":
                "HTTP Error "
                + str(error.code)
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
# SCAN ALL 4 PAIRS IN PARALLEL
# ======================================================

def scan_all_pairs():

    results = []

    with ThreadPoolExecutor(
        max_workers=4
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
# SCAN ENDPOINT
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
# SINGLE-PAIR BACKTEST
# ======================================================

@app.route("/backtest")
def backtest():

    # Example:
    # /backtest?symbol=GBPUSD_otc

    symbol = request.args.get(
        "symbol",
        "EURUSD_otc"
    )

    # Only allow confirmed working symbols
    if symbol not in SYMBOLS:

        return {
            "success":
                False,

            "error":
                "Unsupported symbol",

            "allowed_symbols":
                list(
                    SYMBOLS.keys()
                )
        }, 400

    pair_name = SYMBOLS[
        symbol
    ]

    start_time = datetime.now(
        timezone.utc
    )

    try:

        # ----------------------------------------------
        # DOWNLOAD 5-SECOND HISTORY
        # ----------------------------------------------

        candles = download_otc_candles(
            symbol,
            BACKTEST_CANDLE_LIMIT
        )

        current_utc = datetime.now(
            timezone.utc
        )

        # ----------------------------------------------
        # REMOVE FORMING CANDLE
        # ----------------------------------------------

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

        # ----------------------------------------------
        # CHECK GAPS
        # ----------------------------------------------

        gaps = check_candle_gaps(
            completed
        )

        if len(gaps) > 0:

            return {
                "success":
                    False,

                "pair":
                    pair_name,

                "symbol":
                    symbol,

                "error":
                    "Candle gaps detected",

                "candle_gaps":
                    len(gaps)
            }, 502

        # ----------------------------------------------
        # RUN BACKTEST
        # ----------------------------------------------

        report = run_backtest(
            completed
        )

        selected_strategy = (
            report[
                "selected_strategy"
            ]
        )

        selected_unseen = (
            report[
                "unseen_results"
            ][
                selected_strategy
            ]
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

        # ----------------------------------------------
        # RESULT
        # ----------------------------------------------

        return {
            "success":
                True,

            "market":
                "Pocket Option OTC",

            "source":
                "OTCharts",

            "pair":
                pair_name,

            "symbol":
                symbol,

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
                selected_unseen[
                    "win_rate"
                ],

            "unseen_trades":
                selected_unseen[
                    "decided_trades"
                ],

            "wins":
                selected_unseen[
                    "wins"
                ],

            "losses":
                selected_unseen[
                    "losses"
                ],

            "draws":
                selected_unseen[
                    "draws"
                ],

            "buy":
                selected_unseen[
                    "buy"
                ],

            "sell":
                selected_unseen[
                    "sell"
                ],

            "backtest_time_seconds":
                elapsed_seconds,

            "full_report":
                report,

            "important":
                (
                    "Historical results do not "
                    "guarantee future performance. "
                    "Signal strength measures indicator "
                    "agreement, not win probability."
                )
        }

    except urllib.error.HTTPError as error:

        return {
            "success":
                False,

            "pair":
                pair_name,

            "symbol":
                symbol,

            "http_status":
                error.code,

            "error":
                "HTTP Error "
                + str(error.code)
        }, 502

    except Exception as error:

        return {
            "success":
                False,

            "pair":
                pair_name,

            "symbol":
                symbol,

            "error":
                str(error)
        }, 500


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
