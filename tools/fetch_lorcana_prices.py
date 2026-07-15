#!/usr/bin/env python3
import json
import os
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone


API_BASE_URL = "https://lorcana-prices-api.p.rapidapi.com"
API_HOST = "lorcana-prices-api.p.rapidapi.com"
OUTPUT_PATH = "data/lorcana-prices-v1.json"
PER_PAGE = 100
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3


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
            "Content-Type": "application/json",
            "x-rapidapi-host": API_HOST,
            "x-rapidapi-key": api_key,
        },
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(attempt * 2)


def normalize_key(value):
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_value.casefold().split())


def market_price(card):
    prices = card.get("prices") or {}
    cardmarket = prices.get("cardmarket") or {}
    return cardmarket.get("lowest_near_mint_EU_only") or cardmarket.get("lowest_near_mint")


def compact_variant(card):
    prices = card.get("prices") or {}
    cardmarket = prices.get("cardmarket") or {}
    return {
        "tcggo_id": card.get("id"),
        "cardmarket_id": card.get("cardmarket_id"),
        "rarity": card.get("rarity"),
        "currency": cardmarket.get("currency"),
        "price_eur": market_price(card),
        "7d_average": cardmarket.get("7d_average"),
        "30d_average": cardmarket.get("30d_average"),
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


def build_price_entry(episode, group_cards):
    priced_variants = [card for card in group_cards if market_price(card) is not None]
    sorted_variants = sorted(priced_variants, key=market_price)
    single_special_finish = has_single_special_finish(group_cards)

    regular_variant = sorted_variants[0] if sorted_variants else None
    foil_variant = None if single_special_finish or len(sorted_variants) < 2 else sorted_variants[-1]
    reference_card = group_cards[0]

    regular_price = market_price(regular_variant) if regular_variant else None
    foil_price = market_price(foil_variant) if foil_variant else None
    special_price = regular_price if single_special_finish else None

    return {
        "set_code": episode.get("code"),
        "set_name": episode.get("name"),
        "episode_id": episode.get("id"),
        "card_number": str(reference_card.get("card_number")),
        "name": reference_card.get("name"),
        "rarity": reference_card.get("rarity"),
        "key": "|".join(
            [
                normalize_key(episode.get("code", "")),
                str(reference_card.get("card_number")),
                normalize_key(reference_card.get("name", "")),
            ]
        ),
        "finish_type": "special" if single_special_finish else "standard",
        "regular_price_eur": regular_price,
        "foil_price_eur": foil_price,
        "special_price_eur": special_price,
        "price_source": "eu_only_then_lowest",
        "variant_count": len(group_cards),
        "priced_variant_count": len(priced_variants),
        "regular_variant": compact_variant(regular_variant) if regular_variant else None,
        "foil_variant": compact_variant(foil_variant) if foil_variant else None,
        "variants": [compact_variant(card) for card in group_cards],
    }


def main():
    episodes = fetch_all_episodes()
    only_episode_id = os.environ.get("ONLY_EPISODE_ID")
    if only_episode_id:
        episodes = [episode for episode in episodes if str(episode.get("id")) == only_episode_id]

    output = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "lorcana-prices-api",
        "price_rule": "Use lowest_near_mint_EU_only, fallback to lowest_near_mint. Store available Cardmarket aggregates such as 7d_average, 30d_average, global/EU lows and language lows when provided. Epic and Enchanted are treated as single special finish. For duplicate standard same set/name/number variants, lower price is regular and higher price is foil.",
        "episodes": [],
        "prices": [],
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
            group_key = (
                normalize_key(episode.get("code", "")),
                str(card.get("card_number")),
                normalize_key(card.get("name", "")),
            )
            grouped_cards.setdefault(group_key, []).append(card)

        for group_cards in grouped_cards.values():
            output["prices"].append(build_price_entry(episode, group_cards))

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
