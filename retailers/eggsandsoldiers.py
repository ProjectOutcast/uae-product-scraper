import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class EggsAndSoldiersScraper(BaseStrollerScraper):
    """Eggs and Soldiers - WooCommerce baby boutique in Dubai.
    Search: /?s=KEYWORD&post_type=product
    Category: /product-category/out-about/strollers/
    Product URLs are single-segment slugs like /bugaboo-dragonfly/
    """
    RETAILER_NAME = "Eggs and Soldiers"
    BASE_URL = "https://www.eggsnsoldiers.com"
    LISTING_URL = "https://www.eggsnsoldiers.com/product-category/out-about/strollers/"

    # Non-product pages
    _NON_PRODUCT_SLUGS = {
        "brands", "classes", "our-stores", "contact-us", "advice-help",
        "shipping-delivery", "cart", "checkout", "my-account", "shop",
        "about-us", "returns", "privacy-policy", "terms-conditions",
        "faq", "blog", "gift-card", "gift-cards",
    }

    def _extract_product_urls(self, links_data: list) -> set:
        """Filter a list of href strings to find product URLs."""
        urls = set()
        for href in links_data:
            if not href:
                continue
            clean = href.split("?")[0].rstrip("/")
            if clean.startswith("/"):
                clean = f"{self.BASE_URL}{clean}"
            if not clean.startswith(self.BASE_URL):
                continue
            path = clean.replace(self.BASE_URL, "").strip("/")
            # Product pages: single-segment slug, not in exclude list
            if (path
                    and "/" not in path
                    and len(path) > 5
                    and path not in self._NON_PRODUCT_SLUGS
                    and "product-category" not in path
                    and not path.startswith("#")):
                urls.add(clean)
        return urls

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        urls = set()

        # Strategy 1: Try WooCommerce search (most reliable)
        search_url = f"{self.BASE_URL}/?s={self.keyword}&post_type=product"
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(4)
            await self._scroll_to_bottom(page, pause=1.5, max_scrolls=5)

            # Collect hrefs using JavaScript for reliability
            hrefs = await page.evaluate("""
                () => Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.href)
                    .filter(h => h.includes('eggsnsoldiers.com'))
            """)
            urls = self._extract_product_urls(hrefs)
        except Exception:
            pass

        # Strategy 2: Try the strollers category page
        if not urls:
            try:
                await page.goto(self.LISTING_URL, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(4)
                await self._scroll_to_bottom(page, pause=1.5, max_scrolls=5)

                hrefs = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href)
                        .filter(h => h.includes('eggsnsoldiers.com'))
                """)
                urls = self._extract_product_urls(hrefs)
            except Exception:
                pass

        # Strategy 3: Try related categories
        if not urls:
            for cat_url in [
                f"{self.BASE_URL}/product-category/out-about/",
                f"{self.BASE_URL}/product-category/out-about/car-seats/",
            ]:
                try:
                    await page.goto(cat_url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                    await asyncio.sleep(3)

                    hrefs = await page.evaluate("""
                        () => Array.from(document.querySelectorAll('a[href]'))
                            .map(a => a.href)
                            .filter(h => h.includes('eggsnsoldiers.com'))
                    """)
                    urls = self._extract_product_urls(hrefs)
                    if urls:
                        break
                except Exception:
                    continue

        return list(urls)

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(2)

        product = StrollerProduct()

        ld = await self._extract_json_ld(page)
        if ld:
            product.product = ld.get("name", "")
            product.description = ld.get("description", "")
            product.image_url = ld.get("image", "")
            if isinstance(product.image_url, list):
                product.image_url = product.image_url[0] if product.image_url else ""
            offers = ld.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if offers.get("price"):
                product.price = f"AED {offers['price']}"
            brand_info = ld.get("brand", {})
            if isinstance(brand_info, dict):
                product.brand = brand_info.get("name", "")

        # WooCommerce DOM fallbacks
        if not product.product:
            product.product = await self._safe_text(page, "h1.product_title, h1.entry-title, h1")
        if not product.brand:
            product.brand = await self._safe_text(
                page,
                ".woocommerce-product-attributes-item--attribute_pa_brand .woocommerce-product-attributes-item__value, "
                "[class*='brand'], .product-vendor"
            )
        if not product.price:
            product.price = await self._safe_text(
                page,
                ".woocommerce-Price-amount, .price ins .amount, .price .amount, "
                ".summary .price"
            )
        if not product.description:
            product.description = await self._safe_text(
                page,
                ".woocommerce-product-details__short-description, "
                "#tab-description, .product-description"
            )

        # WooCommerce product attributes table
        specs = await self._extract_spec_table(page, ".woocommerce-product-attributes, .shop_attributes, table")
        product.weight = specs.get("weight", "")
        product.color = specs.get("color", specs.get("colour", ""))
        product.suitable_for = specs.get("suitable for", specs.get("age", ""))

        features = await self._safe_all_text(page, ".product-description li, #tab-description li, .woocommerce-Tabs-panel li")
        if features:
            product.features = " ; ".join(features[:15])

        return product
