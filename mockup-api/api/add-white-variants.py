from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.error

PRINTIFY_SHOP_ID = os.environ.get("PRINTIFY_SHOP_ID", "12909290")
BLUEPRINT_ID = "635"


def _http_error_detail(e):
    try:
        body = e.read().decode("utf-8", errors="replace")
    except Exception:
        body = "(unreadable)"
    return f"HTTP {e.code}: {body}"


def printify_get(path, token):
    req = urllib.request.Request(
        f"https://api.printify.com{path}",
        headers={"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"[GET {path}] {_http_error_detail(e)}"
    except Exception as e:
        return None, f"[GET {path}] {str(e)}"


def printify_put(path, body_dict, token):
    body = json.dumps(body_dict).encode()
    req = urllib.request.Request(
        f"https://api.printify.com{path}",
        data=body,
        method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"[PUT {path}] {_http_error_detail(e)}"
    except Exception as e:
        return None, f"[PUT {path}] {str(e)}"


def find_white_variant_ids(all_variants):
    white_11oz_id = None
    white_15oz_id = None
    for v in all_variants:
        title = v.get("title", "").lower()
        is_white = "white" in title
        is_11oz = "11" in title
        is_15oz = "15" in title
        if is_white and is_11oz:
            white_11oz_id = v.get("id")
        elif is_white and is_15oz:
            white_15oz_id = v.get("id")
        if white_11oz_id and white_15oz_id:
            break
    return white_11oz_id, white_15oz_id


def price_for_size(product_variants, oz):
    for v in product_variants:
        title = v.get("title", "").lower()
        if str(oz) in title and v.get("is_enabled", True):
            return v.get("price", 1874)
    for v in product_variants:
        if v.get("is_enabled", True):
            return v.get("price", 1874)
    return 1874


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
            "endpoint": "add-white-variants",
            "version": "v3",
        }).encode())

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))

            product_id = str(body.get("product_id", "")).strip()
            if not product_id:
                return self._json({"status": "error", "error": "Missing product_id"})

            token = body.get("printify_token") or os.environ.get("PRINTIFY_API_TOKEN", "")
            if not token:
                return self._json({"status": "error", "error": "No Printify token"})

            shop_id = PRINTIFY_SHOP_ID

            product, err = printify_get(f"/v1/shops/{shop_id}/products/{product_id}.json", token)
            if err:
                return self._json({"status": "error", "error": err})

            print_provider_id = product.get("print_provider_id")
            if not print_provider_id:
                return self._json({"status": "error", "error": "No print_provider_id in product"})

            existing_variants = product.get("variants", [])
            existing_ids = {v["id"] for v in existing_variants}

            catalog, err = printify_get(
                f"/v1/catalog/blueprints/{BLUEPRINT_ID}/print_providers/{print_provider_id}/variants.json",
                token
            )
            if err:
                return self._json({"status": "error", "error": err})

            all_variants = catalog.get("variants", [])
            if not all_variants:
                return self._json({"status": "error", "error": "No variants in catalog"})

            white_11oz_id, white_15oz_id = find_white_variant_ids(all_variants)

            if not white_11oz_id or not white_15oz_id:
                sample = [v.get("title") for v in all_variants[:20]]
                return self._json({
                    "status": "error",
                    "error": "Could not find White 11oz and/or 15oz variants",
                    "sample_titles": sample,
                })

            added = []
            updated_variants = list(existing_variants)

            if white_11oz_id not in existing_ids:
                updated_variants.append({"id": white_11oz_id, "price": price_for_size(existing_variants, 11), "is_enabled": True})
                added.append({"id": white_11oz_id, "size": "11oz"})

            if white_15oz_id not in existing_ids:
                updated_variants.append({"id": white_15oz_id, "price": price_for_size(existing_variants, 15), "is_enabled": True})
                added.append({"id": white_15oz_id, "size": "15oz"})

            if not added:
                return self._json({"status": "ok", "message": "White variants already present", "product_id": product_id})

            new_ids = [v["id"] for v in added]
            print_areas = product.get("print_areas", [])
            for pa in print_areas:
                pa["variant_ids"] = pa.get("variant_ids", []) + new_ids

            put_body = {"variants": updated_variants}
            if print_areas:
                put_body["print_areas"] = print_areas

            result, err = printify_put(f"/v1/shops/{shop_id}/products/{product_id}.json", put_body, token)
            if err:
                return self._json({"status": "error", "error": err})

            return self._json({"status": "ok", "product_id": product_id, "variants_added": added, "total_variants": len(updated_variants)})

        except Exception as e:
            return self._json({"status": "error", "error": f"[unhandled] {str(e)}"})

    def _json(self, payload):
        self._cors_headers(200)
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
