import os
import json
import urllib.request
import urllib.error

from flask import Flask

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
    api_key = os.environ.get("OTCHARTS_API_KEY")

    if not api_key:
        return {
            "success": False,
            "error": "OTCHARTS_API_KEY is missing"
        }, 500

    url = "https://otcharts.com/v1/symbols?venue=otc"

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + api_key
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))

        symbols = data.get("symbols", [])

        eurusd = next(
            (
                item for item in symbols
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
