# Lorcana Price Cache

This repo can publish a daily `data/lorcana-prices-v1.json` file with Cardmarket EUR prices from Lorcana Prices API.

## GitHub Setup

1. Push this project to a GitHub repository.
2. In GitHub, open `Settings > Secrets and variables > Actions`.
3. Add a repository secret named `RAPIDAPI_KEY`.
4. Paste the RapidAPI key as the secret value.
5. Add a repository variable named `CARDMARKET_PRICE_GUIDE_URL` with the public Cardmarket Lorcana price guide URL:

```text
https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_19.json
```

6. Optional: add these repository variables for sealed products and Lorcana accessories. The script has the same values as defaults, but defining them in GitHub makes the setup explicit:

```text
CARDMARKET_LORCANA_NONSINGLES_URL=https://downloads.s3.cardmarket.com/productCatalog/productList/products_nonsingles_19.json
CARDMARKET_ACCESSORIES_URL=https://downloads.s3.cardmarket.com/productCatalog/productList/products_accessories.json
CARDMARKET_ACCESSORIES_PRICE_GUIDE_URL=https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_accessories.json
```

7. Open `Actions > Update Lorcana prices`.
8. Run the workflow manually once with `Run workflow`.

The workflow also runs every day at 04:17 UTC.

## App URL

If the GitHub repository is public, the app can read:

```text
https://raw.githubusercontent.com/<owner>/<repo>/<branch>/data/lorcana-prices-v1.json
```

For example, if the branch is `main`:

```text
https://raw.githubusercontent.com/<owner>/<repo>/main/data/lorcana-prices-v1.json
```

## Price Rules

- Main price: `lowest_near_mint_EU_only`.
- Fallback: `lowest_near_mint`.
- Language-specific and effective lowest values are stored for diagnostics, but they are not used as the collection valuation price.
- Duplicate same set/name/number variants are sorted by price.
- Lower priced variant is treated as regular.
- Higher priced variant is treated as foil.
- If Lorcana Prices API returns no price for a card, the generator tries `CARDMARKET_PRICE_GUIDE_URL` as fallback.
- Cardmarket Price Guide fallback is matched by `idProduct` from LorcanaJSON `externalLinks.cardmarketId`.
- Fallback prices support Cardmarket JSON, CSV and CSV.GZ.
- Fallback prices use the guide's `low` / `Low Price` first, then `trend` / `Trend Price`.
- The output also includes `sealed_products`, built from Cardmarket public non-singles/accessories product catalog files and joined to price guides by `idProduct`.
- Sealed product images are intentionally stored as `image_url: null` until an image database is available.
