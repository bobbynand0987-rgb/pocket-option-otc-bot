import os
import json
import urllib.request
import urllib.parse
import urllib.error

from datetime import datetime, timezone
from flask import Flask
from Analysis import analyze_candles


app = Flask(__name__)


# ======================================================
# SETTINGS
# ======================================================

OTC_SYMBOL = "EURUSD_otc"
TIMEFRAME_SECONDS = 60
CANDLE_LIMIT = 50

# Maximum acceptable age of latest candle.
MAX_CANDLE_AGE_SECONDS = 180


# ======================================================
# HOME
# ======================================================

@app.route("/")
def home():
    return {
        "status": "online",
        "bot": "OTC Signal Assistant",
        "market": "Pocket Option OTC",
        "symbol": OTC_SYMBOL,
        "timeframe": "1 minute",
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
        "symbol": OTC_SYMBOL,
        "timeframe": "1 minute",
        "source": "OTCharts"
    }


# ======================================================
# GET OTC CANDLES
# ======================================================

def get_otc_candles():

    api_key = os.environ.get(
        "OTCHARTS_API_KEY", ""
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

        data = json.loads(
            response.read().decode("utf-8")
        )


    candles = data.get("candles", [])


    if not candles:
        raise Exception(
            "No OTC candles returned"
        )


    # Make sure candles are chronological:
    # oldest -> newest

    candles.sort(
        key=lambda candle:
            int(candle["time"])
    )


    return candles, data


# ======================================================
# CONFIDENCE / SIGNAL STRENGTH
# ======================================================

def calculate_signal_strength(analysis):

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


    strength = round(
        (confirmations / total) * 100
    )


    return max(
        0,
        min(100, strength)
    )


# ======================================================
# OTC SIGNAL
# ======================================================

@app.route("/signal")
@app.route("/test-otc")
def otc_signal():

    try:

        candles, raw_data = (
            get_otc_candles()
        )


        # ==============================================
        # ENOUGH DATA?
        # ==============================================

        if len(candles) < 35:

            return {
                "success": False,
                "signal": "WAIT",
                "reason":
                    "Not enough OTC candles",
                "candles_received":
                    len(candles)
            }, 502


        # ==============================================
        # LATEST CANDLE
        # ==============================================

        latest_candle = candles[-1]

        latest_timestamp = int(
            latest_candle["time"]
        )


        latest_datetime = (
            datetime.fromtimestamp(
                latest_timestamp,
                tz=timezone.utc
            )
        )


        current_utc = datetime.now(
            timezone.utc
        )


        candle_age_seconds = (
            current_utc -
            latest_datetime
        ).total_seconds()


        candle_age_minutes = round(
            candle_age_seconds / 60,
            2
        )


        # ==============================================
        # FRESHNESS CHECK
        # ==============================================

        data_fresh = (
            0 <= candle_age_seconds
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
                "WAIT"
            )
        ).upper()


        strength = (
            calculate_signal_strength(
                analysis
            )
        )


        # ==============================================
        # SAFETY CHECKS
        # ==============================================

        if not data_fresh:

            signal = "WAIT"

            reason = (
                "OTC candle data is stale"
            )

        elif signal not in [
            "BUY",
            "SELL"
        ]:

            signal = "WAIT"

            reason = (
                "No strong BUY/SELL setup"
            )

        else:

            reason = (
                "Signal conditions confirmed"
            )


        # ==============================================
        # SIMPLE TELEGRAM-READY MESSAGE
        # ==============================================

        if signal in [
            "BUY",
            "SELL"
        ]:

            message = (
                "EUR/USD OTC\n\n"
                + signal
                + "\n"
                + "Signal strength: "
                + str(strength)
                + "%\n\n"
                + "Expiry: 1 minute"
            )

        else:

            # Telegram can use this value
            # to remain silent.

            message = None


        # ==============================================
        # RESPONSE
        # ==============================================

        return {

            "success": True,

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

            # This is signal strength,
            # NOT guaranteed win probability.
            "confidence":
                strength,

            "signal_strength":
                strength,

            "reason":
                reason,

            "data_fresh":
                data_fresh,

            "latest_candle_time_utc":
                latest_datetime.isoformat(),

            "candle_age_seconds":
                round(
                    candle_age_seconds,
                    1
                ),

            "candle_age_minutes":
                candle_age_minutes,

            "candles_received":
                len(candles),

            "message":
                message,

            "analysis":
                analysis
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

            "signal": "WAIT",

            "message": None,

            "http_status":
                error.code,

            "error":
                error_body

        }, 502


    except Exception as error:

        return {

            "success": False,

            "signal": "WAIT",

            "message": None,

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
