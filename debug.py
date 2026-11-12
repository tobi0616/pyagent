import os

DEBUG = os.environ.get("DEBUG", "").lower() == "1"

def debug(*msg):
    if DEBUG:
        print("[debug]", msg)