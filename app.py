import os
import json
import urllib.request
import urllib.parse
import urllib.error

from flask import Flask
from Analysis import analyze_candles


app = Flask(__name__)


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():
    return {
        "status": "online",
        "bot": "Forex Signal Assistant",
        "market": "Regular Forex",
        "source": "Twelve Data"
    }


# =========================================================
# STATUS
# =========================================================

@app.route("/status")
def status():
    return {
        "status": "online",
        "market": "Regular Forex",
        "pair": "EUR/USD",
        "timeframe": "1 minute",
        "source": "Twelve Data"
    }


# =========================================================
# EUR/USD FOREX DATA + ANALYSIS
# =========================================================

@app.route("/test-forex")
def test_forex():

    api_key = os.environ.get(
        "TWELVE_DATA_API_KEY",
        ""
    ).strip()

    if not api_key:
        return {
            "success": False,
            "error": "TWELVE_DATA_API_KEY is missing"
        }, 500


    # -----------------------------------------------------
    # Twelve Data request
    # -----------------------------------------------------

    params = urllib.parse.urlencode({
        "symbol": "EUR/USD",
        "interval": "1min",
        "outputsize": 50,
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


        # -------------------------------------------------
        # Twelve Data API error
        # -------------------------------------------------

        if data.get("status") == "error":

            return {
                "success": False,
                "error": data.get(
                    "message",
                    "Twelve Data error"
                )
            }, 502


        # -------------------------------------------------
        # Get candles
        # -------------------------------------------------

        candles = data.get("values", [])


        if not candles:

            return {
                "success": False,
                "error": "No candle data returned"
            }, 502


        # Twelve Data normally returns newest -> oldest.
        # Our analysis requires oldest -> newest.

        candles.reverse()


        # -------------------------------------------------
        # Make sure enough candles exist
        # -------------------------------------------------

        if len(candles) < 35:

            return {
                "success": False,
                "error":
                    "Not enough candles for analysis",
                "candles_received":
                    len(candles)
            }, 502


        # -------------------------------------------------
        # Latest candle information
        # -------------------------------------------------

        latest_candle = candles[-1]

        latest_candle_time = (
            latest_candle.get("datetime")
        )


        # -------------------------------------------------
        # Run technical analysis
        # -------------------------------------------------

        analysis = analyze_candles(
            candles
        )


        # -------------------------------------------------
        # Successful response
        # -------------------------------------------------

        return {

            "success": True,

            "source": "Twelve Data",

            "market": "Regular Forex",

            "symbol": "EUR/USD",

            "timeframe": "1 minute",

            "candles_received":
                len(candles),

            "latest_candle_time":
                latest_candle_time,

            "analysis":
                analysis,

            "candles":
                candles
        }


    # -----------------------------------------------------
    # HTTP error
    # -----------------------------------------------------

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


    # -----------------------------------------------------
    # Other errors
    # -----------------------------------------------------

    except Exception as error:

        return {
            "success": False,
            "error": str(error)
        }, 500


# =========================================================
# START SERVER
# =========================================================

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
