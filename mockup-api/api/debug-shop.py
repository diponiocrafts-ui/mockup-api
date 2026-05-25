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


def get_me(access_token, shared_secret):
    req = urllib.request.Request(
        "https://openapi.etsy.com/v3/application/users/me",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-api-key": shared_secret,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"[get_me] {_http_error_detail(e)}"
    except Exception as e:
        return None, f"[get_me] {str(e)}"


def get_user_shops(user_id, access_token, shared_secret):
    req = urllib.request.Request(
        f"https://openapi.etsy.com/v3/application/users/{user_id}/shops",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-api-key": shared_secret,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"[get_shops] {_http_error_detail(e)}"
    except Exception as e:
        return None, f"[get_shops] {str(e)}"


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self._cors_headers(200)
        self.end_headers()

    def do_GET(self):
        etsy_client_id = os.environ.get("ETSY_CLIENT_ID", "")
        etsy_refresh_token = os.environ.get("ETSY_REFRESH_TOKEN", "")
        etsy_shared_secret = os.environ.get("ETSY_SHARED_SECRET", "")

        if not etsy_client_id or not etsy_refresh_token or not etsy_shared_secret:
            return self._json(200, {
                "status": "error",
                "error": "Missing credentials",
                "has_client_id": bool(etsy_client_id),
                "has_refresh_token": bool(etsy_refresh_token),
                "has_shared_secret": bool(etsy_shared_secret),
            })

        # Step 1 — get access token
        access_token, err = get_etsy_access_token(etsy_client_id, etsy_refresh_token)
        if err:
            return self._json(200, {"status": "error", "step": "token_refresh", "error": err})

        # Step 2 — get authenticated user
        me, err = get_me(access_token, etsy_shared_secret)
        if err:
            return self._json(200, {"status": "error", "step": "get_me", "error": err})

        user_id = me.get("user_id")

        # Step 3 — get shops for this user
        shops_data, err = get_user_shops(user_id, access_token, etsy_shared_secret)
        if err:
            return self._json(200, {
                "status": "error",
                "step": "get_shops",
                "error": err,
                "user_id": user_id,
            })

        # Return only safe fields — no tokens or secrets
        shops = []
        if isinstance(shops_data, dict):
            results = shops_data.get("results", [shops_data])
        elif isinstance(shops_data, list):
            results = shops_data
        else:
            results = []

        for s in results:
            shops.append({
                "shop_id": s.get("shop_id"),
                "shop_name": s.get("shop_name"),
                "user_id": s.get("user_id"),
            })

        return self._json(200, {
            "status": "ok",
            "authenticated_user_id": user_id,
            "shops": shops,
        })

    def _json(self, code, payload):
        self._cors_headers(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def _cors_headers(self, code):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format, *args):
        pass
