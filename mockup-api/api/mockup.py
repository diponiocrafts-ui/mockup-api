from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.parse
import urllib.error


def _http_error_detail(e):
    try:
        body = e.read().decode("utf-8", errors="replace")
    except Exception:
        body = "(unreadable)"
    return f"HTTP {e.code}: {body}"


def _etsy_get(url, access_token, shared_secret):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-api-key": shared_secret,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, _http_error_detail(e)
    except Exception as e:
        return None, str(e)


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


def get_shop_id(access_token, shared_secret):
    """Dynamically resolve shop_id from the OAuth token — no hardcoding."""
    me, err = _etsy_get(
        "https://openapi.etsy.com/v3/application/users/me",
        access_token, shared_secret
    )
    if err:
        return None, f"[get_me] {err}"
    user_id = me.get("user_id")
    shops, err = _etsy_get(
        f"https://openapi.etsy.com/v3/application/users/{user_id}/shops",
        access_token, shared_secret
    )
    if err:
        return None, f"[get_shops] {err}"
    results = shops.get("results", [shops]) if isinstance(shops, dict) else shops
    if not results:
        return None, "[get_shops] No shops found for this account"
    shop_id = results[0].get("shop_id")
    shop_name = results[0].get("shop_name", "unknown")
    return {"shop_id": shop_id, "shop_name": shop_name, "user_id": user_id}, None


def get_etsy_draft_listings(shop_id, access_token, shared_secret, limit=100):
    url = (
        f"https://openapi.etsy.com/v3/application/shops/{shop_id}/listings"
        f"?state=draft&limit={limit}&sort_on=created&sort_order=desc"
    )
    data, err = _etsy_get(url, access_token, shared_secret)
    if err:
        return None, f"[etsy_listings] {err}"
    return data, None


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self._cors_headers(200)
        self.end_headers()

    def do_GET(self):
        etsy_client_id = os.environ.get("ETSY_CLIENT_ID", "")
        etsy_refresh_token = os.environ.get("ETSY_REFRESH_TOKEN", "")
        etsy_shared_secret = os.environ.get("ETSY_SHARED_SECRET", "")
        return self._json(200, {
            "status": "ok",
            "endpoint": "get-listing-id",
            "has_client_id": bool(etsy_client_id),
            "has_refresh_token": bool(etsy_refresh_token),
            "has_shared_secret": bool(etsy_shared_secret),
            "x_api_key_source": "ETSY_SHARED_SECRET",
            "shop_id": "dynamic",
        })

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))

            title = body.get("title", "").strip()
            if not title:
                return self._json(200, {"status": "error", "error": "Missing title"})

            etsy_client_id = os.environ.get("ETSY_CLIENT_ID", "")
            etsy_refresh_token = os.environ.get("ETSY_REFRESH_TOKEN", "")
            etsy_shared_secret = os.environ.get("ETSY_SHARED_SECRET", "")
            if not etsy_client_id or not etsy_refresh_token or not etsy_shared_secret:
                return self._json(200, {
                    "status": "error",
                    "error": "Etsy credentials not configured",
                    "has_client_id": bool(etsy_client_id),
                    "has_refresh_token": bool(etsy_refresh_token),
                    "has_shared_secret": bool(etsy_shared_secret),
                })

            # Get fresh Etsy access token
            access_token, err = get_etsy_access_token(etsy_client_id, etsy_refresh_token)
            if err:
                return self._json(200, {"status": "error", "error": err})

            # Dynamically resolve shop_id from the OAuth token
            shop_info, err = get_shop_id(access_token, etsy_shared_secret)
            if err:
                return self._json(200, {"status": "error", "error": err})

            # Fetch recent draft listings
            result, err = get_etsy_draft_listings(shop_info["shop_id"], access_token, etsy_shared_secret)
            if err:
                return self._json(200, {"status": "error", "error": err, "shop": shop_info})

            listings = result.get("results", [])

            # Find exact title match
            matches = [l for l in listings if l.get("title", "").strip() == title]

            if not matches:
                return self._json(200, {
                    "status": "ETSY_DRAFT_NOT_FOUND",
                    "error": "ETSY_DRAFT_NOT_FOUND",
                    "searched_title": title,
                    "total_drafts_checked": len(listings),
                    "shop": shop_info,
                })

            if len(matches) > 1:
                return self._json(200, {
                    "status": "MULTIPLE_DRAFTS_FOUND",
                    "error": "MULTIPLE_DRAFTS_FOUND",
                    "count": len(matches),
                    "listing_ids": [l["listing_id"] for l in matches],
                    "listing_id": matches[0]["listing_id"],
                    "shop": shop_info,
                })

            listing = matches[0]
            return self._json(200, {
                "status": "ok",
                "listing_id": listing["listing_id"],
                "title": listing.get("title"),
                "state": listing.get("state"),
                "shop": shop_info,
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
