#!/usr/bin/env python3
import csv
import gzip
import io
import json
import os
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from urllib.error import HTTPError
from datetime import datetime, timezone


API_BASE_URL = "https://lorcana-prices-api.p.rapidapi.com"
API_HOST = "lorcana-prices-api.p.rapidapi.com"
LORCANA_JSON_URL = "https://lorcanajson.org/files/current/en/allCards.json"
OUTPUT_PATH = "data/lorcana-prices-v1.json"
CARDMARKET_LORCANA_NONSINGLES_URL = "https://downloads.s3.cardmarket.com/productCatalog/productList/products_nonsingles_19.json"
CARDMARKET_ACCESSORIES_URL = "https://downloads.s3.cardmarket.com/productCatalog/productList/products_accessories.json"
CARDMARKET_ACCESSORIES_PRICE_GUIDE_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_accessories.json"
SEALED_PRODUCT_IMAGES_PATH = "data/sealed-product-images.json"
PER_PAGE = 100
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3

GLOBAL_LOW_FIELDS = [
    "lowest_near_mint",
    "lowest_near_mint_DE",
    "lowest_near_mint_FR",
    "lowest_near_mint_IT",
]

EU_LOW_FIELDS = [
    "lowest_near_mint_EU_only",
    "lowest_near_mint_DE_EU_only",
    "lowest_near_mint_FR_EU_only",
    "lowest_near_mint_IT_EU_only",
]


def request_json(path, query=None):
    api_key = os.environ.get("RAPIDAPI_KEY")
    if not api_key:
        raise RuntimeError("Missing RAPIDAPI_KEY environment variable")

    query_string = urllib.parse.urlencode(query or {})
    url = f"{API_BASE_URL}{path}"
    if query_string:
        url = f"{url}?{query_string}"

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-RapidAPI-Host": API_HOST,
            "X-RapidAPI-Key": api_key,
        },
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            message = f"HTTP {error.code} while requesting {path}: {error_body}"
            if 400 <= error.code < 500:
                raise RuntimeError(message) from error
            if attempt == MAX_RETRIES:
                raise RuntimeError(message) from error
            time.sleep(attempt * 2)
        except Exception:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(attempt * 2)


def normalize_key(value):
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_value.casefold().split())


def slugify(value):
    text = unicodedata.normalize("NFKD", str(value))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.replace("&", " and ")
    text = text.replace("'", "").replace("’", "")
    text = "".join(character if character.isalnum() else "-" for character in text)
    return "-".join(part for part in text.split("-") if part)


def normalized_card_number(value):
    text = str(value).strip()
    digits = []
    for character in text:
        if not character.isdigit():
            break
        digits.append(character)
    return str(int("".join(digits))) if digits else normalize_key(text)


def normalized_set_code(value):
    normalized = normalize_key(value)
    if normalized.startswith("pr") and normalized[2:].isdigit():
        return f"p{normalized[2:]}"
    return normalized


def price_key(set_code, card_number, name):
    return "|".join(
        [
            normalized_set_code(set_code),
            normalized_card_number(card_number),
            normalize_key(name),
        ]
    )


def market_price(card):
    if not card:
        return None

    prices = card.get("prices") or {}
    cardmarket = prices.get("cardmarket") or {}
    return cardmarket.get("lowest_near_mint_EU_only") or cardmarket.get("lowest_near_mint")


def numeric_price(value):
    if isinstance(value, (int, float)) and value >= 0:
        return value
    return None


def parse_price(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return numeric_price(value)

    text = str(value).strip()
    if not text:
        return None

    text = (
        text.replace("\u00a0", "")
        .replace("€", "")
        .replace("EUR", "")
        .replace(" ", "")
    )

    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")

    try:
        price = float(text)
    except ValueError:
        return None

    return price if price >= 0 else None


def effective_lowest(cardmarket, field_names):
    values = [
        numeric_price(cardmarket.get(field_name))
        for field_name in field_names
    ]
    values = [value for value in values if value is not None]
    return min(values) if values else None


def compact_variant(card, fallback_metadata=None):
    fallback_metadata = fallback_metadata or {}
    prices = card.get("prices") or {}
    cardmarket = prices.get("cardmarket") or {}
    return {
        "tcggo_id": card.get("id"),
        "cardmarket_id": card.get("cardmarket_id") or fallback_metadata.get("cardmarket_id"),
        "cardmarket_url": fallback_metadata.get("cardmarket_url"),
        "tcgplayer_id": fallback_metadata.get("tcgplayer_id"),
        "rarity": card.get("rarity"),
        "currency": cardmarket.get("currency"),
        "price_eur": market_price(card),
        "7d_average": cardmarket.get("7d_average"),
        "30d_average": cardmarket.get("30d_average"),
        "effective_lowest_near_mint_eu_only": effective_lowest(cardmarket, EU_LOW_FIELDS),
        "effective_lowest_near_mint": effective_lowest(
            cardmarket,
            GLOBAL_LOW_FIELDS + EU_LOW_FIELDS,
        ),
        "lowest_near_mint_eu_only": cardmarket.get("lowest_near_mint_EU_only"),
        "lowest_near_mint": cardmarket.get("lowest_near_mint"),
        "lowest_near_mint_de": cardmarket.get("lowest_near_mint_DE"),
        "lowest_near_mint_de_eu_only": cardmarket.get("lowest_near_mint_DE_EU_only"),
        "lowest_near_mint_fr": cardmarket.get("lowest_near_mint_FR"),
        "lowest_near_mint_fr_eu_only": cardmarket.get("lowest_near_mint_FR_EU_only"),
        "lowest_near_mint_it": cardmarket.get("lowest_near_mint_IT"),
        "lowest_near_mint_it_eu_only": cardmarket.get("lowest_near_mint_IT_EU_only"),
        "available_items": cardmarket.get("available_items"),
    }


def normalized_rarity(card):
    return normalize_key(card.get("rarity", "")).replace("_", " ")


def has_single_special_finish(group_cards):
    rarities = {normalized_rarity(card) for card in group_cards}
    return any(rarity in {"epic", "enchanted"} for rarity in rarities)


def fetch_all_episodes():
    episodes = []
    page = 1

    while True:
        payload = request_json("/episodes", {"page": page})
        episodes.extend(payload.get("data", []))
        paging = payload.get("paging", {})
        if page >= paging.get("total", page):
            return episodes
        page += 1
        time.sleep(0.25)


def fetch_episode_cards(episode_id):
    cards = []
    page = 1

    while True:
        print(f"Fetching episode {episode_id}, page {page}", flush=True)
        payload = request_json(
            f"/episodes/{episode_id}/cards",
            {
                "sort": "card_number_lowest",
                "per_page": PER_PAGE,
                "page": page,
            },
        )
        cards.extend(payload.get("data", []))
        paging = payload.get("paging", {})
        if page >= paging.get("total", page):
            return cards
        page += 1
        time.sleep(0.25)


def fetch_lorcanajson_metadata():
    try:
        with urllib.request.urlopen(LORCANA_JSON_URL, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        print(f"Warning: unable to fetch LorcanaJSON metadata: {error}", file=sys.stderr)
        return {}

    metadata_by_key = {}
    for card in payload.get("cards", []):
        external_links = card.get("externalLinks") or {}
        effective_set_code = card.get("promoGrouping") or card.get("setCode")
        metadata = {
            "cardmarket_id": external_links.get("cardmarketId"),
            "cardmarket_url": external_links.get("cardmarketUrl"),
            "tcgplayer_id": external_links.get("tcgPlayerId"),
        }
        names = {
            card.get("name"),
            card.get("fullName"),
        }
        for name in names:
            if not name:
                continue
            key = price_key(effective_set_code, card.get("number"), name)
            metadata_by_key[key] = metadata

    return metadata_by_key


def normalized_column_name(value):
    return normalize_key(value).replace(".", "").replace("+", " plus")


def first_price(row, column_names):
    for column_name in column_names:
        price = parse_price(row.get(column_name))
        if price is not None:
            return price
    return None


def decode_price_guide_bytes(payload, source_name):
    if source_name.endswith(".gz") or payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)

    return payload.decode("utf-8-sig")


def read_cardmarket_price_guide_source(source):
    if source.startswith(("http://", "https://")):
        request = urllib.request.Request(
            source,
            headers={
                "Accept": "text/csv,application/gzip,application/octet-stream,*/*",
                "User-Agent": "LorcanaVaultPriceGenerator/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return decode_price_guide_bytes(response.read(), source)

    with open(source, "rb") as file:
        return decode_price_guide_bytes(file.read(), source)


def env_url_or_default(name, default):
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    return default


def fetch_cardmarket_price_guide():
    source = os.environ.get("CARDMARKET_PRICE_GUIDE_URL") or os.environ.get("CARDMARKET_PRICE_GUIDE_PATH")
    if not source:
        print("Cardmarket price guide fallback disabled: missing CARDMARKET_PRICE_GUIDE_URL", flush=True)
        return {}

    try:
        csv_text = read_cardmarket_price_guide_source(source)
    except Exception as error:
        print(f"Warning: unable to fetch Cardmarket price guide: {error}", file=sys.stderr)
        return {}

    stripped_text = csv_text.lstrip()
    if stripped_text.startswith("{") or stripped_text.startswith("["):
        return parse_cardmarket_price_guide_json(stripped_text)

    sample = csv_text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(csv_text), dialect=dialect)
    price_guide_by_product_id = {}

    for raw_row in reader:
        row = {
            normalized_column_name(key): value
            for key, value in raw_row.items()
            if key is not None
        }
        product_id = (
            row.get("idproduct")
            or row.get("id product")
            or row.get("product id")
            or row.get("id")
        )
        if not product_id:
            continue

        product_id = str(product_id).strip()
        low_price = first_price(row, ["low price", "low", "from"])
        low_price_ex = first_price(row, ["low price ex plus", "low ex plus", "lowex", "lowex plus"])
        trend_price = first_price(row, ["trend price", "trend"])
        average_7d = first_price(row, ["avg7", "avg 7", "7d average", "7 days average"])
        average_30d = first_price(row, ["avg30", "avg 30", "30d average", "30 days average"])
        foil_low_price = first_price(row, ["foil low", "low foil", "lowfoil"])
        foil_trend_price = first_price(row, ["foil trend", "trend foil", "trendfoil"])

        price_guide_by_product_id[product_id] = {
            "price_eur": low_price_ex or low_price or trend_price,
            "lowest_near_mint": low_price_ex or low_price,
            "trend_price": trend_price,
            "7d_average": average_7d,
            "30d_average": average_30d,
            "foil_price_eur": foil_low_price or foil_trend_price,
            "foil_lowest_near_mint": foil_low_price,
            "foil_trend_price": foil_trend_price,
        }

    print(f"Loaded {len(price_guide_by_product_id)} Cardmarket price guide entries", flush=True)
    return price_guide_by_product_id


def parse_cardmarket_price_guide_json(json_text):
    payload = json.loads(json_text)
    if isinstance(payload, dict):
        rows = payload.get("priceGuides") or payload.get("price_guides") or payload.get("data") or []
    else:
        rows = payload

    price_guide_by_product_id = {}
    for row in rows:
        if not isinstance(row, dict):
            continue

        product_id = row.get("idProduct") or row.get("idproduct") or row.get("id_product") or row.get("id")
        if product_id is None:
            continue

        low_price = parse_price(row.get("low"))
        trend_price = parse_price(row.get("trend"))
        average_7d = parse_price(row.get("avg7"))
        average_30d = parse_price(row.get("avg30"))
        foil_low_price = parse_price(row.get("low-foil") or row.get("lowFoil"))
        foil_trend_price = parse_price(row.get("trend-foil") or row.get("trendFoil"))

        price_guide_by_product_id[str(product_id).strip()] = {
            "price_eur": low_price or trend_price,
            "lowest_near_mint": low_price,
            "trend_price": trend_price,
            "7d_average": average_7d,
            "30d_average": average_30d,
            "foil_price_eur": foil_low_price or foil_trend_price,
            "foil_lowest_near_mint": foil_low_price,
            "foil_trend_price": foil_trend_price,
            "foil_7d_average": parse_price(row.get("avg7-foil") or row.get("avg7Foil")),
            "foil_30d_average": parse_price(row.get("avg30-foil") or row.get("avg30Foil")),
        }

    print(f"Loaded {len(price_guide_by_product_id)} Cardmarket price guide entries", flush=True)
    return price_guide_by_product_id


def fetch_json_url(url, label):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,*/*",
            "User-Agent": "LorcanaVaultPriceGenerator/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def read_json_source(source, label):
    if not source:
        return None
    try:
        if source.startswith(("http://", "https://")):
            return fetch_json_url(source, label)
        with open(source, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as error:
        print(f"Warning: unable to read {label}: {error}", file=sys.stderr)
        return None


def fetch_cardmarket_product_catalog(source, label):
    if not source:
        print(f"{label} catalog disabled: missing URL", flush=True)
        return []

    try:
        payload = fetch_json_url(source, label)
    except Exception as error:
        print(f"Warning: unable to fetch {label} catalog: {error}", file=sys.stderr)
        return []

    products = payload.get("products") if isinstance(payload, dict) else payload
    products = products if isinstance(products, list) else []
    print(f"Loaded {len(products)} {label} product entries", flush=True)
    return [product for product in products if isinstance(product, dict)]


def load_sealed_product_images():
    source = (
        os.environ.get("SEALED_PRODUCT_IMAGES_URL")
        or os.environ.get("SEALED_PRODUCT_IMAGES_PATH")
        or (SEALED_PRODUCT_IMAGES_PATH if os.path.exists(SEALED_PRODUCT_IMAGES_PATH) else None)
    )
    payload = read_json_source(source, "sealed product images")
    if not payload:
        return {}

    if isinstance(payload, dict) and isinstance(payload.get("images"), dict):
        payload = payload["images"]

    if not isinstance(payload, dict):
        print("Warning: sealed product images source must be a JSON object", file=sys.stderr)
        return {}

    images = {}
    for raw_key, raw_value in payload.items():
        if isinstance(raw_value, str):
            image_url = raw_value
        elif isinstance(raw_value, dict):
            image_url = raw_value.get("image_url") or raw_value.get("url")
        else:
            image_url = None

        if image_url:
            images[str(raw_key).strip()] = image_url

    print(f"Loaded {len(images)} sealed product image mappings", flush=True)
    return images


def fetch_accessories_price_guide():
    source = env_url_or_default("CARDMARKET_ACCESSORIES_PRICE_GUIDE_URL", CARDMARKET_ACCESSORIES_PRICE_GUIDE_URL)
    try:
        csv_text = read_cardmarket_price_guide_source(source)
    except Exception as error:
        print(f"Warning: unable to fetch Cardmarket accessories price guide: {error}", file=sys.stderr)
        return {}

    stripped_text = csv_text.lstrip()
    if stripped_text.startswith("{") or stripped_text.startswith("["):
        return parse_cardmarket_price_guide_json(stripped_text)

    return {}


def cardmarket_price_guide_variant(product_id, price_guide, fallback_metadata):
    price = price_guide.get("price_eur")
    if price is None:
        return None

    return {
        "tcggo_id": None,
        "cardmarket_id": product_id,
        "cardmarket_url": fallback_metadata.get("cardmarket_url"),
        "tcgplayer_id": fallback_metadata.get("tcgplayer_id"),
        "rarity": None,
        "currency": "EUR",
        "price_eur": price,
        "7d_average": price_guide.get("7d_average"),
        "30d_average": price_guide.get("30d_average"),
        "effective_lowest_near_mint_eu_only": price,
        "effective_lowest_near_mint": price,
        "lowest_near_mint_eu_only": price,
        "lowest_near_mint": price_guide.get("lowest_near_mint") or price,
        "lowest_near_mint_de": None,
        "lowest_near_mint_de_eu_only": None,
        "lowest_near_mint_fr": None,
        "lowest_near_mint_fr_eu_only": None,
        "lowest_near_mint_it": None,
        "lowest_near_mint_it_eu_only": None,
        "available_items": None,
        "trend_price": price_guide.get("trend_price"),
        "source": "cardmarket_price_guide",
    }


def apply_cardmarket_price_guide_fallback(price_entries, price_guide_by_product_id):
    if not price_guide_by_product_id:
        return 0

    fallback_count = 0

    for entry in price_entries:
        if entry.get("regular_price_eur") is not None or entry.get("special_price_eur") is not None:
            continue

        product_id = entry.get("external_cardmarket_id")
        if product_id is None:
            for variant in entry.get("variants") or []:
                product_id = variant.get("cardmarket_id")
                if product_id is not None:
                    break
        if product_id is None:
            continue

        price_guide = price_guide_by_product_id.get(str(product_id))
        if not price_guide:
            continue

        fallback_metadata = {
            "cardmarket_id": product_id,
            "cardmarket_url": entry.get("external_cardmarket_url"),
        }
        regular_variant = cardmarket_price_guide_variant(product_id, price_guide, fallback_metadata)
        if not regular_variant:
            continue

        entry["regular_price_eur"] = regular_variant["price_eur"]
        entry["price_source"] = "lorcana_prices_api_then_cardmarket_price_guide"
        entry["priced_variant_count"] = max(entry.get("priced_variant_count") or 0, 1)
        entry["regular_variant"] = regular_variant

        if entry.get("finish_type") == "special":
            entry["special_price_eur"] = regular_variant["price_eur"]

        foil_price = price_guide.get("foil_price_eur")
        if foil_price is not None and entry.get("foil_price_eur") is None:
            entry["foil_price_eur"] = foil_price
            entry["foil_variant"] = {
                **regular_variant,
                "price_eur": foil_price,
                "7d_average": price_guide.get("foil_7d_average"),
                "30d_average": price_guide.get("foil_30d_average"),
                "lowest_near_mint_eu_only": price_guide.get("foil_lowest_near_mint") or foil_price,
                "lowest_near_mint": price_guide.get("foil_lowest_near_mint") or foil_price,
                "trend_price": price_guide.get("foil_trend_price"),
            }

        fallback_count += 1

    return fallback_count


def sealed_product_category_group(category_name):
    normalized = normalize_key(category_name)
    if "booster boxes" in normalized:
        return "booster_box"
    if "booster" in normalized:
        return "booster"
    if "starter" in normalized:
        return "starter_deck"
    if "gift" in normalized:
        return "gift_set"
    if "box set" in normalized:
        return "box_set"
    if normalized.endswith("sets") or "lorcana sets" in normalized:
        return "set"
    if "lots" in normalized:
        return "lot"
    if "playmat" in normalized:
        return "playmat"
    if "sleeve" in normalized:
        return "sleeves"
    if "deckbox" in normalized or "deck box" in normalized:
        return "deck_box"
    if "album" in normalized:
        return "album"
    if "memorabilia" in normalized:
        return "memorabilia"
    if "storage" in normalized:
        return "storage"
    return "other"


def sealed_product_category_path(category_name):
    normalized = normalize_key(category_name)
    if "booster boxes" in normalized:
        return "Booster-Boxes"
    if "booster" in normalized:
        return "Boosters"
    if "starter" in normalized:
        return "Starter-Decks"
    if "gift" in normalized:
        return "Gift-Sets"
    if "box set" in normalized:
        return "Box-Sets"
    if normalized.endswith("sets") or "lorcana sets" in normalized:
        return "Sets"
    if "lots" in normalized:
        return "Lots"

    accessory_paths = {
        "playmats": "Playmats",
        "sleeves": "Sleeves",
        "deckboxes": "Deck-Boxes",
        "albums": "Albums",
        "memorabilia": "Memorabilia",
        "storage": "Storage",
        "printedmedia": "Printed-Media",
        "lifecounter": "Life-Counters",
    }
    return accessory_paths.get(normalized.replace(" ", ""), "Accessories")


def sealed_product_cardmarket_url(product):
    product_id = product.get("idProduct")
    name_slug = slugify(product.get("name") or "")
    if product_id is None or not name_slug:
        return None

    category_path = sealed_product_category_path(product.get("categoryName") or "")
    quoted_slug = urllib.parse.quote(name_slug)
    return f"https://www.cardmarket.com/en/Lorcana/Products/{category_path}/{quoted_slug}?idProduct={product_id}"


def should_include_lorcana_accessory(product):
    text = normalize_key(f"{product.get('name', '')} {product.get('categoryName', '')}")
    return "lorcana" in text or "disney lorcana" in text


def build_sealed_product_entry(product, price_guide, source, image_by_product_id):
    product_id = product.get("idProduct")
    if product_id is None:
        return None

    price = price_guide.get(str(product_id).strip()) or {}
    category_name = product.get("categoryName") or ""
    low_price = price.get("price_eur")

    return {
        "id": f"cardmarket-{product_id}",
        "cardmarket_id": product_id,
        "cardmarket_url": sealed_product_cardmarket_url(product),
        "name": product.get("name"),
        "category_id": product.get("idCategory"),
        "category_name": category_name,
        "category_group": sealed_product_category_group(category_name),
        "expansion_id": product.get("idExpansion"),
        "metacard_id": product.get("idMetacard"),
        "date_added": product.get("dateAdded"),
        "image_url": image_by_product_id.get(str(product_id).strip()),
        "currency": "EUR",
        "price_eur": low_price,
        "lowest_price_eur": price.get("lowest_near_mint") or low_price,
        "trend_price_eur": price.get("trend_price"),
        "7d_average_eur": price.get("7d_average"),
        "30d_average_eur": price.get("30d_average"),
        "source": source,
    }


def build_sealed_products(cardmarket_price_guide):
    nonsingles_source = env_url_or_default("CARDMARKET_LORCANA_NONSINGLES_URL", CARDMARKET_LORCANA_NONSINGLES_URL)
    accessories_source = env_url_or_default("CARDMARKET_ACCESSORIES_URL", CARDMARKET_ACCESSORIES_URL)
    nonsingles = fetch_cardmarket_product_catalog(nonsingles_source, "Cardmarket Lorcana non-singles")
    accessories = [
        product
        for product in fetch_cardmarket_product_catalog(accessories_source, "Cardmarket accessories")
        if should_include_lorcana_accessory(product)
    ]
    accessories_price_guide = fetch_accessories_price_guide()
    image_by_product_id = load_sealed_product_images()

    products = []
    for product in nonsingles:
        entry = build_sealed_product_entry(product, cardmarket_price_guide, "cardmarket_lorcana_nonsingles", image_by_product_id)
        if entry:
            products.append(entry)

    for product in accessories:
        entry = build_sealed_product_entry(product, accessories_price_guide, "cardmarket_accessories", image_by_product_id)
        if entry:
            products.append(entry)

    products.sort(key=lambda item: (
        item.get("category_group") or "",
        normalize_key(item.get("name") or ""),
        str(item.get("cardmarket_id") or ""),
    ))
    print(f"Built {len(products)} sealed/accessory product entries", flush=True)
    return products


def build_price_entry(episode, group_cards, metadata_by_key):
    priced_variants = [card for card in group_cards if market_price(card) is not None]
    sorted_variants = sorted(priced_variants, key=market_price)
    single_special_finish = has_single_special_finish(group_cards)

    regular_variant = sorted_variants[0] if sorted_variants else None
    foil_variant = None if single_special_finish or len(sorted_variants) < 2 else sorted_variants[-1]
    reference_card = group_cards[0]

    regular_price = market_price(regular_variant) if regular_variant else None
    foil_price = market_price(foil_variant) if foil_variant else None
    special_price = regular_price if single_special_finish else None
    entry_key = price_key(
        episode.get("code", ""),
        reference_card.get("card_number"),
        reference_card.get("name", ""),
    )
    fallback_metadata = metadata_by_key.get(entry_key, {})

    return {
        "set_code": episode.get("code"),
        "set_name": episode.get("name"),
        "episode_id": episode.get("id"),
        "card_number": str(reference_card.get("card_number")),
        "name": reference_card.get("name"),
        "rarity": reference_card.get("rarity"),
        "key": entry_key,
        "finish_type": "special" if single_special_finish else "standard",
        "regular_price_eur": regular_price,
        "foil_price_eur": foil_price,
        "special_price_eur": special_price,
        "price_source": "eu_only_then_lowest",
        "variant_count": len(group_cards),
        "priced_variant_count": len(priced_variants),
        "external_cardmarket_id": fallback_metadata.get("cardmarket_id"),
        "external_cardmarket_url": fallback_metadata.get("cardmarket_url"),
        "regular_variant": compact_variant(regular_variant, fallback_metadata) if regular_variant else None,
        "foil_variant": compact_variant(foil_variant, fallback_metadata) if foil_variant else None,
        "variants": [compact_variant(card, fallback_metadata) for card in group_cards],
    }


def main():
    episodes = fetch_all_episodes()
    metadata_by_key = fetch_lorcanajson_metadata()
    cardmarket_price_guide = fetch_cardmarket_price_guide()
    only_episode_id = os.environ.get("ONLY_EPISODE_ID")
    if only_episode_id:
        episodes = [episode for episode in episodes if str(episode.get("id")) == only_episode_id]

    output = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "lorcana-prices-api",
        "price_rule": "Use the lowest available EU-only Near Mint value across generic and language-specific Cardmarket lows, fallback to the lowest available global Near Mint value across generic and language-specific lows. If Lorcana Prices API has no price for a card, optionally fallback to the public Cardmarket Price Guide matched by LorcanaJSON cardmarketId. Store raw API aggregates such as 7d_average, 30d_average, global/EU lows and language lows when provided. Epic and Enchanted are treated as single special finish. For duplicate standard same set/name/number variants, lower price is regular and higher price is foil. Sealed/accessory products are built from Cardmarket public product catalog files and joined to the public price guide by idProduct. Product images are intentionally nullable.",
        "episodes": [],
        "prices": [],
        "sealed_products": [],
    }

    for episode in episodes:
        print(
            f"Fetching {episode.get('name')} ({episode.get('code')}, id={episode.get('id')})",
            flush=True,
        )
        cards = fetch_episode_cards(episode["id"])
        output["episodes"].append(
            {
                "id": episode.get("id"),
                "name": episode.get("name"),
                "code": episode.get("code"),
                "slug": episode.get("slug"),
                "released_at": episode.get("released_at"),
                "cards_total": episode.get("cards_total"),
                "cards_returned": len(cards),
            }
        )

        grouped_cards = {}
        for card in cards:
            group_key = price_key(episode.get("code", ""), card.get("card_number"), card.get("name", ""))
            grouped_cards.setdefault(group_key, []).append(card)

        for group_cards in grouped_cards.values():
            output["prices"].append(build_price_entry(episode, group_cards, metadata_by_key))

    fallback_count = apply_cardmarket_price_guide_fallback(output["prices"], cardmarket_price_guide)
    output["cardmarket_price_guide_fallback_count"] = fallback_count
    output["sealed_products"] = build_sealed_products(cardmarket_price_guide)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, separators=(",", ":"))
        file.write("\n")

    print(f"Wrote {len(output['prices'])} price entries to {OUTPUT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
