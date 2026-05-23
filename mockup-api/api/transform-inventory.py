from http.server import BaseHTTPRequestHandler
import json

WHITE_11OZ_SKU = "24873414371188792626"
WHITE_15OZ_SKU = "80484685462245870793"

def money_to_float(price_obj):
    if isinstance(price_obj, (int, float)):
        return float(price_obj)
    amount = price_obj.get("amount", 0)
    divisor = price_obj.get("divisor", 100)
    return round(float(amount) / float(divisor), 2)

def transform_product_for_put(product):
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
    return {"sku": product.get("sku", ""), "property_values": property_values, "offerings": offerings}

def build_white_variant(sku, capacity_value, price, color_prop, capacity_prop):
    return {
        "sku": sku,
        "property_values": [
            {"property_id": color_prop["property_id"], "property_name": color_prop.get("property_name", "Color"), "values": ["White"], "scale_id": color_prop.get("scale_id")},
            {"property_id": capacity_prop["property_id"], "property_name": capacity_prop.get("property_name", "Capacity"), "values": [capacity_value], "scale_id": capacity_prop.get("scale_id")},
        ],
        "offerings": [{"price": price, "quantity": 999, "is_enabled": True}],
    }

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self): self._cors_headers(200); self.end_headers()
    def do_GET(self):
        self._cors_headers(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "endpoint": "transform-inventory"}).encode())
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            inventory = json.loads(self.rfile.read(length))
            existing_products = inventory.get("products", [])
            if not existing_products:
                return self._json({"error": f"No products in inventory. Keys found: {list(inventory.keys())}"})
            existing_skus = {p.get("sku", "") for p in existing_products}
            if WHITE_11OZ_SKU in existing_skus and WHITE_15OZ_SKU in existing_skus:
                return self._json({"products": [transform_product_for_put(p) for p in existing_products]})
            first = existing_products[0]
            color_prop = capacity_prop = None
            for pv in first.get("property_values", []):
                name = pv.get("property_name", "")
                if name == "Color": color_prop = pv
                elif name in ("Capacity", "Size"): capacity_prop = pv
            if not color_prop or not capacity_prop:
                return self._json({"error": f"Expected Color + Capacity properties, found: {[pv.get('property_name') for pv in first.get('property_values', [])]}"})
            price_11oz = price_15oz = None
            for product in existing_products:
                for pv in product.get("property_values", []):
                    if pv.get("property_name") in ("Capacity", "Size") and product.get("offerings"):
                        pval = money_to_float(product["offerings"][0].get("price", 0))
                        vals = pv.get("values", [])
                        if vals and "11" in vals[0]: price_11oz = pval
                        elif vals and "15" in vals[0]: price_15oz = pval
                if price_11oz and price_15oz: break
            fallback = money_to_float(first.get("offerings", [{}])[0].get("price", 0))
            price_11oz = price_11oz or fallback
            price_15oz = price_15oz or fallback
            updated = [transform_product_for_put(p) for p in existing_products]
            if WHITE_11OZ_SKU not in existing_skus:
                updated.append(build_white_variant(WHITE_11OZ_SKU, "11 Fluid ounces", price_11oz, color_prop, capacity_prop))
            if WHITE_15OZ_SKU not in existing_skus:
                updated.append(build_white_variant(WHITE_15OZ_SKU, "15 Fluid ounces", price_15oz, color_prop, capacity_prop))
            return self._json({"products": updated})
        except Exception as e:
            self._json({"error": f"[unhandled] {str(e)}"})
    def _json(self, payload):
        self._cors_headers(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(payload).encode())
    def _cors_headers(self, code):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
    def log_message(self, format, *args): pass
