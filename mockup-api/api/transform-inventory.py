from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.parse
import urllib.error

WHITE_11OZ_SKU = "24873414371188792626"
WHITE_15OZ_SKU = "80484685462245870793"
ETSY_SHOP_ID = "48393866"


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


def get_etsy_inventory(listing_id, access_token, client_id, shared_secret):
    url = f"https://openapi.etsy.com/v3/application/listings/{listing_id}/inventory"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-api-key": f"{client_id}:{shared_secret}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"[get_inventory] {_http_error_detail(e)}"
    except Exception as e:
        return None, f"[get_inventory] {str(e)}"


def put_etsy_inventory(listing_id, body_dict, access_token, client_id, shared_secret):
    url = f"https://openapi.etsy.com/v3/application/listings/{listing_id}/inventory"
    body = json.dumps(body_dict).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method="PUT",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-api-key": f"{client_id}:{shared_secret}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"[put_inventory] {_http_error_detail(e)}"
    except Exception as e:
        return None, f"[put_inventory] {str(e)}"


def money_to_float(price_obj):
    if isinstance(price_obj, (int, float)):
        return float(price_obj)
    amount = price_obj.get("amount", 0)
    divisor = price_obj.get("divisor", 100)
    return round(float(amount) / float(divisor), 2)


def transform_offering(o):
    """Convert GET offering to PUT format."""
    return {
        "price": money_to_float(o.get("price", 0)),
        "quantity": o.get("quantity", 999),
        "is_enabled": o.get("is_enabled", True),
        "readiness_state": 2,
    }


def transform_product_for_put(product):
    offerings = [transform_offering(o) for o in product.get("offerings", [])]
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
        "offerings": [{"price": price, "quantity": 999, "is_enabled": True, "readiness_state": 2}],
    }


def transform_inventory(inventory):
    existing_products = inventory.get("products", [])
    if not existing_products:
        keys = list(inventory.keys())
        return None, f"No products in inventory. Keys found: {keys}"

    existing_skus = {p.get("sku", "") for p in existing_products}
    if WHITE_11OZ_SKU in existing_skus and WHITE_15OZ_SKU in existing_skus:
        return [transform_product_for_put(p) for p in existing_products], None

    first = existing_products[0]
    color_prop = None
    capacity_prop = None
    for pv in first.get("property_values", []):
        name = pv.get("property_name", "")
        if name in ("Color", "Mug color"):
            color_prop = pv
        elif name in ("Capacity", "Size", "Mug sizes"):
            capacity_prop = pv

    if not color_prop or not capacity_prop:
        found = [pv.get("property_name") for pv in first.get("property_values", [])]
        return None, f"Expected Color/Mug color + Capacity/Size/Mug sizes, found: {found}"

    price_11oz = None
    price_15oz = None
    for product in existing_products:
        for pv in product.get("property_values", []):
            if pv.get("property_name") in ("Capacity", "Size", "Mug sizes") and product.get("offerings"):
                pval = money_to_float(product["offerings"][0].get("price", 0))
                vals = pv.get("values", [])
                if vals and "11" in vals[0]:
                    price_11oz = pval
                elif vals and "15" in vals[0]:
                    price_15oz = pval
        if price_11oz and price_15oz:
            break

    fallback = money_to_float((first.get("offerings") or [{}])[0].get("price", 0))
    price_11oz = price_11oz or fallback
    price_15oz = price_15oz or fallback

    updated = [transform_product_for_put(p) for p in existing_products]
    if WHITE_11OZ_SKU not in existing_skus:
        updated.append(build_white_variant(
            WHITE_11OZ_SKU, "11 Fluid ounces", price_11oz, color_prop, capacity_prop
        ))
    if WHITE_15OZ_SKU not in existing_skus:
        updated.append(build_white_variant(
            WHITE_15OZ_SKU, "15 Fluid ounces", price_15oz, color_prop, capacity_prop
        ))

    return updated, None


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
            "endpoint": "transform-inventory",
            "version": "both-rs-v5",
        }).encode())

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))

            listing_id = str(body.get("listing_id", "")).strip()
            if not listing_id:
                return self._json({"status": "error", "error": "Missing listing_id"})

            client_id = os.environ.get("ETSY_CLIENT_ID", "")
            refresh_token = os.environ.get("ETSY_REFRESH_TOKEN", "")
            shared_secret = os.environ.get("ETSY_SHARED_SECRET", "")

            if not client_id or not refresh_token or not shared_secret:
                return self._json({"status": "error", "error": "Etsy credentials not configured"})

            access_token, err = get_etsy_access_token(client_id, refresh_token)
            if err:
                return self._json({"status": "error", "error": err})

            inventory, err = get_etsy_inventory(listing_id, access_token, client_id, shared_secret)
            if err:
                return self._json({"status": "error", "error": err})

            # Collect top-level keys from GET for debug
            inventory_top_keys = {k: v for k, v in inventory.items() if k != "products"}

            products, err = transform_inventory(inventory)
            if err:
                return self._json({"status": "error", "error": err})

            # Build PUT body: pass through all top-level fields from GET except products
            put_body = {"products": products}
            for key in ["price_on_property", "quantity_on_property", "sku_on_property", "readiness_state_on_property"]:
                if key in inventory:
                    put_body[key] = inventory[key]

            result, err = put_etsy_inventory(listing_id, put_body, access_token, client_id, shared_secret)
            if err:
                return self._json({
                    "status": "error",
                    "error": err,
                    "products_count": len(products),
                    "put_body_keys": list(put_body.keys()),
                    "inventory_top_keys": inventory_top_keys,
                    "sample_offering_sent": products[0]["offerings"][0] if products and products[0].get("offerings") else None,
                })

            return self._json({
                "status": "ok",
                "products_updated": len(products),
                "listing_id": listing_id,
            })

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
