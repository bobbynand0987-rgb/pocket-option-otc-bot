import os
import json
import urllib.request
import urllib.parse
import urllib.error

from datetime import datetime, timezone, timedelta
from flask import Flask, request

from Analysis import analyze_candles
from Backtest import run_backtest


app = Flask(__name__)


# ======================================================
# SETTINGS
# ======================================================

CANDLE_LIMIT = 60
BACKTEST_CANDLE_LIMIT = 1000

ALLOWED_TIMEFRAMES = [5, 10, 15, 30, 60]

SYMBOLS = {
    "EURUSD_otc": "EUR/USD OTC",
    "GBPUSD_otc": "GBP/USD OTC",
    "AUDUSD_otc": "AUD/USD OTC",
    "USDJPY_otc": "USD/JPY OTC"
}

OTCHARTS_TIME_OFFSET_HOURS = float(
    os.environ.get(
        "OTCHARTS_TIME_OFFSET_HOURS",
        "-2"
    )
)


# ======================================================
# HOME
# ======================================================

@app.route("/")
def home():

    return {
        "status": "online",
        "bot": "Pocket Option OTC Signal Bot",
        "market": "Pocket Option OTC",
        "pairs": SYMBOLS,
        "timeframes_seconds": ALLOWED_TIMEFRAMES,
        "source": "OTCharts"
    }


# ======================================================
# STATUS
# ======================================================

@app.route("/status")
def status():

    return {
        "success": True,
        "status": "online",
        "market": "Pocket Option OTC",
        "pairs": list(SYMBOLS.values()),
        "timeframes_seconds": ALLOWED_TIMEFRAMES,
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
# DOWNLOAD CANDLES
# ======================================================

def download_otc_candles(
    symbol,
    timeframe,
    limit=CANDLE_LIMIT
):

    api_key = get_api_key()

    params = urllib.parse.urlencode({
        "venue": "otc",
        "symbol": symbol,
        "tf": timeframe,
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
                "OTC-Signal-Bot/4.0",

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
# TIME CORRECTION
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

def check_candle_gaps(
    candles,
    timeframe
):

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

        if difference != timeframe:

            gaps.append({
                "index": i,
                "difference_seconds":
                    difference
            })

    return gaps


# ======================================================
# COMPLETED CANDLES ONLY
# ======================================================

def get_completed_candles(
    candles,
    current_utc,
    timeframe
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
            seconds=timeframe
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
        "latest_candle_complete":
            complete,
        "raw_time": raw,
        "corrected_time": corrected,
        "candle_end": candle_end
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
            min(100, value)
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

        return round(
            confirmations
            / total
            * 100
        )


# ======================================================
# READ USER SELECTION
# ======================================================

def get_request_selection():

    symbol = request.args.get(
        "symbol",
        ""
    ).strip()

    timeframe_text = request.args.get(
        "tf",
        ""
    ).strip()


    if symbol not in SYMBOLS:

        return None, None, (
            "Unsupported symbol. "
            "Choose EURUSD_otc, "
            "GBPUSD_otc, AUDUSD_otc "
            "or USDJPY_otc."
        )


    try:
        timeframe = int(
            timeframe_text
        )

    except ValueError:

        return None, None, (
            "Invalid timeframe."
        )


    if timeframe not in ALLOWED_TIMEFRAMES:

        return None, None, (
            "Timeframe must be "
            "5, 10, 15, 30 or 60 seconds."
        )


    return (
        symbol,
        timeframe,
        None
    )


# ======================================================
# ANALYZE SELECTED MARKET
# ======================================================

def analyze_selected_market(
    symbol,
    timeframe
):

    pair_name = SYMBOLS[symbol]

    start = datetime.now(
        timezone.utc
    )

    candles = download_otc_candles(
        symbol,
        timeframe,
        CANDLE_LIMIT
    )

    current_utc = datetime.now(
        timezone.utc
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


    # Freshness changes with timeframe.
    max_age = max(
        20,
        timeframe * 3
    )

    data_fresh = (
        0
        <= age_seconds
        <= max_age
    )


    completed_info = (
        get_completed_candles(
            candles,
            current_utc,
            timeframe
        )
    )

    completed = (
        completed_info["candles"]
    )


    gaps = check_candle_gaps(
        completed,
        timeframe
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


    if signal not in [
        "BUY",
        "SELL"
    ]:

        raise Exception(
            "Analysis did not produce "
            "a valid BUY/SELL signal"
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
            - start
        ).total_seconds()
        * 1000,
        1
    )


    return {
        "success": True,

        "market":
            "Pocket Option OTC",

        "source":
            "OTCharts",

        "pair":
            pair_name,

        "symbol":
            symbol,

        "timeframe_seconds":
            timeframe,

        "expiry_seconds":
            timeframe,

        "prediction_target":
            "next completed "
            + str(timeframe)
            + "-second candle",

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
                "latest_candle_complete"
            ],

        "candle_age_seconds":
            round(
                age_seconds,
                2
            ),

        "response_ms":
            elapsed_ms,

        "raw_otcharts_time":
            raw.isoformat(),

        "corrected_candle_time_utc":
            corrected.isoformat(),

        "analysis":
            analysis
    }


# ======================================================
# SELECTED SIGNAL
# ======================================================

@app.route("/signal")
@app.route("/test-otc")
def signal():

    symbol, timeframe, error = (
        get_request_selection()
    )


    if error:

        return {
            "success": False,
            "error": error,
            "example":
                "/signal?symbol=USDJPY_otc&tf=5"
        }, 400


    try:

        result = analyze_selected_market(
            symbol,
            timeframe
        )

        return result


    except urllib.error.HTTPError as error:

        return {
            "success": False,
            "symbol": symbol,
            "timeframe_seconds":
                timeframe,
            "http_status":
                error.code,
            "error":
                "OTCharts HTTP Error "
                + str(error.code)
        }, 502


    except Exception as error:

        return {
            "success": False,
            "symbol": symbol,
            "timeframe_seconds":
                timeframe,
            "error": str(error)
        }, 500


# ======================================================
# BACKTEST ONE SELECTED PAIR/TIMEFRAME
# ======================================================

@app.route("/backtest")
def backtest():

    symbol = request.args.get(
        "symbol",
        "EURUSD_otc"
    ).strip()

    try:
        timeframe = int(
            request.args.get(
                "tf",
                "5"
            )
        )

    except ValueError:

        return {
            "success": False,
            "error":
                "Invalid timeframe"
        }, 400


    if symbol not in SYMBOLS:

        return {
            "success": False,
            "error":
                "Unsupported symbol"
        }, 400


    if timeframe not in ALLOWED_TIMEFRAMES:

        return {
            "success": False,
            "error":
                "Timeframe must be "
                "5, 10, 15, 30 or 60"
        }, 400


    start = datetime.now(
        timezone.utc
    )


    try:

        candles = download_otc_candles(
            symbol,
            timeframe,
            BACKTEST_CANDLE_LIMIT
        )

        current_utc = datetime.now(
            timezone.utc
        )

        completed_info = (
            get_completed_candles(
                candles,
                current_utc,
                timeframe
            )
        )

        completed = (
            completed_info["candles"]
        )

        gaps = check_candle_gaps(
            completed,
            timeframe
        )


        if gaps:

            return {
                "success": False,
                "pair":
                    SYMBOLS[symbol],
                "symbol":
                    symbol,
                "timeframe_seconds":
                    timeframe,
                "error":
                    "Candle gaps detected",
                "candle_gaps":
                    len(gaps)
            }, 502


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


        elapsed = round(
            (
                datetime.now(
                    timezone.utc
                )
                - start
            ).total_seconds(),
            2
        )


        return {
            "success": True,

            "pair":
                SYMBOLS[symbol],

            "symbol":
                symbol,

            "timeframe_seconds":
                timeframe,

            "expiry_seconds":
                timeframe,

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
                unseen["win_rate"],

            "unseen_trades":
                unseen[
                    "decided_trades"
                ],

            "wins":
                unseen["wins"],

            "losses":
                unseen["losses"],

            "draws":
                unseen["draws"],

            "buy":
                unseen["buy"],

            "sell":
                unseen["sell"],

            "backtest_time_seconds":
                elapsed,

            "full_report":
                report,

            "important":
                (
                    "Historical results do not "
                    "guarantee future results."
                )
        }


    except Exception as error:

        return {
            "success": False,
            "pair":
                SYMBOLS[symbol],
            "symbol":
                symbol,
            "timeframe_seconds":
                timeframe,
            "error":
                str(error)
        }, 500


# ======================================================
# START
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
