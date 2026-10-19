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
# 5-SECOND OTC SETTINGS
# ======================================================

TIMEFRAME_SECONDS = 5

CANDLE_LIMIT = 60
BACKTEST_CANDLE_LIMIT = 1000

# 5-second data must be very recent.
MAX_CANDLE_AGE_SECONDS = 20

# Keep the correction that worked with your current feed.
OTCHARTS_TIME_OFFSET_HOURS = float(
    os.environ.get(
        "OTCHARTS_TIME_OFFSET_HOURS",
        "-2"
    )
)

# Five OTC currency pairs.
# If OTCharts does not provide one of these for your plan,
# that pair is skipped automatically.
SYMBOLS = {
    "EURUSD_otc": "EUR/USD OTC",
    "GBPUSD_otc": "GBP/USD OTC",
    "USDJPY_otc": "USD/JPY OTC",
    "AUDUSD_otc": "AUD/USD OTC",
    "USDCAD_otc": "USD/CAD OTC"
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
        "scanner": "5-pair OTC scanner",
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
# DOWNLOAD CANDLES FOR ONE SYMBOL
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
                "OTC-5S-Scanner/1.0",

            "Accept":
                "application/json",

            "Connection":
                "keep-alive"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=8
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
            "No candles returned"
        )

    valid = []

    for candle in candles:

        try:

            valid.append({
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

    valid.sort(
        key=lambda x: x["time"]
    )

    if len(valid) < 35:
        raise Exception(
            "Not enough valid candles"
        )

    return valid


# ======================================================
# TIME CONVERSION
# ======================================================

def convert_otcharts_time(timestamp):

    raw = datetime.fromtimestamp(
        int(timestamp),
        tz=timezone.utc
    )

    corrected = (
        raw
        + timedelta(
            hours=
                OTCHARTS_TIME_OFFSET_HOURS
        )
    )

    return raw, corrected


# ======================================================
# CHECK GAPS
# ======================================================

def check_candle_gaps(candles):

    gaps = []

    for i in range(
        1,
        len(candles)
    ):

        difference = (
            int(candles[i]["time"])
            - int(candles[i - 1]["time"])
        )

        if difference != TIMEFRAME_SECONDS:

            gaps.append({
                "index": i,
                "difference_seconds":
                    difference
            })

    return gaps


# ======================================================
# REMOVE FORMING 5-SECOND CANDLE
# ======================================================

def get_completed_candles(
    candles,
    current_utc
):

    if not candles:
        raise Exception(
            "No candles available"
        )

    latest = candles[-1]

    raw, corrected = (
        convert_otcharts_time(
            latest["time"]
        )
    )

    candle_end = (
        corrected
        + timedelta(
            seconds=
                TIMEFRAME_SECONDS
        )
    )

    complete = (
        current_utc >= candle_end
    )

    if complete:
        completed = candles
    else:
        completed = candles[:-1]

    if len(completed) < 35:
        raise Exception(
            "Not enough completed candles"
        )

    return {
        "candles": completed,
        "latest_complete": complete,
        "raw": raw,
        "corrected": corrected,
        "end": candle_end
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

        return 0


# ======================================================
# ANALYZE ONE PAIR
# ======================================================

def analyze_symbol(symbol):

    pair_name = SYMBOLS[symbol]

    try:

        start_time = datetime.now(
            timezone.utc
        )

        candles = (
            download_otc_candles(
                symbol
            )
        )

        current_utc = datetime.now(
            timezone.utc
        )

        gaps = check_candle_gaps(
            candles
        )

        latest = candles[-1]

        raw, corrected = (
            convert_otcharts_time(
                latest["time"]
            )
        )

        age_seconds = (
            current_utc
            - corrected
        ).total_seconds()

        data_fresh = (
            0
            <= age_seconds
            <= MAX_CANDLE_AGE_SECONDS
        )

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

        analysis = analyze_candles(
            completed
        )

        signal = str(
            analysis.get(
                "signal",
                ""
            )
        ).upper()

        # Safety fallback.
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

            signal = (
                "BUY"
                if buy_score >= sell_score
                else "SELL"
            )

        strength = (
            get_signal_strength(
                analysis
            )
        )

        usable = (
            data_fresh
            and len(gaps) == 0
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
            "success": True,

            "symbol":
                symbol,

            "pair":
                pair_name,

            "signal":
                signal,

            "signal_strength":
                strength,

            "confidence":
                strength,

            "confidence_type":
                "signal strength",

            "usable_data":
                usable,

            "data_fresh":
                data_fresh,

            "candle_gaps":
                len(gaps),

            "candles_received":
                len(candles),

            "completed_candles_used":
                len(completed),

            "latest_candle_complete":
                completed_info[
                    "latest_complete"
                ],

            "candle_age_seconds":
                round(
                    age_seconds,
                    2
                ),

            "response_ms":
                elapsed_ms,

            "analysis":
                analysis
        }

    except Exception as error:

        return {
            "success": False,
            "symbol": symbol,
            "pair": pair_name,
            "usable_data": False,
            "error": str(error)
        }


# ======================================================
# SCAN ALL 5 PAIRS IN PARALLEL
# ======================================================

def scan_all_pairs():

    results = []

    # Parallel requests make this much faster
    # than downloading each market one-by-one.

    with ThreadPoolExecutor(
        max_workers=5
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

            try:
                result = future.result()

            except Exception as error:

                symbol = jobs[future]

                result = {
                    "success": False,
                    "symbol": symbol,
                    "pair":
                        SYMBOLS[symbol],
                    "usable_data": False,
                    "error": str(error)
                }

            results.append(
                result
            )

    return results


# ======================================================
# CHOOSE STRONGEST SIGNAL
# ======================================================

def choose_best_signal(results):

    usable = [
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

    if not usable:
        return None

    usable.sort(
        key=lambda item:
            item.get(
                "signal_strength",
                0
            ),
        reverse=True
    )

    return usable[0]


# ======================================================
# TELEGRAM-STYLE MESSAGE
# ======================================================

def create_signal_message(best):

    signal = best["signal"]

    icon = (
        "🟢"
        if signal == "BUY"
        else "🔴"
    )

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
        + "Scanned: 5 OTC pairs"
    )


# ======================================================
# MAIN 5-SECOND SIGNAL
# ======================================================

@app.route("/signal")
@app.route("/test-otc")
def signal():

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
                "success": True,
                "usable_data": False,
                "message": None,
                "reason":
                    "No verified fresh 5-second market available",
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
            "success": True,

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
            "success": False,
            "usable_data": False,
            "message": None,
            "error": str(error)
        }, 500


# ======================================================
# SCAN ENDPOINT
# Shows all markets, useful for testing.
# ======================================================

@app.route("/scan")
def scan():

    start = datetime.now(
        timezone.utc
    )

    results = scan_all_pairs()

    elapsed_ms = round(
        (
            datetime.now(
                timezone.utc
            )
            - start
        ).total_seconds()
        * 1000,
        1
    )

    return {
        "success": True,
        "timeframe":
            "5 seconds",
        "expiry":
            "5 seconds",
        "scan_time_ms":
            elapsed_ms,
        "markets":
            results
    }


# ======================================================
# BACKTEST ONE SYMBOL
# ======================================================

@app.route("/backtest")
def backtest():

    # Start with EUR/USD OTC for controlled
    # 5-second strategy testing.

    symbol = "EURUSD_otc"

    try:

        candles = (
            download_otc_candles(
                symbol,
                BACKTEST_CANDLE_LIMIT
            )
        )

        current_utc = datetime.now(
            timezone.utc
        )

        # Exclude current forming candle.
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

        report = run_backtest(
            completed
        )

        return {
            "success": True,
            "market":
                "Pocket Option OTC",
            "symbol":
                symbol,
            "pair":
                "EUR/USD OTC",
            "timeframe":
                "5 seconds",
            "expiry":
                "next 5-second candle",
            "candles_received":
                len(candles),
            "completed_candles":
                len(completed),
            "candle_gaps":
                len(gaps),
            "backtest":
                report,
            "important":
                (
                    "Historical results do not "
                    "guarantee future performance."
                )
        }

    except Exception as error:

        return {
            "success": False,
            "error": str(error)
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
