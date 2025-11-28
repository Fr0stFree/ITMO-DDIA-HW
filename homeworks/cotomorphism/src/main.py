"""
Small Flask app that serves a single image and supports toggling a degraded state.

Usage:
  python main.py --image /path/to/image.png --host 0.0.0.0 --port 8080

The script exposes:
  GET /        - basic status
  GET /get     - returns the configured image (or 503 when degraded)
  GET/POST /degrade/on  - enable degraded mode (subsequent /get returns 503)
  GET/POST /degrade/off - disable degraded mode
"""

from flask import Flask, Response, request
import threading
import os
import mimetypes

app = Flask(__name__)

degraded = False
lock = threading.Lock()

IMAGE_BYTES = None
IMAGE_MIMETYPE = "application/octet-stream"


@app.route("/get")
def cat():
    """Return the configured image or an Internal Server Error when degraded is on."""
    with lock:
        if degraded:
            return Response("Internal error in backend", status=503)

    print("Returning image from /get")
    return Response(IMAGE_BYTES, mimetype=IMAGE_MIMETYPE, status=200)


@app.route("/degrade/on", methods=["GET", "POST"])
def degrade_on():
    """Turn degradation ON."""
    global degraded
    with lock:
        degraded = True
    return f"Degraded mode set to: {degraded}\n", 200


@app.route("/degrade/off", methods=["GET", "POST"])
def degrade_off():
    """Turn degradation OFF."""
    global degraded
    with lock:
        degraded = False
    print("Degraded mode OFF")
    return f"Degraded mode set to: {degraded}\n", 200


@app.route("/")
def index():
    return "Cotomorphism backend is running. Use /get to fetch image and /degrade/on or /degrade/off to toggle degradation.\n"


def load_image(path: str):
    """Load image bytes and set mimetype based on file extension."""
    global IMAGE_BYTES, IMAGE_MIMETYPE
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, "rb") as f:
        IMAGE_BYTES = f.read()
    mtype, _ = mimetypes.guess_type(path)
    if mtype:
        IMAGE_MIMETYPE = mtype


if __name__ == "__main__":
    image = os.environ.get("IMAGE_PATH")
    try:
        load_image(image)
        print(f"Loaded image: {image } (mimetype={IMAGE_MIMETYPE})")
    except Exception as e:
        print(f"Failed to load image '{image }': {e}")
        raise

    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 80)))