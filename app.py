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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
