from http.server import BaseHTTPRequestHandler
from PIL import Image
import requests
import io
import json
import os
import base64
import urllib.request
import urllib.parse

# Placeholder frame coordinates (x1, y1, x2, y2) per template
# Template 6 has two mugs (Front + Back) — design applied to both
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
    """Scale image to cover the target box, crop excess from centre."""
    img_w, img_h = image.size
    scale = max(target_w / img_w, target_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    resized = image.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def generate_mockup_bytes(design, template_num):
    """Composite design onto template and return JPEG bytes."""
    template_path = os.path.join(TEMPLATES_DIR, f"{template_num}.png")
    template = Image.open(template_path).convert("RGBA")
    for (x1, y1, x2, y2) in FRAMES[template_num]:
        fitted = resize_cover(design, x2 - x1, y2 - y1)
        template.paste(fitted, (x1, y1), fitted)
    buf = io.BytesIO()
    template.convert("RGB").save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def upload_to_imgbb(img_bytes, filename):
    """Upload to ImgBB, return public URL. Needs IMGBB_API_KEY env var."""
    api_key = os.environ.get("IMGBB_API_KEY", "")
    if not api_key:
        return None
    payload = urllib.parse.urlencode({
        "key": api_key,
        "image": base64.b64encode(img_bytes).decode("utf-8"),
        "name": filename,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.imgbb.com/1/upload", data=payload, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        if result.get("success"):
            return result["data"]["display_url"]
    return None


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self._cors_headers(200)
        self.end_headers()

    def do_GET(self):
        """Health check."""
        self._cors_headers(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok",
            "templates": sorted(FRAMES.keys()),
            "imgbb_configured": bool(os.environ.get("IMGBB_API_KEY")),
        }).encode())

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))

            design_url = body.get("design_url", "").strip()
            templates = body.get("templates", sorted(FRAMES.keys()))

            if not design_url:
                return self._error(400, "Missing design_url")

            invalid = [t for t in templates if t not in FRAMES]
            if invalid:
                return self._error(
                    400,
                    f"Invalid template numbers: {invalid}. Valid: {sorted(FRAMES.keys())}"
                )

            # Download design image ONCE — reused across all templates
            resp = requests.get(design_url, timeout=30)
            resp.raise_for_status()
            design = Image.open(io.BytesIO(resp.content)).convert("RGBA")

            urls = []
            errors = []

            for t in templates:
                try:
                    img_bytes = generate_mockup_bytes(design, t)
                    url = upload_to_imgbb(img_bytes, f"mockup_{t}.jpg")

                    if url:
                        urls.append(url)
                    else:
                        # Fallback: base64 data URI (works if ImgBB key not set)
                        b64 = base64.b64encode(img_bytes).decode("utf-8")
                        urls.append(f"data:image/jpeg;base64,{b64}")

                except Exception as e:
                    errors.append({"template": t, "error": str(e)})

            result = {
                "urls": urls,
                "count": len(urls),
                "templates_processed": templates,
            }
            if errors:
                result["errors"] = errors

            self._cors_headers(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode("utf-8"))

        except Exception as e:
            self._error(500, str(e))

    def _cors_headers(self, code):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _error(self, code, message):
        self._cors_headers(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode())

    def log_message(self, format, *args):
        pass  # suppress default logging
