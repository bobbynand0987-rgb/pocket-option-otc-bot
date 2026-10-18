import os
import json
import urllib.request
import urllib.error

from flask import Flask
from pocketoptionapi.stable_api import PocketOption


app = Flask(__name__)


@app.route("/")
def home():
    return "Pocket Option OTC Bot is online"


@app.route("/status")
def status():
    return {
        "status": "online",
        "market": "Pocket Option OTC",
        "mode": "data testing only"
    }


@app.route("/test-otc")
def test_otc():
    api_key = os.environ.get("OTCHARTS_API_KEY", "").strip()

    if not api_key:
        return {
            "success": False,
            "error": "OTCHARTS_API_KEY is missing"
        }, 500

    url = "https://otcharts.com/v1/symbols?venue=otc"

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + api_key,
            "User-Agent": "Mozilla/5.0"
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )

        symbols = data.get("symbols", [])

        eurusd = next(
            (
                item
                for item in symbols
                if item.get("symbol") == "EURUSD_otc"
            ),
            None
        )

        return {
            "success": True,
            "venue": "otc",
            "symbols_received": len(symbols),
            "EURUSD_otc": eurusd
        }

    except urllib.error.HTTPError as error:
        return {
            "success": False,
            "http_status": error.code,
            "error": error.read().decode("utf-8")
        }, 502

    except Exception as error:
        return {
            "success": False,
            "error": str(error)
        }, 500


@app.route("/test-usage")
def test_usage():
    api_key = os.environ.get("OTCHARTS_API_KEY", "").strip()

    if not api_key:
        return {
            "success": False,
            "error": "OTCHARTS_API_KEY is missing"
        }, 500

    url = "https://otcharts.com/v1/usage"

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + api_key,
            "User-Agent": "Mozilla/5.0"
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )

        return {
            "success": True,
            "usage": data
        }

    except urllib.error.HTTPError as error:
        return {
            "success": False,
            "http_status": error.code,
            "error": error.read().decode("utf-8")
        }, 502

    except Exception as error:
        return {
            "success": False,
            "error": str(error)
        }, 500


@app.route("/test-session")
def test_session():
    ssid = os.environ.get("POCKET_OPTION_SSID", "").strip()

    if not ssid:
        return {
            "success": False,
            "connected": False,
            "error": "POCKET_OPTION_SSID is missing"
        }, 500

    try:
        api = PocketOption(ssid)
        result = api.connect()

        connected = False
        error_message = None

        if isinstance(result, tuple):
            connected = bool(result[0])

            if len(result) > 1:
                error_message = str(result[1])

        else:
            connected = bool(result)

        if connected:
            return {
                "success": True,
                "connected": True,
                "message": "Pocket Option connection successful"
            }

        return {
            "success": False,
            "connected": False,
            "error": error_message or "Pocket Option connection failed"
        }, 502

    except Exception as error:
        return {
            "success": False,
            "connected": False,
            "error": str(error)
        }, 500
