from flask import Blueprint, send_from_directory
import os

pages = Blueprint("pages", __name__)

static_dir = os.path.join(os.path.dirname(__file__), "../../static")

@pages.route("/presentation")
def presentation():
    return send_from_directory(static_dir, "presentation.html")

@pages.route("/slides/<filename>")
def slide_image(filename):
    return send_from_directory(os.path.join(static_dir, "slides"), filename, mimetype="image/png")

@pages.route("/")
@pages.route("/<path:path>")
def index(path=""):
    return send_from_directory(static_dir, "index.html")
