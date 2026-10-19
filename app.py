import os
import json
import urllib.request
import urllib.parse
import urllib.error

from datetime import datetime, timezone
from flask import Flask
from Analysis import analyze_candles


app = Flask(__name__)


@app.route("/")
def home():
    return {
        "status": "online",
        "bot": "Forex Signal Assistant",
        "market": "Regular Forex",
        "source": "Twelve Data"
    }


@app.route("/status")
def status():
    return {
        "status": "online",
        "market": "Regular Forex",
        "pair": "EUR/USD",
        "timeframe": "1 minute",
        "source": "Twelve Data"
    }


@app.route("/test-forex")
def test_forex():

    api_key = os.environ.get(
        "TWELVE_DATA_API_KEY", ""
    ).strip()

    if not api_key:
        return {
            "success": False,
            "error": "TWELVE_DATA_API_KEY is missing"
        }, 500


    # ==========================================
    # TWELVE DATA REQUEST
    # ==========================================

    params = urllib.parse.urlencode({
        "symbol": "EUR/USD",
        "interval": "1min",
        "outputsize": 50,
        "timezone": "UTC",
        "apikey": api_key
    })

    url = (
        "https://api.twelvedata.com/time_series?"
        + params
    )


    try:

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent":
                    "Forex-Signal-Assistant/1.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )


        # ======================================
        # API ERROR
        # ======================================

        if data.get("status") == "error":

            return {
                "success": False,
                "error": data.get(
                    "message",
                    "Twelve Data error"
                )
            }, 502


        candles = data.get("values", [])


        if not candles:

            return {
                "success": False,
                "error": "No candle data returned"
            }, 502


        # Twelve Data returns newest -> oldest.
        # Analysis.py needs oldest -> newest.

        candles.reverse()


        if len(candles) < 35:

            return {
                "success": False,
                "error":
                    "Not enough candles for analysis",
                "candles_received":
                    len(candles)
            }, 502


        # ======================================
        # LATEST CANDLE
        # ======================================

        latest_candle = candles[-1]

        latest_candle_time = (
            latest_candle.get("datetime")
        )


        if not latest_candle_time:

            return {
                "success": False,
                "error":
                    "Latest candle has no timestamp"
            }, 502


        # ======================================
        # FRESHNESS CHECK
        # ======================================

        candle_datetime = datetime.strptime(
            latest_candle_time,
            "%Y-%m-%d %H:%M:%S"
        ).replace(
            tzinfo=timezone.utc
        )


        current_utc = datetime.now(
            timezone.utc
        )


        candle_age_seconds = (
            current_utc - candle_datetime
        ).total_seconds()


        candle_age_minutes = round(
            candle_age_seconds / 60,
            2
        )


        # Allow a little time for a 1-minute
        # candle to finish and reach the API.
        #
        # More than 3 minutes old = stale.

        data_fresh = (
            0 <= candle_age_seconds <= 180
        )


        # ======================================
        # ANALYSIS
        # ======================================

        analysis = analyze_candles(
            candles
        )


        # ======================================
        # STALE DATA SAFETY
        # ======================================

        if not data_fresh:

            analysis["signal"] = "WAIT"

            analysis["stale_data"] = True

            analysis["reason"] = (
                "DATA STALE"
            )

        else:

            analysis["stale_data"] = False

            analysis["reason"] = (
                "DATA FRESH"
            )


        # ======================================
        # RESPONSE
        # ======================================

        return {

            "success": True,

            "source": "Twelve Data",

            "market": "Regular Forex",

            "symbol": "EUR/USD",

            "timeframe": "1 minute",

            "timezone": "UTC",

            "candles_received":
                len(candles),

            "latest_candle_time":
                latest_candle_time,

            "candle_age_seconds":
                round(
                    candle_age_seconds,
                    1
                ),

            "candle_age_minutes":
                candle_age_minutes,

            "data_fresh":
                data_fresh,

            "analysis":
                analysis,

            "candles":
                candles
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
            "error": str(error)
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
