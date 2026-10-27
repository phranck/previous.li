#!/usr/bin/env python3
"""Takes the pictures of the admin tool that this page and its film show.

    python3 shot.py shoot [url] [out.png]
    python3 shot.py open [url]
    python3 shot.py size
    python3 shot.py window name [out.png]
    python3 shot.py desk [out.png]

`shoot` takes the page's own picture in Safari Technology Preview. It starts
the Technology Preview's own safaridriver, lays the desk out the way
ARRANGEMENT says and writes shots/workspace.png at 2240 by 1664.

`open` starts a Chrome of its own for the film, on its own profile and
without a window, and pins the page at 1120 by 832. `window` then takes one
window by its name in the admin, such as files or info, with nothing of the
desk around it and four device pixels to each of NeXTSTEP's own. `desk` takes
the desk with every window hidden. The film is made of both. They run in
Chrome because its DevTools protocol sets the device pixels to the point,
and WebDriver has no command for that.

Three things make the page's picture more than a screen grab:

  The size    1120 by 832 is what a NeXT MegaPixel Display held, and the page
              shows the picture at 1120, so a display with two device pixels to
              the point draws it one for one.
  The fit     WebDriver sizes the window rather than the page in it, so the
              window is resized until the page is 1120 wide and CORNER_ROOM
              taller than 832. A display that does not draw two device pixels
              to the point stops the run.
  The source  The page is held at 1120 by 832 at the top of that window from
              the moment it has loaded, with black below it, so the window
              shows the picture while it runs. What Safari shows is taken and
              cut to those 832, so the picture carries no window frame and
              none of the rounded corners macOS gives a window's lower edge.
              A screen grab carries both.

`shoot` needs nothing beyond the standard library. The Chrome commands need
websocket-client:

    python3 -m venv .venv && .venv/bin/pip install websocket-client
    .venv/bin/python site/shot.py open
"""

import base64
import contextlib
import json
import pathlib
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib

HERE = pathlib.Path(__file__).parent

#: A Chrome of its own, so nothing here reaches the one somebody is using.
PORT = 9333
PROFILE = "/tmp/chrome-shot-profile"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

#: Safari Technology Preview's own driver. Its session runs in a window of its
#: own, so nothing here reaches the Safari somebody is using.
SAFARIDRIVER = "/Applications/Safari Technology Preview.app/Contents/MacOS/safaridriver"
SAFARI_PORT = 9334

#: The browser name that makes safaridriver start the Technology Preview.
SAFARI_BROWSER = "Safari Technology Preview"

#: How often the window is resized before a page that will not measure the
#: display's size stops the run.
FIT_TRIES = 3

#: Points the Safari window is taller than the display. macOS rounds a
#: window's lower corners and Safari's picture of the page carries that
#: rounding, so the page is held at the display's size above this margin and
#: only the page is taken.
CORNER_ROOM = 64

#: How long the panes the arrangement has just shown take to load their
#: pictures, such as the mark beside a system that is here, in seconds.
PICTURES_SECONDS = 1

#: The NeXT MegaPixel Display, and two device pixels to the point.
WIDTH, HEIGHT, SCALE = 1120, 832, 2

#: Where the admin answers, which is what the page's own address bar shows.
ADMIN = "http://next.local:8810/"

DESTINATION = HERE / "shots" / "workspace.png"

#: Where each window of the page's picture stands, in the desk's own points,
#: from the back to the front, so the last one is the key window. The names
#: are the admin's own: `info` is About for the emulated machine, and `pi` is
#: the window titled Info, which is about the Raspberry Pi. phranck's own desk
#: of 27 October 2026 is the model, pushed together to fit the MegaPixel
#: Display: the Config Editor and Activity Monitor down the right under the
#: dock, Activity Monitor over the Config Editor, About and Info along the
#: top, Preferences on the left, and the File Viewer in front of them as the
#: key window.
ARRANGEMENT = {
    "pi": {"x": 569, "y": 5},
    "info": {"x": 162, "y": 5},
    "preferences": {"x": 5, "y": 235},
    "editor": {"x": 643, "y": 141},
    # On the floor of the display, 359 points tall.
    "activity": {"x": 643, "y": 473},
    # 442 points is the narrowest that holds the machines three to a row, as
    # phranck's desk shows them, and four more keep the third row in.
    "files": {"x": 187, "y": 268, "w": 446, "h": 557},
}

#: JavaScript that raises the windows in the order ARRANGEMENT gives them, so
#: the last is in front and is the key window.
RAISED_IN_ORDER = (f"for (const name of {json.dumps(list(ARRANGEMENT))}) "
                   "document.querySelector(`nx-window[name=\"${name}\"]`)?.raise();")

#: The Preferences module the picture shows, by its `value` in the admin.
MODULE = "notifications"

#: The folder the File Viewer shows, by its path in the admin's tree, and the
#: machine the Config Editor is opened on, by its name in that folder.
PLACE = "/Machines/System"
EDITED = "NeXTcube"

#: Where the admin keeps the desk, how large it draws it, and which folder the
#: File Viewer stands in, in the browser's localStorage. All three are the
#: admin's own keys, in design/kit/desk.js, admin/interface/app/size.js and
#: admin/interface/app/viewer.js of phranck/previously. The folder is written
#: there rather than reached by double clicks, because opening one waits on an
#: animation that a browser window behind others never finishes. `shoot_page`
#: checks that the windows stand where it put them, so a key the admin has
#: renamed stops it with a message rather than taking a picture of some other
#: desk.
DESK_KEY = "nextstep-workspace:v4"
SIZE_KEY = "previously:size"
PLACE_KEY = "previously:place"

#: How long the admin takes after loading to fill its windows with what the
#: Pi answers, in seconds.
READINGS_SECONDS = 3

#: How long Activity Monitor runs before the picture is taken, in seconds: as
#: long as its load chart takes to fill, a column every five seconds for its
#: 36 columns, so neither chart stands half empty.
ACTIVITY_SECONDS = 180

#: Device pixels a side for each of NeXTSTEP's own pixels in a single window.
#: The film zooms into a window until its pixels show, and a whole number
#: keeps every one of them the same square.
DEVICE_PIXELS_PER_NEXT_PIXEL = 4


#: How long to wait for Chrome to answer with a tab, as tries half a second
#: apart.
WAIT_TRIES = 60


def chrome_page():
    """The tab this drives, which is the only one in that Chrome.

    Returns:
        The tab, or None while the Chrome on the port answers without one,
        which it does for a moment after it starts.

    Raises:
        OSError: while nothing answers on the port.
    """
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json") as answer:
        for target in json.load(answer):
            if target["type"] == "page":
                return target
    return None


def page_target():
    """The tab this drives, for a command that cannot go on without it."""
    target = chrome_page()
    if target is None:
        raise SystemExit("no page in the Chrome on that port")
    return target


def answering():
    """Whether a Chrome answers on the port at all, with a tab or without."""
    try:
        chrome_page()
    except OSError:
        return False
    return True


def waited_for_page():
    """Waits until the Chrome on the port answers with a tab.

    Returns:
        Whether it did within WAIT_TRIES tries. A Chrome that is not listening
        yet and one that listens before its first tab exists are both waited
        for, because both are a Chrome still starting.
    """
    for _ in range(WAIT_TRIES):
        with contextlib.suppress(OSError):
            if chrome_page() is not None:
                return True
        time.sleep(0.5)
    return False


def talk(commands):
    """Sends commands to the page and returns each result, in order."""
    # Imported here, because only the Chrome commands need it and `shoot`
    # runs without it.
    import websocket

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
    written(destination, base64.b64decode(result[1]["data"]))


def written(destination, png):
    """Writes a picture and says what to run over it before it is committed."""
    destination.write_bytes(png)
    print(f"{destination} written. Run `oxipng -o 4 --strip safe` over it, "
          f"which takes about a fifth off and changes no pixel.")


#: Hides the desk around a window for as long as the window is being taken:
#: the menus, the dock, the floor, and a panel asking for the password.
HIDE_THE_DESK = "nx-menu, nx-dock, nx-floor, nx-ask { visibility: hidden !important; }"

#: Hides every window, which leaves the desk itself.
HIDE_THE_WINDOWS = "nx-window, nx-ask { visibility: hidden !important; }"


#: Holds the page at the display's size inside a window taller than the
#: display, which is what keeps the window's rounded corners out of the
#: picture. The admin's body is 100vh tall and its dock and floor are fixed to
#: the window, so the body is given the display's height and made the box the
#: fixed ones stand in. What is left of the window below it is black, so the
#: window shows the picture and nothing that looks like room in it.
HOLD_THE_DISPLAY = (f"html, body {{ height: {HEIGHT}px !important; }}"
                    " html { background: #000 !important; }"
                    " body { contain: layout paint; }")


def styled(rule):
    """JavaScript that adds a style rule to the page for one picture.

    Removed again by `UNSTYLED`. A rule rather than a style on each element,
    so taking it away leaves every element exactly as it was.
    """
    return (f"(() => {{ const style = document.createElement('style'); style.id = 'shot-style';"
            f" style.textContent = {json.dumps(rule)}; document.head.append(style); }})()")


UNSTYLED = "(() => { document.getElementById('shot-style')?.remove(); })()"


def shoot_window(name, destination):
    """Takes one of the admin's windows by itself, with nothing of the desk.

    The window is opened, raised and moved to the top left corner, with the
    desk around it hidden, and then put back where it was, and closed again
    if it was closed. The admin remembers where its windows are, and opening
    one writes that down before it moves, so the arrangement `arrange` made
    survives.

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
    evaluate(styled(HIDE_THE_DESK), scale)
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
        evaluate(UNSTYLED)


def shoot_desk(destination):
    """Takes the desk with every window hidden: the workspace, the menu, the
    dock and the floor, at the size of the page's own picture."""
    evaluate(styled(HIDE_THE_WINDOWS))
    try:
        picture(destination)
    finally:
        evaluate(UNSTYLED)


class Safari:
    """A WebDriver session in Safari Technology Preview, for one picture.

    WebDriver is HTTP and JSON, so urllib speaks it and nothing needs
    installing. The driver and its session last as long as the `with` block
    that opens them.
    """

    def __enter__(self):
        self.driver = subprocess.Popen([SAFARIDRIVER, "--port", str(SAFARI_PORT)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.waited_for_driver()
            capabilities = {"capabilities": {"alwaysMatch": {"browserName": SAFARI_BROWSER}}}
            self.session = self.ask("POST", "/session", capabilities)["sessionId"]
            self.own = self.command("GET", "window")
        except BaseException:
            self.stop_driver()
            raise
        return self

    def __exit__(self, *exception):
        with contextlib.suppress(OSError, SystemExit):
            self.ask("DELETE", f"/session/{self.session}")
        self.stop_driver()

    def stop_driver(self):
        """Ends the safaridriver this session started."""
        self.driver.terminate()
        self.driver.wait()

    def waited_for_driver(self):
        """Waits until safaridriver says it can start a session."""
        for _ in range(WAIT_TRIES):
            with contextlib.suppress(OSError):
                if self.ask("GET", "/status").get("ready"):
                    return
            time.sleep(0.5)
        raise SystemExit("safaridriver did not answer on its port")

    def ask(self, method, path, body=None):
        """Sends one WebDriver request and returns its value.

        Raises:
            OSError: while nothing answers on the port.
            SystemExit: where Safari answers with an error, which it names.
        """
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{SAFARI_PORT}{path}", data=data,
                                         method=method,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as answer:
                return json.load(answer)["value"]
        except urllib.error.HTTPError as refusal:
            reason = json.load(refusal).get("value", {}).get("message", refusal.reason)
            raise SystemExit(f"Safari refused {method} {path}: {reason}") from None

    def command(self, method, path, body=None):
        """Sends one request to this session."""
        return self.ask(method, f"/session/{self.session}/{path}", body)

    def evaluate(self, expression):
        """Runs JavaScript in the page and returns what it comes to, awaiting a promise."""
        return self.command("POST", "execute/sync",
                            {"script": f"return ({expression});", "args": []})

    def waited_for(self, expression, failure):
        """Waits until an expression in the page comes to true.

        Args:
            expression: JavaScript whose value is true once the page is ready.
            failure: What to stop with where it never is, within WAIT_TRIES tries.
        """
        for _ in range(WAIT_TRIES):
            if self.evaluate(expression) is True:
                return
            time.sleep(0.5)
        raise SystemExit(failure)

    def alone(self):
        """Closes every tab but the session's own and goes back to it.

        An extension can open a tab of its own in the session, and WebDriver
        then talks to whichever tab is in front, and a tab bar takes height
        from the page.
        """
        for handle in self.command("GET", "window/handles"):
            if handle != self.own:
                self.command("POST", "window", {"handle": handle})
                self.command("DELETE", "window")
        self.command("POST", "window", {"handle": self.own})

    def fit(self):
        """Sizes the window until the page in it is the display's width and
        CORNER_ROOM taller than the display.

        WebDriver sets the window, and the toolbar takes part of it, so the
        window grows by whatever the page still lacks.
        """
        wanted = (WIDTH, HEIGHT + CORNER_ROOM)
        self.command("POST", "window/rect", {"x": 40, "y": 40, "width": wanted[0], "height": wanted[1]})
        for _ in range(FIT_TRIES):
            width, height = self.evaluate("[innerWidth, innerHeight]")
            if (width, height) == wanted:
                return
            frame = self.command("GET", "window/rect")
            self.command("POST", "window/rect", {"width": frame["width"] + wanted[0] - width,
                                                 "height": frame["height"] + wanted[1] - height})
        raise SystemExit(f"the page in Safari measures {width} by {height}, not {wanted[0]} by {wanted[1]}")

    def picture(self, destination):
        """Takes the page as a PNG of the display's device pixels.

        The whole of what the window shows, cut to the display's height at the
        top, because HOLD_THE_DISPLAY holds the page there above the window's
        rounded corners. Safari's picture of the body alone came back as tall
        as the window after a full run on 27 October 2026, though the body
        measured the display's height, so nothing here depends on it.
        """
        scale = self.evaluate("devicePixelRatio")
        if scale != SCALE:
            raise SystemExit(f"this display draws {scale} device pixels to the point, "
                             f"and the picture needs {SCALE}")
        box = self.evaluate("(({ x, y, width, height }) => [x, y, width, height])"
                            "(document.body.getBoundingClientRect())")
        if box != [0, 0, WIDTH, HEIGHT]:
            raise SystemExit(f"the page's body stands at {box}, not at 0, 0, {WIDTH} by {HEIGHT}")
        png = base64.b64decode(self.command("GET", "screenshot"))
        size = struct.unpack(">II", png[16:24])
        if size != (WIDTH * SCALE, (HEIGHT + CORNER_ROOM) * SCALE):
            raise SystemExit(f"Safari took {size[0]} by {size[1]} pixels, "
                             f"not {WIDTH * SCALE} by {(HEIGHT + CORNER_ROOM) * SCALE}")
        written(destination, top_rows(png, HEIGHT * SCALE))


#: How many bytes a pixel takes in each PNG color type at eight bits a sample.
PNG_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}


def top_rows(png, rows):
    """A PNG cut to its top rows.

    Each row of a PNG is filtered against the rows above it and never against
    the rows below, so the top rows are kept as they are, with their filters,
    and nothing is decoded or changes a pixel.

    Args:
        png: The PNG, eight bits a sample and not interlaced, as Safari writes.
        rows: How many rows to keep from the top.

    Returns:
        The PNG with those rows, its other chunks before the pixels kept.
    """
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    position, before, pixels, header = 8, [], b"", None
    while position < len(png):
        length, kind = struct.unpack(">I4s", png[position:position + 8])
        data = png[position + 8:position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            header = data
        elif kind == b"IDAT":
            pixels += data
        elif kind != b"IEND" and not pixels:
            before.append(chunk(kind, data))
    width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", header)
    if depth != 8 or interlace or color not in PNG_CHANNELS or rows > height:
        raise SystemExit("Safari's picture is not a PNG this can cut")
    kept = zlib.decompress(pixels)[:rows * (1 + width * PNG_CHANNELS[color])]
    return (png[:8] + chunk(b"IHDR", struct.pack(">II", width, rows) + header[8:])
            + b"".join(before) + chunk(b"IDAT", zlib.compress(kept, 9)) + chunk(b"IEND", b""))


def thing_named(name):
    """JavaScript for the File Viewer's icon of that name, or null.

    The last one of the name, because the shelf and the path at the top of
    the viewer show things as well, and the machine to edit is the one in the
    browser under them.
    """
    return (f"[...document.querySelectorAll('#file-viewer nx-thing')]"
            f".filter((thing) => thing.textContent.trim() === {json.dumps(name)}).at(-1) ?? null")


def shoot_page(url, destination):
    """Lays the desk out the way the page's picture has it, and takes it.

    The admin draws its desk from what the browser remembers, so the
    arrangement is written there and the page loaded again: every window in
    ARRANGEMENT open where it says, the desk at 100%, which is NeXTSTEP's own
    size, the File Viewer in PLACE, and the last window in front. Preferences
    shows MODULE, and the Config Editor is opened on EDITED, which is what the
    admin does with a machine carried into it. Activity Monitor then runs for
    ACTIVITY_SECONDS, and its rows of lamps are shown at their reading before
    the picture, because a browser window behind others stops animating.

    Args:
        url: Where the admin answers.
        destination: Where the PNG goes.
    """
    desk = {name: {"open": True, **place} for name, place in ARRANGEMENT.items()}
    desk["desk"] = {"front": list(ARRANGEMENT)[-1]}
    with Safari() as safari:
        safari.command("POST", "url", {"url": url})
        safari.alone()
        safari.fit()
        safari.evaluate(f"""(() => {{
          localStorage.setItem({json.dumps(SIZE_KEY)}, "1");
          localStorage.setItem({json.dumps(DESK_KEY)}, {json.dumps(json.dumps(desk))});
          localStorage.setItem({json.dumps(PLACE_KEY)}, {json.dumps(json.dumps(PLACE))});
        }})()""")
        safari.command("POST", "refresh")
        safari.waited_for(f"Boolean({thing_named(EDITED)})",
                          f"the File Viewer shows no machine named {EDITED} in {PLACE}")
        # Held from here on rather than just before the picture, so whoever
        # watches the window sees what the picture will be.
        safari.evaluate(styled(HOLD_THE_DISPLAY))
        time.sleep(READINGS_SECONDS)

        safari.evaluate(f"""document.querySelector(
          'nx-window[name="preferences"] .module[value={json.dumps(MODULE)}]')?.click()""")
        safari.evaluate(f"""document.querySelector('nx-window[name="editor"]').dispatchEvent(
          new CustomEvent("nx-choose", {{
            bubbles: true, detail: {{ value: {thing_named(EDITED)}.getAttribute("value") }} }}))""")
        safari.waited_for("!document.querySelector('nx-window[name=\"editor\"]').hidden",
                          f"the Config Editor did not open on {EDITED}")
        # The editor comes to the front as it opens, over Activity Monitor and
        # the File Viewer, so the order is set again at once rather than only
        # before the picture.
        time.sleep(PICTURES_SECONDS)
        safari.evaluate(f"(() => {{ {RAISED_IN_ORDER} }})()")
        time.sleep(ACTIVITY_SECONDS)

        astray = safari.evaluate(f"""(() => {{
          for (const row of document.querySelectorAll('nx-window[name="activity"] nx-leds')) {{
            row.shown = row.held() ?? 0;
            row.draw();
          }}
          const places = {json.dumps(ARRANGEMENT)};
          {RAISED_IN_ORDER}
          return Object.entries(places).filter(([name, place]) => {{
            const target = document.querySelector(`nx-window[name="${{name}}"]`);
            return !target || target.hidden
              || target.offsetLeft !== place.x || target.offsetTop !== place.y
              || (place.w && target.offsetWidth !== place.w)
              || (place.h && target.offsetHeight !== place.h);
          }}).map(([name]) => name);
        }})()""")
        if astray:
            raise SystemExit(f"not where ARRANGEMENT puts them: {', '.join(astray)}")
        time.sleep(PICTURES_SECONDS)
        safari.alone()
        safari.picture(destination)


def open_browser(url):
    # A second Chrome on a port one is already listening on starts without a
    # window and exits, which looks from here like the first one having died.
    # Headless, because everything it is asked for comes through the port and
    # a window would only take the screen of whoever runs it.
    already = answering()
    if not already:
        subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
                          f"--user-data-dir={PROFILE}", "--no-first-run",
                          "--no-default-browser-check", "--window-size=1400,1100",
                          "--window-position=40,40", url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not waited_for_page():
        raise SystemExit("Chrome did not answer on its debugging port with a page")
    if already:
        talk([pin()])
        print(f"already open at {WIDTH}x{HEIGHT}, {SCALE} device pixels to the point")
        return
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
        shoot_page(sys.argv[2] if len(sys.argv) > 2 else ADMIN,
                   pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else DESTINATION)

    elif what == "window" and len(sys.argv) > 2:
        name = sys.argv[2]
        shoot_window(name, pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else pathlib.Path(f"{name}.png"))

    elif what == "desk":
        shoot_desk(pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path("desk.png"))

    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
