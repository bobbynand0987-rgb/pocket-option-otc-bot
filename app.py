import os
import json
import urllib.request
import urllib.parse
import urllib.error

from datetime import datetime, timezone, timedelta
from flask import Flask

from Analysis import analyze_candles
from Backtest import run_backtest


app = Flask(__name__)


# ======================================================
# SETTINGS
# ======================================================

OTC_SYMBOL = "EURUSD_otc"
TIMEFRAME_SECONDS = 60

# Live signal only needs 50 candles.
CANDLE_LIMIT = 50

# Historical backtest uses 1000 candles.
BACKTEST_CANDLE_LIMIT = 1000

# Reject live data older than this.
MAX_CANDLE_AGE_SECONDS = 180

# OTCharts timestamps currently appear about
# 2 hours ahead of actual UTC in your feed.
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
        "bot": "Pocket Option OTC Signal Assistant",
        "market": "Pocket Option OTC",
        "symbol": OTC_SYMBOL,
        "timeframe": "1 minute",
        "expiry_reference": "1 minute",
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
        "pair": "EUR/USD OTC",
        "symbol": OTC_SYMBOL,
        "timeframe": "1 minute",
        "expiry_reference": "1 minute",
        "source": "OTCharts"
    }


# ======================================================
# DOWNLOAD OTC CANDLES
# ======================================================

def download_otc_candles(limit):

    api_key = os.environ.get(
        "OTCHARTS_API_KEY",
        ""
    ).strip()

    if not api_key:
        raise Exception(
            "OTCHARTS_API_KEY is missing"
        )

    params = urllib.parse.urlencode({
        "venue": "otc",
        "symbol": OTC_SYMBOL,
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
                "OTC-Signal-Assistant/1.0",

            "Accept":
                "application/json"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
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
            "No OTC candles returned"
        )

    # ==================================================
    # CLEAN AND VALIDATE
    # ==================================================

    valid_candles = []

    for candle in candles:

        try:

            clean_candle = {
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
            }

            valid_candles.append(
                clean_candle
            )

        except (
            KeyError,
            TypeError,
            ValueError
        ):

            continue

    if len(valid_candles) < 35:

        raise Exception(
            "Not enough valid OTC candles"
        )

    # Analysis.py expects oldest -> newest.

    valid_candles.sort(
        key=lambda candle:
            candle["time"]
    )

    return valid_candles


# ======================================================
# LIVE CANDLES
# ======================================================

def get_otc_candles():

    return download_otc_candles(
        CANDLE_LIMIT
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

        # Normal 1-minute candle difference = 60 sec.

        if difference != TIMEFRAME_SECONDS:

            gaps.append({
                "index": i,
                "difference_seconds":
                    difference
            })

    return gaps


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
# SIGNAL CONFIDENCE
# ======================================================

def get_confidence(analysis):

    # Prefer confidence from Analysis.py.

    if (
        analysis.get("confidence")
        is not None
    ):

        try:

            confidence = int(
                round(
                    float(
                        analysis["confidence"]
                    )
                )
            )

            return max(
                0,
                min(
                    100,
                    confidence
                )
            )

        except (
            TypeError,
            ValueError
        ):

            pass

    # Fallback calculation.

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

    confidence = round(
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
            confidence
        )
    )


# ======================================================
# CREATE TELEGRAM SIGNAL MESSAGE
# ======================================================

def create_signal_message(
    signal,
    confidence
):

    return (
        "EUR/USD OTC\n\n"
        + signal
        + "\n"
        + "Confidence: "
        + str(confidence)
        + "%\n\n"
        + "Expiry: 1 minute"
    )


# ======================================================
# LIVE OTC SIGNAL
# ======================================================

@app.route("/signal")
@app.route("/test-otc")
def otc_signal():

    try:

        # ==============================================
        # DOWNLOAD 50 LIVE CANDLES
        # ==============================================

        candles = get_otc_candles()

        # ==============================================
        # CHECK GAPS
        # ==============================================

        gaps = check_candle_gaps(
            candles
        )

        # ==============================================
        # LATEST CANDLE
        # ==============================================

        latest_candle = candles[-1]

        latest_timestamp = int(
            latest_candle["time"]
        )

        (
            raw_datetime,
            corrected_datetime
        ) = convert_otcharts_time(
            latest_timestamp
        )

        current_utc = datetime.now(
            timezone.utc
        )

        # ==============================================
        # CANDLE AGE
        # ==============================================

        candle_age_seconds = (
            current_utc
            - corrected_datetime
        ).total_seconds()

        candle_age_minutes = round(
            candle_age_seconds / 60,
            2
        )

        # ==============================================
        # FRESHNESS
        # ==============================================

        data_fresh = (
            0
            <= candle_age_seconds
            <= MAX_CANDLE_AGE_SECONDS
        )

        # ==============================================
        # ANALYSIS
        # ==============================================

        analysis = analyze_candles(
            candles
        )

        signal = str(
            analysis.get(
                "signal",
                ""
            )
        ).upper()

        confidence = get_confidence(
            analysis
        )

        # ==============================================
        # ENSURE BUY OR SELL
        # ==============================================

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

        # ==============================================
        # DATA SAFETY
        # ==============================================

        usable_data = (
            data_fresh
            and len(gaps) == 0
        )

        if usable_data:

            message = (
                create_signal_message(
                    signal,
                    confidence
                )
            )

            reason = "OTC data valid"

        else:

            # Keep technical direction for debugging,
            # but don't send a trading message when
            # market data fails validation.

            message = None

            if not data_fresh:

                reason = (
                    "OTC candle freshness "
                    "check failed"
                )

            elif len(gaps) > 0:

                reason = (
                    "OTC candle gaps detected"
                )

            else:

                reason = (
                    "OTC data unavailable"
                )

        # ==============================================
        # RESPONSE
        # ==============================================

        return {
            "success":
                True,

            "market":
                "Pocket Option OTC",

            "source":
                "OTCharts",

            "symbol":
                OTC_SYMBOL,

            "timeframe":
                "1 minute",

            "expiry_reference":
                "1 minute",

            "signal":
                signal,

            "confidence":
                confidence,

            "confidence_type":
                "signal strength",

            "usable_data":
                usable_data,

            "data_fresh":
                data_fresh,

            "reason":
                reason,

            "candles_received":
                len(candles),

            "candle_gaps":
                len(gaps),

            "raw_otcharts_time":
                raw_datetime.isoformat(),

            "corrected_candle_time_utc":
                corrected_datetime.isoformat(),

            "current_time_utc":
                current_utc.isoformat(),

            "candle_age_seconds":
                round(
                    candle_age_seconds,
                    1
                ),

            "candle_age_minutes":
                candle_age_minutes,

            "timestamp_offset_hours":
                OTCHARTS_TIME_OFFSET_HOURS,

            "message":
                message,

            "analysis":
                analysis
        }

    except urllib.error.HTTPError as error:

        try:

            error_body = (
                error
                .read()
                .decode("utf-8")
            )

        except Exception:

            error_body = str(
                error
            )

        return {
            "success":
                False,

            "message":
                None,

            "http_status":
                error.code,

            "error":
                error_body
        }, 502

    except Exception as error:

        return {
            "success":
                False,

            "message":
                None,

            "error":
                str(error)
        }, 500


# ======================================================
# HISTORICAL BACKTEST
# ======================================================

@app.route("/backtest")
def backtest():

    try:

        # ==============================================
        # DOWNLOAD 1000 HISTORICAL CANDLES
        # ==============================================

        candles = download_otc_candles(
            BACKTEST_CANDLE_LIMIT
        )

        # ==============================================
        # CHECK DATA
        # ==============================================

        if len(candles) < 100:

            return {
                "success": False,
                "error":
                    "Not enough historical candles",
                "candles_received":
                    len(candles)
            }, 502

        gaps = check_candle_gaps(
            candles
        )

        # ==============================================
        # RUN BACKTEST
        # ==============================================

        report = run_backtest(
            candles
        )

        # ==============================================
        # RESPONSE
        # ==============================================

        return {
            "success":
                True,

            "market":
                "Pocket Option OTC",

            "symbol":
                OTC_SYMBOL,

            "timeframe":
                "1 minute",

            "expiry":
                "1 minute",

            "source":
                "OTCharts",

            "candles_received":
                len(candles),

            "candle_gaps":
                len(gaps),

            "backtest":
                report,

            "important":
                (
                    "Historical backtest results "
                    "do not guarantee future performance."
                )
        }

    except urllib.error.HTTPError as error:

        try:

            error_body = (
                error
                .read()
                .decode("utf-8")
            )

        except Exception:

            error_body = str(
                error
            )

        return {
            "success":
                False,

            "http_status":
                error.code,

            "error":
                error_body
        }, 502

    except Exception as error:

        return {
            "success":
                False,

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
