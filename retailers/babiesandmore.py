import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class BabiesAndMoreScraper(BaseStrollerScraper):
    """Babies and More - Next.js clothing-focused store.
    Primarily a clothing brand, but may have some gear.
    Product URLs: /en-ae/CATEGORY/PRODUCT-NAME/p/ or /p-N/
    The strollers page redirects to /clothing, so we use search.
    """
    RETAILER_NAME = "Babies and More"
    BASE_URL = "https://www.babiesandmore.com"
    LISTING_URL = "https://www.babiesandmore.com/en-ae/strollers"

    def _is_product_url(self, href: str) -> bool:
        """Check if URL is a product page."""
        if not href:
            return False
        path = href.split("?")[0].rstrip("/")
        # Product URLs end with /p/ or /p-N/
        if "/p/" in path or "/p-" in path.split("/")[-1]:
            return True
        return False

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        urls = set()

        # Try search since listing page redirects to clothing
        for search_url in [
            f"{self.BASE_URL}/en-ae/catalogsearch/result/?q={self.keyword}",
            f"{self.BASE_URL}/en-ae/search?q={self.keyword}",
        ]:
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(4)
                await self._scroll_to_bottom(page, pause=1.5, max_scrolls=15)

                links = await page.query_selector_all("a[href]")
                for link in links:
                    href = await link.get_attribute("href")
                    if href and self._is_product_url(href):
                        clean = href.split("?")[0]
                        full = self._make_absolute(clean)
                        urls.add(full)

                if urls:
                    break
            except Exception:
                continue

        # Fallback: try listing URL anyway (may redirect but have some products)
        if not urls:
            try:
                await page.goto(self._get_start_url(), wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(3)
                await self._scroll_to_bottom(page, pause=1.5, max_scrolls=10)

                links = await page.query_selector_all("a[href]")
                for link in links:
                    href = await link.get_attribute("href")
                    if href and self._is_product_url(href):
                        clean = href.split("?")[0]
                        full = self._make_absolute(clean)
                        urls.add(full)
            except Exception:
                pass

        return list(urls)

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)

        product = StrollerProduct()

        # Try __NEXT_DATA__ for Next.js
        next_data = await self._extract_next_data(page)
        if next_data:
            try:
                props = next_data.get("props", {}).get("pageProps", {})
                prod_data = props.get("product", props.get("productData", {}))
                if prod_data:
                    product.product = prod_data.get("name", prod_data.get("title", ""))
                    product.brand = prod_data.get("brand", {}).get("name", "") if isinstance(prod_data.get("brand"), dict) else prod_data.get("brand", "")
                    product.description = prod_data.get("description", "")
                    price_info = prod_data.get("price", {})
                    if isinstance(price_info, dict):
                        product.price = f"AED {price_info.get('current', price_info.get('value', ''))}"
                    elif price_info:
                        product.price = f"AED {price_info}"
                    product.image_url = prod_data.get("image", prod_data.get("imageUrl", ""))
            except Exception:
                pass

        # JSON-LD fallback
        if not product.product:
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

        if not product.product:
            product.product = await self._safe_text(page, "h1")
        if not product.brand:
            product.brand = await self._safe_text(page, "[class*='brand'], .product-brand, .product-vendor")
        if not product.price:
            product.price = await self._safe_text(page, "[class*='price'], .product-price")
        if not product.description:
            product.description = await self._safe_text(page, "[class*='description'], .product-description")

        features = await self._safe_all_text(page, "[class*='description'] li")
        if features:
            product.features = " ; ".join(features[:15])

        specs = await self._extract_spec_table(page, "table, [class*='spec']")
        product.weight = specs.get("weight", "")
        product.color = specs.get("color", specs.get("colour", ""))
        product.suitable_for = specs.get("suitable for", specs.get("age", ""))

        return product
