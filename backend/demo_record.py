"""Drive ProofBridge demo scenes in headed Edge via CDP and record with ffmpeg.

Usage (cwd = backend/):
  ./.venv/Scripts/python demo_record.py <scene>
  scenes: test | a | b | c | d | e
"""

import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import ctypes
import httpx
from websockets.asyncio.client import connect

BASE_URL = "http://localhost:5174"
API_URL = "http://127.0.0.1:8001"

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9222
PROFILE = r"C:\Users\Lenovo\Downloads\demo-edge-profile"
FFMPEG = r"C:\Users\Lenovo\Downloads\ffmpeg-tmp\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe"

ROOT = Path(__file__).parent
ASSETS = ROOT / "demo_assets"
CLIPS = ROOT / "demo_clips"

BUYER = "buyer@demo.com"
SELLER = "seller@demo.com"
AGENT = "agent@demo.com"
PASSWORD = "demo12345"

CLIP_W, CLIP_H = 1280, 800

CASE_TITLE = "Smartphone Charger Order #PB-1042"
CASE_DESCRIPTION = (
    "Customer reports that order #PB-1042 never arrived and that "
    "their credit card was charged twice for the purchase."
)
REVIEW_NOTES = (
    "Order #PB-1042 is confirmed by the documents on file, so the delivery "
    "promise is supported. The double-charge claim references order #PB-9999, "
    "which does not appear in any submitted document. A partial refund for "
    "the missing delivery is recommended."
)

CREATE_NO_WINDOW = 0x08000000
DEVNULL = subprocess.DEVNULL


# ---------------------------------------------------------------- windows


def _browser_pids():
    """PIDs of msedge processes running with our dedicated demo profile."""
    pids = []
    try:
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\""
                f" | Where-Object {{ $_.CommandLine -like '*{PROFILE}*' }}"
                " | Select-Object -ExpandProperty ProcessId",
            ],
            capture_output=True, text=True, timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
        pids = [int(line) for line in out.stdout.splitlines() if line.strip().isdigit()]
    except Exception:
        pass
    if _EDGE_PID and _EDGE_PID not in pids:
        pids.append(_EDGE_PID)
    return pids


def _find_edge_hwnd(debug=False):
    user32 = ctypes.windll.user32
    pids = set(_browser_pids())
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _enum(hwnd, _lparam):
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value != "Chrome_WidgetWin_1":
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        visible = user32.IsWindowVisible(hwnd)
        if pid.value in pids or buf.value.strip() == "ProofBridge AI":
            found.append({
                "hwnd": hwnd,
                "title": buf.value.strip(),
                "pid": pid.value,
                "visible": bool(visible),
                "rect": (rect.left, rect.top, rect.right, rect.bottom),
            })
        return True

    user32.EnumWindows(_enum, 0)
    if debug:
        for w in found:
            print("  [win] hwnd=%d pid=%d vis=%s rect=%s title=%r" % (
                w["hwnd"], w["pid"], w["visible"], w["rect"], w["title"],
            ))
    if not found:
        return None
    area = lambda w: (w["rect"][2] - w["rect"][0]) * (w["rect"][3] - w["rect"][1])
    visible = [w for w in found if w["visible"]]
    pool = visible or found
    exact = [w for w in pool if w["title"] == "ProofBridge AI"]
    return max(exact or pool, key=area)["hwnd"]


def force_foreground():
    hwnd = _find_edge_hwnd()
    if not hwnd:
        print("  [warn] edge window not found")
        return False
    user32 = ctypes.windll.user32
    SWP_SHOWWINDOW = 0x0040
    HWND_TOPMOST = -1
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, CLIP_W, CLIP_H, SWP_SHOWWINDOW)
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True


def edge_window_rect():
    hwnd = _find_edge_hwnd()
    if not hwnd:
        return None
    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


_EDGE_PID = None


def launch_edge():
    global _EDGE_PID
    shutil.rmtree(PROFILE, ignore_errors=True)
    cmd = [
        EDGE,
        f"--remote-debugging-port={PORT}",
        f"--user-data-dir={PROFILE}",
        f"--app={BASE_URL}/login",
        f"--window-size={CLIP_W},{CLIP_H}",
        "--window-position=0,0",
        "--no-first-run",
        "--no-default-browser-check",
        "--force-device-scale-factor=1",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--disable-gpu",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-features=CalculateNativeWinOcclusion",
    ]
    proc = subprocess.Popen(cmd, stdout=DEVNULL, stderr=DEVNULL, creationflags=CREATE_NO_WINDOW)
    _EDGE_PID = proc.pid


def kill_edge():
    for pid in _browser_pids():
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=DEVNULL, stderr=DEVNULL,
        )


def get_page_ws_url():
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            pages = httpx.get(
                f"http://127.0.0.1:{PORT}/json",
                timeout=3, trust_env=False,
            ).json()
            for page in pages:
                if page.get("type") == "page" and "localhost:5174" in page.get("url", ""):
                    return page["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("edge page target not found")


# -------------------------------------------------------------------- cdp


class CDP:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self._id = 0
        self._pending = {}
        self._events = asyncio.Queue()
        self._reader = None

    async def connect(self):
        self.ws = await connect(self.ws_url, max_size=2**26)
        self._reader = asyncio.ensure_future(self._read_loop())

    async def _read_loop(self):
        try:
            while True:
                msg = json.loads(await self.ws.recv())
                if msg.get("id") in self._pending:
                    fut = self._pending.pop(msg["id"])
                    if "error" in msg:
                        fut.set_exception(RuntimeError(f"CDP: {msg['error']}"))
                    else:
                        fut.set_result(msg.get("result", {}))
                else:
                    self._events.put_nowait(msg)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def close(self):
        if self._reader:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
            self._reader = None
        if self.ws:
            await self.ws.close()

    async def send(self, method, params=None):
        self._id += 1
        fut = asyncio.get_event_loop().create_future()
        self._pending[self._id] = fut
        await self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        try:
            return await asyncio.wait_for(fut, timeout=60)
        except asyncio.TimeoutError:
            self._pending.pop(self._id, None)
            raise RuntimeError(f"CDP {method}: timeout")

    async def next_event(self):
        return await self._events.get()

    async def eval(self, expr):
        result = await self.send("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "awaitPromise": True,
        })
        if "exceptionDetails" in result:
            return None
        return result.get("result", {}).get("value")

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)

    async def wait_for(self, expr, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await self.eval(expr):
                return True
            await asyncio.sleep(0.3)
        raise RuntimeError(f"wait_for timeout: {expr[:100]}")

    async def goto(self, url):
        await self.send("Page.navigate", {"url": url})
        await self.wait_for("document.readyState === 'complete'", 20)
        await asyncio.sleep(1.0)

    async def focus(self, selector):
        ok = await self.eval(
            "(() => { const el = document.querySelector(%s);"
            " if (!el) return false; el.focus();"
            " el.scrollIntoView({block:'center', behavior:'instant'});"
            " return true; })()" % json.dumps(selector)
        )
        return bool(ok)

    async def select_all(self):
        vk_a = 65
        await self.send("Input.dispatchKeyEvent", {
            "type": "keyDown", "modifiers": 2, "key": "a", "code": "KeyA",
            "windowsVirtualKeyCode": vk_a, "nativeVirtualKeyCode": vk_a,
        })
        await self.send("Input.dispatchKeyEvent", {
            "type": "keyUp", "modifiers": 2, "key": "a", "code": "KeyA",
            "windowsVirtualKeyCode": vk_a, "nativeVirtualKeyCode": vk_a,
        })

    async def type_sel(self, selector, text, clear=True):
        if not await self.focus(selector):
            raise RuntimeError(f"element not found: {selector}")
        await asyncio.sleep(0.35)
        if clear:
            await self.select_all()
        await self.send("Input.insertText", {"text": text})
        await asyncio.sleep(0.35)

    async def click(self, selector):
        ok = await self.eval(
            "(() => { const el = document.querySelector(%s);"
            " if (!el) return false;"
            " el.scrollIntoView({block:'center', behavior:'instant'});"
            " el.click(); return true; })()" % json.dumps(selector)
        )
        if not ok:
            raise RuntimeError(f"click target not found: {selector}")

    async def click_text(self, text):
        ok = await self.eval(
            "(() => { const el = [...document.querySelectorAll('button,a')]"
            ".find(b => b.textContent.trim().includes(%s));"
            " if (!el) return false;"
            " el.scrollIntoView({block:'center', behavior:'instant'});"
            " el.click(); return true; })()" % json.dumps(text)
        )
        if not ok:
            raise RuntimeError(f"click text not found: {text}")

    async def select_value(self, selector, value):
        ok = await self.eval(
            "(() => { const el = document.querySelector(%s);"
            " if (!el) return false;"
            " const setter = Object.getOwnPropertyDescriptor("
            " HTMLSelectElement.prototype, 'value').set;"
            " setter.call(el, %s);"
            " el.dispatchEvent(new Event('change', {bubbles: true}));"
            " return true; })()" % (json.dumps(selector), json.dumps(value))
        )
        if not ok:
            raise RuntimeError(f"select not found: {selector}")

    async def upload(self, selector, path):
        doc = await self.send("DOM.getDocument", {"depth": -1, "pierce": True})
        root_id = doc["root"]["nodeId"]
        found = await self.send("DOM.querySelector", {"nodeId": root_id, "selector": selector})
        node_id = found.get("nodeId", 0)
        if not node_id:
            raise RuntimeError(f"file input not found: {selector}")
        await self.send("DOM.setFileInputFiles", {
            "nodeId": node_id, "files": [str(path)],
        })

    async def flash_dropzone(self):
        await self.eval(
            "(() => { const dz = document.querySelector('.drop');"
            " if (!dz) return false;"
            " const dt = new DataTransfer();"
            " dz.dispatchEvent(new DragEvent('dragenter', {bubbles: true, dataTransfer: dt}));"
            " dz.dispatchEvent(new DragEvent('dragover', {bubbles: true, dataTransfer: dt}));"
            " return true; })()"
        )

    async def unflash_dropzone(self):
        await self.eval(
            "(() => { const dz = document.querySelector('.drop');"
            " if (!dz) return false;"
            " const dt = new DataTransfer();"
            " dz.dispatchEvent(new DragEvent('dragleave', {bubbles: true, dataTransfer: dt}));"
            " return true; })()"
        )

    async def smooth_scroll(self, steps, step_px=110, pause=0.9):
        for _ in range(steps):
            await self.eval("window.scrollBy({top: %d, behavior: 'smooth'})" % step_px)
            await asyncio.sleep(pause)

    async def login(self, email, password):
        await self.eval("localStorage.clear()")
        await self.send("Page.reload")
        await self.wait_for("!!document.querySelector('.login-card')", 20)
        await asyncio.sleep(1.3)
        await self.type_sel(".login-card input[type=email]", email)
        await asyncio.sleep(0.5)
        await self.type_sel(".login-card input[type=password]", password)
        await asyncio.sleep(0.6)
        await self.click(".login-card .btn")
        await self.wait_for("!!document.querySelector('.shell')", 20)
        await asyncio.sleep(0.8)
        # dismiss any native password-save bubble with a real Escape keypress
        ctypes.windll.user32.keybd_event(0x1B, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x1B, 0, 2, 0)
        await asyncio.sleep(1.0)


# ---------------------------------------------------------------- scenes


async def scene_test(cdp: CDP):
    await asyncio.sleep(2)
    await cdp.login(BUYER, PASSWORD)
    await asyncio.sleep(3)


async def scene_a(cdp: CDP):
    # buyer creates the case
    await cdp.login(BUYER, PASSWORD)
    await asyncio.sleep(2.2)

    seller_id = get_user_id(SELLER)

    await cdp.click(".pagehead .btn")  # New Order
    await cdp.wait_for("!!document.querySelector('form.card')")
    await asyncio.sleep(1.6)

    await cdp.type_sel("form.card input", CASE_TITLE)
    await asyncio.sleep(0.8)
    await cdp.type_sel("form.card input[type=number]", str(seller_id))
    await asyncio.sleep(0.8)
    await cdp.type_sel("form.card input[step]", "29.99")
    await asyncio.sleep(0.8)
    await cdp.type_sel("form.card textarea", CASE_DESCRIPTION)
    await asyncio.sleep(1.2)

    await cdp.click("form.card button.btn")
    await cdp.wait_for("location.pathname.includes('/agreement')", 15)
    await asyncio.sleep(4.0)


async def scene_b(cdp: CDP):
    # seller uploads evidence and generates the report
    await cdp.login(SELLER, PASSWORD)
    await asyncio.sleep(2.2)

    await cdp.click("table tr.click")
    await cdp.wait_for("location.pathname.includes('/analysis')")
    await asyncio.sleep(2.0)

    await cdp.click("a[href*='/evidence']")
    await cdp.wait_for("location.pathname.includes('/evidence')")
    await asyncio.sleep(1.8)

    await cdp.flash_dropzone()
    await asyncio.sleep(0.8)
    await cdp.upload("input[type=file]", ASSETS / "order-confirmation-PB-1042.pdf")
    await cdp.unflash_dropzone()
    await cdp.wait_for("document.querySelectorAll('td.fname').length >= 1", 15)
    await asyncio.sleep(2.4)

    await cdp.flash_dropzone()
    await asyncio.sleep(0.8)
    await cdp.upload("input[type=file]", ASSETS / "shipping-delivery-note.pdf")
    await cdp.unflash_dropzone()
    await cdp.wait_for("document.querySelectorAll('td.fname').length >= 2", 15)
    await asyncio.sleep(2.4)

    await cdp.click("a[href*='/analysis']")
    await cdp.wait_for("location.pathname.includes('/analysis')")
    await asyncio.sleep(1.8)

    await cdp.click(".pagehead .btn")  # Generate support report
    await cdp.wait_for("document.body.innerText.includes('Supported')", 90)
    await asyncio.sleep(6.0)


async def scene_c(cdp: CDP):
    # buyer reviews the report and submits for support review
    await cdp.login(BUYER, PASSWORD)
    await asyncio.sleep(2.2)

    await cdp.click("table tr.click")
    await cdp.wait_for("location.pathname.includes('/analysis')")
    await asyncio.sleep(2.0)

    await cdp.click("a[href*='/report']")
    await cdp.wait_for("location.pathname.includes('/report')")
    await asyncio.sleep(2.4)

    await cdp.smooth_scroll(13, 120, 0.85)
    await asyncio.sleep(1.5)
    await cdp.eval("window.scrollTo({top: 0, behavior: 'smooth'})")
    await asyncio.sleep(1.6)

    await cdp.click("a[href*='/analysis']")
    await cdp.wait_for("location.pathname.includes('/analysis')")
    await asyncio.sleep(1.8)

    await cdp.click(".pagehead button.ghost")  # Submit for support review
    await cdp.wait_for("!document.body.innerText.includes('Submit for support review')", 20)
    await asyncio.sleep(3.2)


async def scene_d(cdp: CDP):
    # support agent records the decision
    await cdp.login(AGENT, PASSWORD)
    await asyncio.sleep(2.2)

    await cdp.click("table tr.click")
    await cdp.wait_for("location.pathname.includes('/analysis')")
    await asyncio.sleep(1.8)

    await cdp.click("a[href*='/review']")
    await cdp.wait_for("location.pathname.includes('/review')")
    await asyncio.sleep(2.2)

    await cdp.select_value("form.form select", "partially_verified")
    await asyncio.sleep(1.3)
    await cdp.type_sel("form.form textarea", REVIEW_NOTES)
    await asyncio.sleep(1.7)

    await cdp.click("form.form .btn")
    await cdp.wait_for("!document.querySelector('form.form')", 20)
    await asyncio.sleep(2.0)

    await cdp.goto(BASE_URL + "/")
    await cdp.wait_for("!!document.querySelector('.shell')")
    await asyncio.sleep(3.0)

    # buyer pays through PayPal
    await cdp.login(BUYER, PASSWORD)
    await asyncio.sleep(2.0)

    await cdp.click("table tr.click")
    await cdp.wait_for("location.pathname.includes('/analysis')")
    await asyncio.sleep(1.2)

    await cdp.click("a[href*='/agreement']")
    await cdp.wait_for("location.pathname.includes('/agreement')")
    await asyncio.sleep(2.0)

    await cdp.click_text("Pay with PayPal")
    await cdp.wait_for("location.host.includes('paypal.com')", 30)
    await asyncio.sleep(8.0)


async def scene_e(cdp: CDP):
    # closing dashboard
    await cdp.login(BUYER, PASSWORD)
    await asyncio.sleep(3.2)
    await cdp.smooth_scroll(6, 110, 0.9)
    await asyncio.sleep(1.5)
    await cdp.eval("window.scrollTo({top: 0, behavior: 'smooth'})")
    await asyncio.sleep(3.5)


SCENES = {
    "test": scene_test,
    "a": scene_a,
    "b": scene_b,
    "c": scene_c,
    "d": scene_d,
    "e": scene_e,
}

CLIP_NAMES = {
    "test": "clip_test.mp4",
    "a": "clip_a_creating_a_case.mp4",
    "b": "clip_b_evidence_and_ai_analysis.mp4",
    "c": "clip_c_investigation_report.mp4",
    "d": "clip_d_paypal_and_human_review.mp4",
    "e": "clip_e_closing_dashboard.mp4",
}


def get_user_id(email):
    resp = httpx.post(
        API_URL + "/auth/login",
        data={"username": email, "password": PASSWORD},
        timeout=15, trust_env=False,
    )
    token = resp.json()["access_token"]
    me = httpx.get(
        API_URL + "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15, trust_env=False,
    ).json()
    return me["id"]


# ------------------------------------------------------------- screencast

ANIM_INJECT = (
    "(() => { if (window.__pbrec) return true;"
    " const d=document.createElement('div');"
    " d.style.cssText='position:fixed;right:0;bottom:0;width:1px;height:1px;"
    " pointer-events:none;z-index:-1;will-change:opacity';"
    " document.body.appendChild(d);"
    " const st=document.createElement('style');"
    " st.textContent='@keyframes pbrec{from{opacity:.5}to{opacity:.6}}';"
    " document.head.appendChild(st);"
    " d.style.animation='pbrec .06s linear infinite alternate';"
    " window.__pbrec=true; return true; })()"
)


async def anim_keepalive(cdp):
    while True:
        try:
            await cdp.eval(ANIM_INJECT)
        except Exception:
            pass
        await asyncio.sleep(1.5)


class ScreencastRecorder:
    def __init__(self, cdp, frames_dir):
        self.cdp = cdp
        self.dir = frames_dir
        self._task = None
        self._count = 0
        self._times = []

    async def _run(self):
        await self.cdp.send("Page.startScreencast", {
            "format": "jpeg", "quality": 80,
            "maxWidth": CLIP_W, "maxHeight": CLIP_H,
        })
        interval = 1.0 / 25.0
        next_slot = time.monotonic()
        try:
            while True:
                msg = await self.cdp.next_event()
                if msg.get("method") != "Page.screencastFrame":
                    continue
                params = msg["params"]
                data = base64.b64decode(params["data"])
                self._count += 1
                (self.dir / f"f{self._count:06d}.jpg").write_bytes(data)
                self._times.append(time.monotonic())
                await self.cdp.send("Page.screencastFrameAck", {
                    "sessionId": params["sessionId"],
                })
                next_slot += interval
                delay = next_slot - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    next_slot = time.monotonic()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print("  [warn] screencast:", exc)
        finally:
            try:
                await self.cdp.send("Page.stopScreencast", {})
            except Exception:
                pass

    def start(self):
        self._task = asyncio.ensure_future(self._run())

    async def stop(self):
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        (self.dir / "times.json").write_text(json.dumps(self._times))


def encode_frames(frames_dir, out_path):
    times = json.loads((frames_dir / "times.json").read_text())
    files = sorted(frames_dir.glob("f*.jpg"))
    if not files or not times:
        raise RuntimeError("no screencast frames captured")
    n = len(files)
    avg = (times[-1] - times[0]) / max(1, n - 1) if n > 1 else 0.04
    durations = [
        times[i + 1] - times[i] if i + 1 < n else avg
        for i in range(n)
    ]
    durations = [min(max(d, 0.02), 0.25) for d in durations]
    concat = frames_dir / "concat.txt"
    with open(concat, "w") as fh:
        for i, f in enumerate(files):
            fh.write("file '%s'\n" % str(f).replace("\\", "/"))
            fh.write("duration %.3f\n" % durations[i])
        fh.write("file '%s'\n" % str(files[-1]).replace("\\", "/"))
    subprocess.run(
        [
            FFMPEG, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(out_path),
        ],
        stdout=DEVNULL, stderr=DEVNULL,
        creationflags=CREATE_NO_WINDOW,
        check=True,
    )
    print("frames:", n, "duration: %.1fs" % sum(durations))


# ------------------------------------------------------------------- main


async def run_scene(scene_name):
    CLIPS.mkdir(exist_ok=True)
    out_path = CLIPS / CLIP_NAMES[scene_name]
    scene = SCENES[scene_name]
    frames_dir = CLIPS / "frames_tmp"
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir()

    launch_edge()
    ws_url = get_page_ws_url()
    cdp = CDP(ws_url)
    await cdp.connect()

    await cdp.send("Emulation.setDeviceMetricsOverride", {
        "width": CLIP_W, "height": CLIP_H,
        "deviceScaleFactor": 1, "mobile": False,
    })
    await cdp.wait_for("!!document.querySelector('.login-card')", 30)
    viewport = await cdp.eval("({w: innerWidth, h: innerHeight, dpr: devicePixelRatio})")
    print("viewport:", viewport)

    force_foreground()
    await asyncio.sleep(1.2)
    force_foreground()
    print("visibility:", await cdp.eval("document.visibilityState"))

    rec = ScreencastRecorder(cdp, frames_dir)
    rec.start()
    await asyncio.sleep(1.5)

    keeper = asyncio.ensure_future(anim_keepalive(cdp))
    scene_error = None
    try:
        await scene(cdp)
    except Exception as exc:
        scene_error = exc
        print("  [warn] scene error:", exc)
    keeper.cancel()
    await asyncio.gather(keeper, return_exceptions=True)

    await rec.stop()
    await cdp.close()
    kill_edge()

    try:
        encode_frames(frames_dir, out_path)
    except Exception as exc:
        print("  [warn] encode:", exc)
    shutil.rmtree(frames_dir, ignore_errors=True)

    if scene_error:
        print("scene failed; clip may be incomplete:", scene_error)
    print("clip written:", out_path)
    size = out_path.stat().st_size if out_path.exists() else 0
    print("size:", size, "bytes")


def main():
    scene_name = sys.argv[1] if len(sys.argv) > 1 else "test"
    if scene_name not in SCENES:
        sys.exit(f"unknown scene {scene_name!r}; use one of {sorted(SCENES)}")
    asyncio.run(run_scene(scene_name))


if __name__ == "__main__":
    main()
