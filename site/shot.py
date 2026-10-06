#!/usr/bin/env python3
"""Takes the picture of the admin tool that this page shows.

    python3 shot.py open [url]
    python3 shot.py size
    python3 shot.py shoot [out.png]
    python3 shot.py window name [out.png]
    python3 shot.py desk [out.png]

`open` starts a Chrome of its own, on its own profile, and pins the page at
1120 by 832 with two device pixels to the point. Arrange the windows in that
Chrome by hand, then `shoot`, which writes shots/workspace.png at 2240 by 1664.

`window` takes one window by its name in the admin, such as files or info,
with nothing of the desk around it and four device pixels to each of
NeXTSTEP's own. `desk` takes the desk with every window hidden. The film is
made of both.

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

#: Device pixels a side for each of NeXTSTEP's own pixels in a single window.
#: The film zooms into a window until its pixels show, and a whole number
#: keeps every one of them the same square.
DEVICE_PIXELS_PER_NEXT_PIXEL = 4


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


def pin(scale=SCALE):
    """The command that holds the page at the display's size.

    Sent before every other one, because a reload or a new tab drops it and a
    picture taken without it is whatever the window happened to be.

    Args:
        scale: Device pixels to the point. The page's own picture is taken at
            SCALE, a single window at whatever gives it whole NeXTSTEP pixels.
    """
    return ("Emulation.setDeviceMetricsOverride",
            {"width": WIDTH, "height": HEIGHT, "deviceScaleFactor": scale, "mobile": False})


def evaluate(expression, scale=SCALE):
    """Runs JavaScript in the page and returns what it comes to.

    Args:
        expression: An expression, or a promise, whose value is plain data.
        scale: Device pixels to the point while it runs, as for pin.
    """
    result = talk([pin(scale), ("Runtime.evaluate",
                                {"expression": expression, "returnByValue": True,
                                 "awaitPromise": True})])[1]
    if "exceptionDetails" in result:
        raise SystemExit(result["exceptionDetails"].get("text", "the page refused it"))
    return result["result"].get("value")


def picture(destination, scale=SCALE, clip=None):
    """Takes the page, or one rectangle of it, out of the page as a PNG.

    Args:
        destination: Where the PNG goes.
        scale: Device pixels to the point, as for pin.
        clip: A rectangle in the page's points, or None for all of it. It has
            to lie inside the display, since nothing outside it is drawn.
    """
    params = {"format": "png", "captureBeyondViewport": False}
    if clip:
        params["clip"] = {**clip, "scale": 1}
    result = talk([pin(scale), ("Page.captureScreenshot", params)])
    destination.write_bytes(base64.b64decode(result[1]["data"]))
    print(f"{destination} written. Run `oxipng -o 4 --strip safe` over it, "
          f"which takes about a fifth off and changes no pixel.")


#: Hides the desk around a window for as long as the window is being taken:
#: the menus, the dock, the floor, and a panel asking for the password.
HIDE_THE_DESK = "nx-menu, nx-dock, nx-floor, nx-ask { visibility: hidden !important; }"

#: Hides every window, which leaves the desk itself.
HIDE_THE_WINDOWS = "nx-window, nx-ask { visibility: hidden !important; }"


def hidden(rule):
    """JavaScript that adds a style rule to the page for one picture.

    Removed again by `SHOWN`. A rule rather than a style on each element,
    so taking it away leaves every element exactly as it was.
    """
    return (f"(() => {{ const style = document.createElement('style'); style.id = 'shot-hidden';"
            f" style.textContent = {json.dumps(rule)}; document.head.append(style); }})()")


SHOWN = "(() => { document.getElementById('shot-hidden')?.remove(); })()"


def shoot_window(name, destination):
    """Takes one of the admin's windows by itself, with nothing of the desk.

    The window is opened, raised and moved to the top left corner, with the
    desk around it hidden, and then put back where it was, and closed again
    if it was closed. The admin remembers where its windows are, and opening
    one writes that down before it moves, so the arrangement made by hand for
    `shoot` survives.

    The admin draws its desk larger with CSS zoom, and keeps its lines one
    CSS pixel wide so they stay sharp on a screen. At any zoom but 1 such a
    line is not a whole NeXTSTEP pixel, so the zoom is set to 1 while the
    window is taken, and every NeXTSTEP pixel comes out as exactly
    DEVICE_PIXELS_PER_NEXT_PIXEL device pixels a side.

    Args:
        name: The window's name in the admin, such as "files" or "info".
        destination: Where the PNG goes.
    """
    scale = DEVICE_PIXELS_PER_NEXT_PIXEL
    evaluate(hidden(HIDE_THE_DESK), scale)
    try:
        box = evaluate(f"""(() => {{
          const target = document.querySelector('nx-window[name="{name}"]');
          if (!target) return null;
          target.dataset.shotClosed = target.hidden;
          target.open();
          target.raise();
          document.body.dataset.shotZoom = document.body.style.zoom;
          document.body.style.zoom = "1";
          target.dataset.shotPlace = JSON.stringify([target.style.left, target.style.top]);
          target.style.left = "0px";
          target.style.top = "0px";
          const {{ x, y, width, height }} = target.getBoundingClientRect();
          return {{ x, y, width, height }};
        }})()""", scale)
        if box is None:
            raise SystemExit(f"the admin has no window named {name}")
        if box["x"] + box["width"] > WIDTH or box["y"] + box["height"] > HEIGHT:
            raise SystemExit(f"{name} is larger than the display, at {box['width']} by {box['height']}")
        picture(destination, scale, box)
    finally:
        evaluate(f"""(() => {{
          const target = document.querySelector('nx-window[name="{name}"]');
          if (target?.dataset.shotPlace) {{
            [target.style.left, target.style.top] = JSON.parse(target.dataset.shotPlace);
            delete target.dataset.shotPlace;
          }}
          if (target?.dataset.shotClosed === "true") target.close();
          delete target?.dataset.shotClosed;
          if (document.body.dataset.shotZoom !== undefined) {{
            document.body.style.zoom = document.body.dataset.shotZoom;
            delete document.body.dataset.shotZoom;
          }}
        }})()""")
        evaluate(SHOWN)


def shoot_desk(destination):
    """Takes the desk with every window hidden: the workspace, the menu, the
    dock and the floor, at the size of the page's own picture."""
    evaluate(hidden(HIDE_THE_WINDOWS))
    try:
        picture(destination)
    finally:
        evaluate(SHOWN)


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
        print(evaluate("[innerWidth, innerHeight, devicePixelRatio]"))

    elif what == "shoot":
        picture(pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else DESTINATION)

    elif what == "window" and len(sys.argv) > 2:
        name = sys.argv[2]
        shoot_window(name, pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else pathlib.Path(f"{name}.png"))

    elif what == "desk":
        shoot_desk(pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path("desk.png"))

    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
