from http.server import BaseHTTPRequestHandler
from PIL import Image
import requests
import io
import json
import os
import base64

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


def resize_cover(image, target_w, target_h):
    img_w, img_h = image.size
    scale = max(target_w / img_w, target_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    resized = image.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            body = json.loads(post_data)
            design_url = body.get("design_url", "").strip()
            templates = body.get("templates", list(range(1, 10)))
            if not design_url:
                self._error(400, "Missing design_url")
                return
            resp = requests.get(design_url, timeout=15)
            resp.raise_for_status()
            design_bytes = resp.content
            images = []
            for t in templates:
                t = int(t)
                if t not in FRAMES:
                    self._error(400, f"Invalid template: {t}")
                    return
                design = Image.open(io.BytesIO(design_bytes)).convert("RGBA")
                template_path = os.path.join(TEMPLATES_DIR, f"{t}.png")
                template = Image.open(template_path).convert("RGBA")
                for (x1, y1, x2, y2) in FRAMES[t]:
                    frame_w = x2 - x1
                    frame_h = y2 - y1
                    design_fitted = resize_cover(design, frame_w, frame_h)
                    template.paste(design_fitted, (x1, y1), design_fitted)
                tw, th = template.size
                if tw > 1000:
                    scale = 1000 / tw
                    template = template.resize((1000, int(th * scale)), Image.LANCZOS)
                output = io.BytesIO()
                template.convert("RGB").save(output, format="JPEG", quality=75)
                b64 = base64.b64encode(output.getvalue()).decode("utf-8")
                images.append(b64)
            self._json(200, {"images": images, "count": len(images)})
        except Exception as e:
            self._error(500, str(e))

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

    def _error(self, code, message):
        self._json(code, {"error": message})

    def log_message(self, format, *args):
        pass
