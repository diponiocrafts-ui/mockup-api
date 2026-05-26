from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.parse
import urllib.error

PRINTIFY_SHOP_ID = "12909290"

# Fixed SKUs for the pre-created Printify White mug product (blueprint 478, ID: 6a0bf3405254961412080457)
WHITE_11OZ_SKU = "24873414371188792626"
WHITE_15OZ_SKU = "80484685462245870793"


def _http_error_detail(e):
    """Extract status code and body from an HTTPError."""
    try:
        body = e.read().decode("utf-8", errors="replace")
    except Exception:
        body = "(unreadable)"
    return f"HTTP {e.code}: {body}"


def get_etsy_access_token(client_id, refresh_token):
    """Get a fresh Etsy access token using the stored refresh token."""
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


def get_printify_product(printify_token, product_id):
    """Get Printify product — we need external.id (Etsy listing ID)."""
    req = urllib.request.Request(
        f"https://api.printify.com/v1/shops/{PRINTIFY_SHOP_ID}/products/{product_id}.json",
        headers={"Authorization": f"Bearer {printify_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"[printify_get] {_http_error_detail(e)}"
    except Exception as e:
        return None, f"[printify_get] {str(e)}"


def get_etsy_inventory(listing_id, access_token, client_id):
    """GET current Etsy listing inventory."""
    req = urllib.request.Request(
        f"https://openapi.etsy.com/v3/application/listings/{listing_id}/inventory",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-api-key": client_id,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"[inventory_get] {_http_error_detail(e)}"
    except Exception as e:
        return None, f"[inventory_get] {str(e)}"


def put_etsy_inventory(listing_id, access_token, client_id, products):
    """PUT updated inventory back to Etsy (replaces all variants)."""
    data = json.dumps({"products": products}).encode()
    req = urllib.request.Request(
        f"https://openapi.etsy.com/v3/application/listings/{listing_id}/inventory",
        data=data,
        method="PUT",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-api-key": client_id,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"[inventory_put] {_http_error_detail(e)}"
    except Exception as e:
        return None, f"[inventory_put] {str(e)}"


def money_to_float(price_obj):
    """Convert Etsy Money response object { amount, divisor } to a plain float for PUT."""
    if isinstance(price_obj, (int, float)):
        return float(price_obj)
    amount = price_obj.get("amount", 0)
    divisor = price_obj.get("divisor", 100)
    return round(float(amount) / float(divisor), 2)


def transform_for_put(product):
    """Convert a GET-format product object into the shape Etsy's PUT expects."""
    offerings = []
    for o in product.get("offerings", []):
        offerings.append({
            "price": money_to_float(o.get("price", 0)),
            "quantity": o.get("quantity", 999),
            "is_enabled": o.get("is_enabled", True),
        })

    property_values = []
    for pv in product.get("property_values", []):
        property_values.append({
            "property_id": pv["property_id"],
            "property_name": pv.get("property_name", ""),
            "values": pv.get("values", []),
            "scale_id": pv.get("scale_id"),
        })

    return {
        "sku": product.get("sku", ""),
        "property_values": property_values,
        "offerings": offerings,
    }


def build_white_variant(sku, capacity_value, price, color_prop, capacity_prop):
    """Build a White variant object in PUT format."""
    return {
        "sku": sku,
        "property_values": [
            {
                "property_id": color_prop["property_id"],
                "property_name": color_prop.get("property_name", "Color"),
                "values": ["White"],
                "scale_id": color_prop.get("scale_id"),
            },
            {
                "property_id": capacity_prop["property_id"],
                "property_name": capacity_prop.get("property_name", "Capacity"),
                "values": [capacity_value],
                "scale_id": capacity_prop.get("scale_id"),
            },
        ],
        "offerings": [
            {
                "price": price,
                "quantity": 999,
                "is_enabled": True,
            }
        ],
    }


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
            "endpoint": "add-white-variants",
            "etsy_configured": bool(
                os.environ.get("ETSY_CLIENT_ID") and os.environ.get("ETSY_REFRESH_TOKEN")
            ),
        }).encode())

    def do_POST(self):
        # Always return HTTP 200 — errors are reported in the JSON body.
        # This ensures the Make.com pipeline never stops due to this step.
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))

            product_id = body.get("product_id", "").strip()
            printify_token = body.get("printify_token", "").strip()

            if not product_id:
                return self._json(200, {"status": "error", "error": "Missing product_id"})
            if not printify_token:
                return self._json(200, {"status": "error", "error": "Missing printify_token"})

            etsy_client_id = os.environ.get("ETSY_CLIENT_ID", "")
            etsy_refresh_token = os.environ.get("ETSY_REFRESH_TOKEN", "")
            if not etsy_client_id or not etsy_refresh_token:
                return self._json(200, {
                    "status": "skipped",
                    "message": "Etsy credentials not yet configured (ETSY_CLIENT_ID / ETSY_REFRESH_TOKEN). Add them to Vercel env vars to enable White variant automation.",
                })

            # ── 1. Get Etsy listing ID from Printify product ──────────────────
            printify_product, err = get_printify_product(printify_token, product_id)
            if err:
                return self._json(200, {"status": "error", "error": err})

            external = printify_product.get("external", {})
            listing_id = str(external.get("id", "")).strip()
            if not listing_id:
                return self._json(200, {
                    "status": "error",
                    "error": f"No Etsy listing ID on Printify product {product_id}. external field: {json.dumps(external)}",
                })

            # ── 2. Fresh Etsy access token ────────────────────────────────────
            etsy_token, err = get_etsy_access_token(etsy_client_id, etsy_refresh_token)
            if err:
                return self._json(200, {"status": "error", "error": err})

            # ── 3. GET current inventory ──────────────────────────────────────
            inventory, err = get_etsy_inventory(listing_id, etsy_token, etsy_client_id)
            if err:
                return self._json(200, {"status": "error", "error": err})

            existing_products = inventory.get("products", [])

            # ── 4. Idempotency: skip if White already there ───────────────────
            existing_skus = {p.get("sku", "") for p in existing_products}
            if WHITE_11OZ_SKU in existing_skus and WHITE_15OZ_SKU in existing_skus:
                return self._json(200, {
                    "status": "already_exists",
                    "message": "White variants already present — nothing to do.",
                    "listing_id": listing_id,
                })

            if not existing_products:
                return self._json(200, {
                    "status": "error",
                    "error": f"Etsy inventory has no products for listing {listing_id}. Raw inventory keys: {list(inventory.keys())}",
                })

            # ── 5. Extract Color + Capacity property structure ────────────────
            first = existing_products[0]
            color_prop = None
            capacity_prop = None
            for pv in first.get("property_values", []):
                name = pv.get("property_name", "")
                if name == "Color":
                    color_prop = pv
                elif name in ("Capacity", "Size"):
                    capacity_prop = pv

            if not color_prop or not capacity_prop:
                found = [pv.get("property_name") for pv in first.get("property_values", [])]
                return self._json(200, {"status": "error", "error": f"Expected Color + Capacity properties, found: {found}"})

            # ── 6. Find per-size prices from existing variants ────────────────
            price_11oz = None
            price_15oz = None
            for product in existing_products:
                for pv in product.get("property_values", []):
                    if pv.get("property_name") in ("Capacity", "Size") and product.get("offerings"):
                        pval = money_to_float(product["offerings"][0].get("price", 0))
                        vals = pv.get("values", [])
                        if vals and "11" in vals[0]:
                            price_11oz = pval
                        elif vals and "15" in vals[0]:
                            price_15oz = pval
                if price_11oz and price_15oz:
                    break

            # Fallback to first offering price if size lookup failed
            fallback = money_to_float(first.get("offerings", [{}])[0].get("price", 0))
            price_11oz = price_11oz or fallback
            price_15oz = price_15oz or fallback

            # ── 7. Build updated products array ───────────────────────────────
            updated = [transform_for_put(p) for p in existing_products]
            if WHITE_11OZ_SKU not in existing_skus:
                updated.append(build_white_variant(
                    WHITE_11OZ_SKU, "11 Fluid ounces", price_11oz, color_prop, capacity_prop
                ))
            if WHITE_15OZ_SKU not in existing_skus:
                updated.append(build_white_variant(
                    WHITE_15OZ_SKU, "15 Fluid ounces", price_15oz, color_prop, capacity_prop
                ))

            # ── 8. PUT updated inventory ──────────────────────────────────────
            result, err = put_etsy_inventory(listing_id, etsy_token, etsy_client_id, updated)
            if err:
                return self._json(200, {"status": "error", "error": err})

            return self._json(200, {
                "status": "success",
                "listing_id": listing_id,
                "variants_added": len(updated) - len(existing_products),
                "total_variants": len(updated),
            })

        except Exception as e:
            self._json(200, {"status": "error", "error": f"[unhandled] {str(e)}"})

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

    def _error(self, code, message):
        self._cors_headers(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode())

    def log_message(self, format, *args):
        pass  # suppress default logging
