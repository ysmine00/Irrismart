from flask import Blueprint, send_from_directory
import os

pages = Blueprint("pages", __name__)

@pages.route("/")
@pages.route("/<path:path>")
def index(path=""):
    static_dir = os.path.join(os.path.dirname(__file__), "../../static")
    return send_from_directory(static_dir, "index.html")
