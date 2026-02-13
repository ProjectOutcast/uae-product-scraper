import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class BirdsAndBeesScraper(BaseStrollerScraper):
    """Birds and Bees - Shopify store.
    Search works at: /search?q=strollers
    Product URLs: /products/PRODUCT-SLUG
    Must filter out gift cards.
    """
    RETAILER_NAME = "Birds and Bees"
    BASE_URL = "https://www.birdsn-bees.com"
    LISTING_URL = "https://www.birdsn-bees.com/collections/strollers"

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        urls = set()

        # Try search first (diagnostic showed it works)
        search_url = f"{self.BASE_URL}/search?q={self.keyword}"
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(3)

            links = await page.query_selector_all("a[href*='/products/']")
            for link in links:
                href = await link.get_attribute("href")
                if href and "/products/" in href:
                    clean = href.split("?")[0]
                    full = self._make_absolute(clean)
                    # Exclude gift cards
                    if "gift-card" not in full.lower():
                        urls.add(full)
        except Exception:
            pass

        # Fallback: try the collections page
        if not urls:
            for try_url in [
                self._get_start_url(),
                f"{self.BASE_URL}/collections/all",
            ]:
                try:
                    await page.goto(try_url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                    await asyncio.sleep(2)

                    links = await page.query_selector_all("a[href*='/products/']")
                    for link in links:
                        href = await link.get_attribute("href")
                        if href and "/products/" in href:
                            clean = href.split("?")[0]
                            full = self._make_absolute(clean)
                            if "gift-card" not in full.lower():
                                urls.add(full)

                    if urls:
                        break
                except Exception:
                    continue

        return list(urls)

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(2)

        product = StrollerProduct()

        # JSON-LD (Shopify always has it)
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

        # Shopify DOM fallbacks
        if not product.product:
            product.product = await self._safe_text(page, "h1.product__title, h1")
        if not product.brand:
            product.brand = await self._safe_text(page, ".product-vendor, .product__vendor, [class*='vendor']")
        if not product.price:
            product.price = await self._safe_text(page, ".product-price, .price, .product__price")
        if not product.description:
            product.description = await self._safe_text(page, ".product-description, .product__description, [class*='description']")

        # Try Shopify product data
        if not product.brand or not product.price:
            try:
                shopify_data = await page.evaluate("""
                    () => {
                        if (window.ShopifyAnalytics && window.ShopifyAnalytics.meta && window.ShopifyAnalytics.meta.product) {
                            return window.ShopifyAnalytics.meta.product;
                        }
                        return null;
                    }
                """)
                if shopify_data:
                    if not product.brand:
                        product.brand = shopify_data.get("vendor", "")
                    if not product.product:
                        product.product = shopify_data.get("title", "")
            except Exception:
                pass

        features = await self._safe_all_text(page, ".product-description li, .product__description li")
        if features:
            product.features = " ; ".join(features[:15])

        return product
