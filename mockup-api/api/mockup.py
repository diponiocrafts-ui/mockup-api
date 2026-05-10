from http.server import BaseHTTPRequestHandler
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import io
import json
import os
import traceback

FRAMES = {
    1: [(618, 397, 1348, 1293)],
    2: [(505, 286, 1279, 1232)],
    3: [(505, 286, 1279, 1232)],
    4: [(607, 370, 1196, 1195)],
    5: [(512, 294, 1254, 1291)],
    6: [(320, 449, 799, 1167), (963, 449, 1441, 1167)],
    7: [(574, 400, 1239, 1284)],
    8: [(557, 149, 1223, 1203)],
    9: [(507, 230, 1173, 1295)],
}

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

# Cache template images at module level — reused across warm invocations
_template_cache = {}


def get_template(t):
    if t not in _template_cache:
        path = os.path.join(TEMPLATES_DIR, f"{t}.png")
        _template_cache[t] = Image.open(path).convert("RGBA")
    return _template_cache[t].copy()


def resize_cover(image, target_w, target_h):
    img_w, img_h = image.size
    scale = max(target_w / img_w, target_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    resized = image.resize((new_w, new_h), Image.BILINEAR)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def generate_and_upload(args):
    """Generate one mockup and upload it immediately — pipelined per thread."""
    t, design_bytes, index = args
    design = Image.open(io.BytesIO(design_bytes)).convert("RGBA")
    template = get_template(t)

    for (x1, y1, x2, y2) in FRAMES[t]:
        frame_w = x2 - x1
        frame_h = y2 - y1
        design_fitted = resize_cover(design, frame_w, frame_h)
        template.paste(design_fitted, (x1, y1), design_fitted)

    tw, th = template.size
    if tw > 800:
        scale = 800 / tw
        template = template.resize((800, int(th * scale)), Image.BILINEAR)

    output = io.BytesIO()
    template.convert("RGB").save(output, format="JPEG", quality=55)
    img_bytes = output.getvalue()

    # Upload to 0x0.st (no API key required)
    resp = requests.post(
        "https://0x0.st",
        files={"file": (f"mockup_{index}.jpg", img_bytes, "image/jpeg")},
        timeout=8,
    )
    resp.raise_for_status()
    url = resp.text.strip()
    if not url.startswith("http"):
        raise ValueError(f"Bad 0x0.st response: {url!r}")
    return index, url


class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            # Make.com uses chunked transfer encoding — no Content-Length header
            content_length = int(self.headers.get("Content-Length") or 0)
            if content_length > 0:
                post_data = self.rfile.read(content_length)
            else:
                post_data = self.rfile.read(524288)

            if not post_data:
                self._json(200, {
                    "urls": [],
                    "error": "Empty request body",
                    "step": "read_body",
                })
                return

            body = json.loads(post_data)
            design_url = body.get("design_url", "").strip()
            templates = body.get("templates", list(range(1, 10)))

            if not design_url:
                self._json(200, {"urls": [], "error": "Missing design_url", "step": "validation"})
                return

            try:
                templates = [int(t) for t in templates]
            except Exception as e:
                self._json(200, {"urls": [], "error": f"Template parse error: {e}", "step": "validation"})
                return

            for t in templates:
                if t not in FRAMES:
                    self._json(200, {"urls": [], "error": f"Invalid template: {t}", "step": "validation"})
                    return

            # Download design once
            try:
                resp = requests.get(design_url, timeout=10)
                resp.raise_for_status()
                design_bytes = resp.content
            except Exception as e:
                self._json(200, {"urls": [], "error": f"Download failed: {e}", "step": "download"})
                return

            # Parallel: each thread generates + uploads one mockup
            try:
                urls = [None] * len(templates)
                args_list = [(t, design_bytes, i) for i, t in enumerate(templates)]
                with ThreadPoolExecutor(max_workers=len(templates)) as executor:
                    futures = {executor.submit(generate_and_upload, a): a[2] for a in args_list}
                    for future in as_completed(futures):
                        i, url = future.result()
                        urls[i] = url
            except Exception as e:
                tb = traceback.format_exc()
                self._json(200, {
                    "urls": [],
                    "error": f"Process failed: {e}",
                    "step": "process",
                    "trace": tb[:500],
                })
                return

            self._json(200, {"urls": urls, "count": len(urls)})

        except Exception as e:
            tb = traceback.format_exc()
            self._json(200, {
                "urls": [],
                "error": f"Outer error: {e}",
                "step": "outer",
                "trace": tb[:300],
            })

    def do_GET(self):
        self._json(200, {"status": "ok", "templates": list(FRAMES.keys())})

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass
