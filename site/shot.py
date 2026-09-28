#!/usr/bin/env python3
"""Takes the picture of the admin tool that this page shows.

    python3 shot.py open [url]
    python3 shot.py size
    python3 shot.py shoot [out.png]

`open` starts a Chrome of its own, on its own profile, and pins the page at
1120 by 832 with two device pixels to the point. Arrange the windows in that
Chrome by hand, then `shoot`, which writes shots/workspace.png at 2240 by 1664.

Three things about it are the whole reason it exists rather than a screen grab:

  The size    1120 by 832 is what a NeXT MegaPixel Display held, and the page
              shows the picture at 1120, so a display with two device pixels to
              the point draws it one for one.
  The pin     Emulation.setDeviceMetricsOverride holds the page at that size
              whatever the window is dragged to, so the frame is the same every
              time and the window can be as large as somebody needs to work in.
  The source  Page.captureScreenshot takes the picture out of the page, so it
              carries no window frame and none of the rounded corners macOS
              gives one. A screen grab of the window carries both.

It needs websocket-client, which is not in the standard library:

    python3 -m venv .venv && .venv/bin/pip install websocket-client
    .venv/bin/python site/shot.py open
"""

import base64
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

import websocket

HERE = pathlib.Path(__file__).parent

#: A Chrome of its own, so nothing here reaches the one somebody is using.
PORT = 9333
PROFILE = "/tmp/chrome-shot-profile"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

#: The NeXT MegaPixel Display, and two device pixels to the point.
WIDTH, HEIGHT, SCALE = 1120, 832, 2

#: Where the admin answers, which is what the page's own address bar shows.
ADMIN = "http://cube.local:8810/"

DESTINATION = HERE / "shots" / "workspace.png"


def page_target():
    """The tab this drives, which is the only one in that Chrome."""
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json") as answer:
        for target in json.load(answer):
            if target["type"] == "page":
                return target
    raise SystemExit("no page in the Chrome on that port")


def talk(commands):
    """Sends commands to the page and returns each result, in order."""
    socket = websocket.create_connection(page_target()["webSocketDebuggerUrl"],
                                         suppress_origin=True, timeout=30)
    results = []
    try:
        for number, (method, params) in enumerate(commands, start=1):
            socket.send(json.dumps({"id": number, "method": method, "params": params}))
            while True:
                answer = json.loads(socket.recv())
                if answer.get("id") == number:
                    results.append(answer.get("result", answer.get("error")))
                    break
    finally:
        socket.close()
    return results


def pin():
    """The command that holds the page at the display's size.

    Sent before every other one, because a reload or a new tab drops it and a
    picture taken without it is whatever the window happened to be.
    """
    return ("Emulation.setDeviceMetricsOverride",
            {"width": WIDTH, "height": HEIGHT, "deviceScaleFactor": SCALE, "mobile": False})


def open_browser(url):
    # A second Chrome on a port one is already listening on starts without a
    # window and exits, which looks from here like the first one having died.
    try:
        page_target()
    except Exception:
        pass
    else:
        talk([pin()])
        print(f"already open at {WIDTH}x{HEIGHT}, {SCALE} device pixels to the point")
        return

    subprocess.Popen([CHROME, f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={PROFILE}", "--no-first-run",
                      "--no-default-browser-check", "--window-size=1400,1100",
                      "--window-position=40,40", url],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            page_target()
            break
        except Exception:
            time.sleep(0.5)
    else:
        raise SystemExit("Chrome did not answer on its debugging port")
    time.sleep(2)
    talk([pin()])
    print(f"{url} at {WIDTH}x{HEIGHT}, {SCALE} device pixels to the point")


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "shoot"

    if what == "open":
        open_browser(sys.argv[2] if len(sys.argv) > 2 else ADMIN)

    elif what == "size":
        result = talk([pin(), ("Runtime.evaluate",
                               {"expression": "[innerWidth, innerHeight, devicePixelRatio]",
                                "returnByValue": True})])
        print(result[1]["result"]["value"])

    elif what == "shoot":
        destination = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else DESTINATION
        result = talk([pin(), ("Page.captureScreenshot",
                               {"format": "png", "captureBeyondViewport": False})])
        destination.write_bytes(base64.b64decode(result[1]["data"]))
        print(f"{destination} written. Run `oxipng -o 4 --strip safe` over it, "
              f"which takes about a fifth off and changes no pixel.")

    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
