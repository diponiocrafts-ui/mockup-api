from http.server import BaseHTTPRequestHandler
from PIL import Image
import requests
import io
import json
import os

# Detected placeholder frame coordinates (x1, y1, x2, y2) per template
# Template 6 has two mugs (Front + Back) — design is applied to both
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
    """Scale image to cover the target size, crop excess from center."""
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
            template_num = int(body.get("template", 1))

            if not design_url:
                self._error(400, "Missing design_url")
                return
            if template_num not in FRAMES:
                self._error(400, f"Invalid template number. Must be 1-9.")
                return

            # Load template image from disk
            template_path = os.path.join(TEMPLATES_DIR, f"{template_num}.png")
            template = Image.open(template_path).convert("RGBA")

            # Download the design image
            resp = requests.get(design_url, timeout=20)
            resp.raise_for_status()
            design = Image.open(io.BytesIO(resp.content)).convert("RGBA")

            # Paste design into each frame box
            for (x1, y1, x2, y2) in FRAMES[template_num]:
                frame_w = x2 - x1
                frame_h = y2 - y1
                design_fitted = resize_cover(design, frame_w, frame_h)
                # Use alpha channel as mask for smooth blending
                template.paste(design_fitted, (x1, y1), design_fitted)

            # Output as high-quality JPEG
            output = io.BytesIO()
            template.convert("RGB").save(output, format="JPEG", quality=92)
            img_bytes = output.getvalue()

            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(img_bytes)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(img_bytes)

        except Exception as e:
            self._error(500, str(e))

    def do_GET(self):
        """Health check endpoint."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "templates": list(FRAMES.keys())}).encode())

    def _error(self, code, message):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode())

    def log_message(self, format, *args):
        pass  # Suppress default logging
