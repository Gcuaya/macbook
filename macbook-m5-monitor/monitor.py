import json
import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

CONFIG_PATH = Path("stores.json")
STATE_PATH = Path("state.json")

PRICE_RE = re.compile(
    r"(?:MXN|MX\$|\$)\s*([0-9]{1,3}(?:[,\s][0-9]{3})*(?:\.[0-9]{2})?)",
    re.IGNORECASE,
)

@dataclass
class Offer:
    store: str
    title: str
    url: str
    price: float
    ram: str = "No identificada"
    storage: str = "No identificado"
    previous_price: float | None = None

    @property
    def discount_pct(self) -> float | None:
        if self.previous_price and self.previous_price > self.price:
            return round((1 - self.price / self.previous_price) * 100, 1)
        return None


def money(value: float | None) -> str:
    return "No disponible" if value is None else f"${value:,.2f} MXN"


def normalize_price(raw: str | float | int | None) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    cleaned = re.sub(r"[^\d.,]", "", str(raw)).replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def walk_json(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk_json(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk_json(item)


def extract_jsonld_offer(page) -> tuple[str | None, float | None]:
    title = None
    prices: list[float] = []
    scripts = page.locator('script[type="application/ld+json"]')
    for i in range(scripts.count()):
        try:
            data = json.loads(scripts.nth(i).inner_text(timeout=3000))
        except Exception:
            continue
        for node in walk_json(data):
            node_type = str(node.get("@type", "")).lower()
            if not title and node_type == "product":
                title = node.get("name")
            if node_type in {"offer", "aggregateoffer"}:
                for key in ("price", "lowPrice", "highPrice"):
                    value = normalize_price(node.get(key))
                    if value and 10000 <= value <= 200000:
                        prices.append(value)
    return title, min(prices) if prices else None


def extract_visible_prices(text: str) -> list[float]:
    values = []
    for match in PRICE_RE.findall(text):
        value = normalize_price(match)
        if value and 10000 <= value <= 200000:
            values.append(value)
    return sorted(set(values))


def find_spec(text: str, patterns: list[str], fallback: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return fallback


def valid_product(title_and_text: str, required_keywords: list[str], excluded_keywords: list[str]) -> bool:
    normalized = title_and_text.lower()
    return (
        all(keyword.lower() in normalized for keyword in required_keywords)
        and not any(keyword.lower() in normalized for keyword in excluded_keywords)
    )


def inspect_product(page, item: dict, max_price: float) -> Offer | None:
    page.goto(item["url"], wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    try:
        body_text = page.locator("body").inner_text(timeout=15000)
    except PlaywrightTimeoutError:
        return None

    jsonld_title, jsonld_price = extract_jsonld_offer(page)
    page_title = page.title()
    title = jsonld_title or page_title
    combined = f"{title}\n{body_text}"

    if not valid_product(
        combined,
        item.get("required_keywords", ["macbook", "pro", "m5"]),
        item.get(
            "excluded_keywords",
            ["reacondicionado", "refurbished", "usado", "open box", "caja abierta"],
        ),
    ):
        return None

    prices = extract_visible_prices(body_text)
    price = jsonld_price or (prices[0] if prices else None)
    if price is None or price > max_price:
        return None

    previous_price = None
    higher_prices = [p for p in prices if p > price]
    if higher_prices:
        previous_price = min(higher_prices)

    ram = find_spec(
        combined,
        [r"\b(?:16|24|32|36|48|64|96|128)\s?GB\s+(?:RAM|memoria(?:\s+unificada)?)",
         r"\b(?:16|24|32|36|48|64|96|128)\s?GB\b"],
        "No identificada",
    )
    storage = find_spec(
        combined,
        [r"\b(?:512\s?GB|1\s?TB|2\s?TB|4\s?TB|8\s?TB)\s*(?:SSD)?\b"],
        "No identificado",
    )

    return Offer(
        store=item["store"],
        title=title.strip(),
        url=item["url"],
        price=price,
        ram=ram,
        storage=storage,
        previous_price=previous_price,
    )


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict):
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def offer_key(offer: Offer) -> str:
    host = urlparse(offer.url).netloc
    return f"{host}|{offer.url}|{offer.price:.2f}"


def send_email(offers: list[Offer], test_mode: bool = False):
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_APP_PASSWORD"]
    email_to = os.environ["EMAIL_TO"]

    subject = (
        "Prueba del monitor MacBook M5"
        if test_mode
        else f"Oferta encontrada: MacBook Pro M5 desde {money(min(o.price for o in offers))}"
    )

    lines = [
        "El monitor encontró las siguientes opciones:" if not test_mode
        else "La configuración del correo funciona correctamente.",
        "",
    ]

    for offer in offers:
        lines.extend([
            f"Tienda: {offer.store}",
            f"Modelo: {offer.title}",
            f"RAM: {offer.ram}",
            f"SSD: {offer.storage}",
            f"Precio actual: {money(offer.price)}",
            f"Precio anterior: {money(offer.previous_price)}",
            f"Descuento estimado: {offer.discount_pct if offer.discount_pct is not None else 'No disponible'}"
            + ("%" if offer.discount_pct is not None else ""),
            f"Evaluación: cumple el límite configurado y no contiene términos de usado, reacondicionado o caja abierta.",
            f"Enlace: {offer.url}",
            "",
        ])

    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = email_to
    msg["Subject"] = subject
    msg.set_content("\n".join(lines))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as smtp:
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(msg)


def main():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    max_price = float(config.get("max_price_mxn", 38000))
    test_mode = os.getenv("FORCE_TEST_EMAIL", "false").lower() == "true"

    if test_mode:
        test_offer = Offer(
            store="Prueba",
            title="MacBook Pro M5 de prueba",
            url="https://example.com",
            price=max_price,
            ram="16 GB",
            storage="512 GB SSD",
        )
        send_email([test_offer], test_mode=True)
        print("Correo de prueba enviado.")
        return

    state = load_state()
    found: list[Offer] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="es-MX",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for item in config["products"]:
            try:
                offer = inspect_product(page, item, max_price)
                if offer:
                    key = offer_key(offer)
                    if key not in state:
                        found.append(offer)
                        state[key] = {
                            "store": offer.store,
                            "title": offer.title,
                            "price": offer.price,
                            "url": offer.url,
                        }
                print(f"Revisada: {item['store']} - {item['url']}")
            except Exception as exc:
                print(f"ERROR en {item['store']}: {exc}")

        browser.close()

    if found:
        send_email(found)
        save_state(state)
        print(f"Correo enviado con {len(found)} oferta(s).")
    else:
        print("No se encontraron ofertas nuevas que cumplan los criterios.")


if __name__ == "__main__":
    main()
