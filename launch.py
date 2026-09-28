"""Windows runtime launcher for the packaged Kitchen Factory application."""

import os
import threading
import time
import webbrowser

from waitress import serve


HOST = "127.0.0.1"
PORT = 5000
URL = f"http://{HOST}:{PORT}/login"


def open_browser():
    time.sleep(1.5)
    webbrowser.open(URL)


def main():
    data_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Kitchen Factory")
    os.makedirs(data_dir, exist_ok=True)
    os.environ.setdefault("KITCHEN_FACTORY_DATA_DIR", data_dir)

    from app import app

    threading.Thread(target=open_browser, daemon=True).start()
    serve(app, host=HOST, port=PORT, threads=4)


if __name__ == "__main__":
    main()
