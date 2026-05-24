from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.parse
import urllib.error

ETSY_SHOP_ID = "48241816"


def _http_error_detail(e):
    try:
        body = e.read().decode("utf-8", errors="replace")
    except Exception:
        body = "(unreadable)"
    return f"HTTP {e.code}: {body}"


def get_etsy_access_token(client_id, refresh_token):
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }).encode()
    req = urllib.request.Request(
        "https://api.etsy.com/v3/public/oauth/token",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            return result["access_token"], None
    except urllib.error.HTTPError as e:
        return None, f"[token_refresh] {_http_error_detail(e)}"
    except Exception as e:
        return None, f"[token_refresh] {str(e)}"


def get_etsy_draft_listings(access_token, client_id, limit=100):
    url = (
        f"https://openapi.etsy.com/v3/application/shops/{ETSY_SHOP_ID}/listings"
        f"?state=draft&limit={limit}&sort_on=created&sort_order=desc"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-api-key": client_id,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"[etsy_listings] {_http_error_detail(e)}"
    except Exception as e:
        return None, f"[etsy_listings] {str(e)}"


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self._cors_headers(200)
        self.end_headers()

    def do_GET(self):
        self._cors_headers(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok",
            "endpoint": "get-listing-id",
            "etsy_configured": bool(
                os.environ.get("ETSY_CLIENT_ID") and os.environ.get("ETSY_REFRESH_TOKEN")
            ),
        }).encode())

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))

            title = body.get("title", "").strip()
            if not title:
                return self._json(200, {"status": "error", "error": "Missing title"})

            etsy_client_id = os.environ.get("ETSY_CLIENT_ID", "")
            etsy_refresh_token = os.environ.get("ETSY_REFRESH_TOKEN", "")
            if not etsy_client_id or not etsy_refresh_token:
                return self._json(200, {
                    "status": "error",
                    "error": "Etsy credentials not configured (ETSY_CLIENT_ID / ETSY_REFRESH_TOKEN)",
                })

            # Get fresh Etsy access token
            access_token, err = get_etsy_access_token(etsy_client_id, etsy_refresh_token)
            if err:
                return self._json(200, {"status": "error", "error": err})

            # Fetch recent draft listings
            result, err = get_etsy_draft_listings(access_token, etsy_client_id)
            if err:
                return self._json(200, {"status": "error", "error": err})

            listings = result.get("results", [])

            # Find exact title match
            matches = [l for l in listings if l.get("title", "").strip() == title]

            if not matches:
                return self._json(200, {
                    "status": "ETSY_DRAFT_NOT_FOUND",
                    "error": "ETSY_DRAFT_NOT_FOUND",
                    "searched_title": title,
                    "total_drafts_checked": len(listings),
                })

            if len(matches) > 1:
                return self._json(200, {
                    "status": "MULTIPLE_DRAFTS_FOUND",
                    "error": "MULTIPLE_DRAFTS_FOUND",
                    "count": len(matches),
                    "listing_ids": [l["listing_id"] for l in matches],
                    # Pick the most recent one anyway
                    "listing_id": matches[0]["listing_id"],
                })

            listing = matches[0]
            return self._json(200, {
                "status": "ok",
                "listing_id": listing["listing_id"],
                "title": listing.get("title"),
                "state": listing.get("state"),
            })

        except Exception as e:
            return self._json(200, {"status": "error", "error": f"[unhandled] {str(e)}"})

    def _json(self, code, payload):
        self._cors_headers(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def _cors_headers(self, code):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format, *args):
        pass
