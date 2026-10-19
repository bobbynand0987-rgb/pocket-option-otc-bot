import os
import json
import urllib.request
import urllib.parse
import urllib.error

from datetime import datetime, timezone, timedelta
from flask import Flask
from Analysis import analyze_candles


app = Flask(__name__)


# ======================================================
# SETTINGS
# ======================================================

OTC_SYMBOL = "EURUSD_otc"

TIMEFRAME_SECONDS = 60

CANDLE_LIMIT = 1000

# Do not use candles older than this.
MAX_CANDLE_AGE_SECONDS = 180

# Your current OTCharts timestamps are appearing
# approximately 2 hours ahead of actual UTC.
#
# Default correction = -2 hours.
#
# This can later be changed in Render using:
# OTCHARTS_TIME_OFFSET_HOURS
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
# GET OTC CANDLES
# ======================================================

def get_otc_candles():

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

        "limit": CANDLE_LIMIT
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
        timeout=20
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
    # VALIDATE CANDLES
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


    # Analysis.py requires:
    # oldest -> newest

    valid_candles.sort(
        key=lambda candle:
            candle["time"]
    )


    return valid_candles


# ======================================================
# CHECK FOR CANDLE GAPS
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


        # Normal 1-minute difference = 60 seconds.

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

def convert_otcharts_time(
    timestamp
):

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

def get_confidence(
    analysis
):

    # Prefer the confidence generated
    # directly by Analysis.py.

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
# CREATE SIMPLE MESSAGE
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
# MAIN OTC SIGNAL
# ======================================================

@app.route("/signal")
@app.route("/test-otc")
def otc_signal():

    try:

        # ==============================================
        # DOWNLOAD CANDLES
        # ==============================================

        candles = (
            get_otc_candles()
        )


        # ==============================================
        # CHECK CANDLE GAPS
        # ==============================================

        gaps = (
            check_candle_gaps(
                candles
            )
        )


        # ==============================================
        # LATEST CANDLE
        # ==============================================

        latest_candle = (
            candles[-1]
        )


        latest_timestamp = int(
            latest_candle["time"]
        )


        (
            raw_datetime,
            corrected_datetime
        ) = convert_otcharts_time(
            latest_timestamp
        )


        current_utc = (
            datetime.now(
                timezone.utc
            )
        )


        # ==============================================
        # CANDLE AGE
        # ==============================================

        candle_age_seconds = (

            current_utc

            - corrected_datetime

        ).total_seconds()


        candle_age_minutes = round(

            candle_age_seconds
            / 60,

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
        # TECHNICAL ANALYSIS
        # ==============================================

        analysis = (
            analyze_candles(
                candles
            )
        )


        signal = str(
            analysis.get(
                "signal",
                ""
            )
        ).upper()


        confidence = (
            get_confidence(
                analysis
            )
        )


        # ==============================================
        # VALIDATE DIRECTION
        # ==============================================

        if signal not in [
            "BUY",
            "SELL"
        ]:

            # Emergency fallback.
            #
            # Analysis.py should already always
            # produce BUY or SELL.

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

            reason = (
                "OTC data valid"
            )


        else:

            # We still return the technical direction
            # for debugging, but do NOT create a
            # Telegram trading message from stale/
            # broken candle data.

            message = None


            if not data_fresh:

                reason = (
                    "OTC candle freshness check failed"
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


    # ==================================================
    # HTTP ERROR
    # ==================================================

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


    # ==================================================
    # OTHER ERROR
    # ==================================================

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
# START SERVER
# ======================================================

# ======================================================
# OTC HISTORICAL BACKTEST
# ======================================================

@app.route("/backtest")
def backtest():

    try:

        api_key = os.environ.get(
            "OTCHARTS_API_KEY",
            ""
        ).strip()

        if not api_key:
            return {
                "success": False,
                "error": "OTCHARTS_API_KEY is missing"
            }, 500


        # ==============================================
        # REQUEST 1000 OTC CANDLES
        # ==============================================

        params = urllib.parse.urlencode({
            "venue": "otc",
            "symbol": OTC_SYMBOL,
            "tf": TIMEFRAME_SECONDS,
            "limit": 1000
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
                    "OTC-Backtest/1.0",

                "Accept":
                    "application/json"
            }
        )


        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )


        candles = data.get(
            "candles",
            []
        )


        # ==============================================
        # CLEAN CANDLES
        # ==============================================

        clean_candles = []


        for candle in candles:

            try:

                clean_candles.append({
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


        # ==============================================
        # SORT OLDEST -> NEWEST
        # ==============================================

        clean_candles.sort(
            key=lambda candle:
                candle["time"]
        )


        if len(clean_candles) < 100:

            return {
                "success": False,
                "error":
                    "Not enough historical candles",
                "candles_received":
                    len(clean_candles)
            }, 502


        # ==============================================
        # CHECK GAPS
        # ==============================================

        gaps = check_candle_gaps(
            clean_candles
        )


        # ==============================================
        # RUN BACKTEST
        # ==============================================

        report = run_backtest(
            clean_candles
        )


        # ==============================================
        # RESPONSE
        # ==============================================

        return {

            "success": True,

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
                len(clean_candles),

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
                error.read()
                .decode("utf-8")
            )

        except Exception:

            error_body = str(error)


        return {

            "success": False,

            "http_status":
                error.code,

            "error":
                error_body

        }, 502


    except Exception as error:

        return {

            "success": False,

            "error":
                str(error)

        }, 500

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
