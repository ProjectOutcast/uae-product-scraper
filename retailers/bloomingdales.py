import asyncio
import re
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class BloomingdalesScraper(BaseStrollerScraper):
    """Bloomingdale's UAE - Salesforce Commerce platform.
    Product URLs end with .html and contain SKU codes like:
      /brand-product-name-SKUxColor.html
    """
    RETAILER_NAME = "Bloomingdales"
    BASE_URL = "https://www.bloomingdales.ae"
    LISTING_URL = "https://www.bloomingdales.ae/kids-baby/"

    # Category pages to exclude
    _CATEGORY_PATHS = {
        "/kids-baby/", "/bags/", "/designers/", "/beauty/", "/shoes/",
        "/women/", "/men/", "/home/", "/account/", "/search",
    }

    def _is_product_url(self, href: str) -> bool:
        """Check if URL is a product page (not category/nav)."""
        if not href or not href.endswith(".html"):
            return False
        path = href.split("?")[0]
        # Exclude known category pages
        for cat in self._CATEGORY_PATHS:
            if path.rstrip("/") == cat.rstrip("/") or path == cat:
                return False
        # Product URLs contain a SKU-like pattern: letters/digits followed by x (color)
        basename = path.split("/")[-1]
        # e.g., fendi-baby-set-CLO219140176xMultiColour.html
        if re.search(r'[A-Z]{2,}\d{5,}', basename):
            return True
        # Also accept if it has brand-product pattern with .html
        if basename.count("-") >= 2:
            return True
        return False

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        # Try search first for strollers
        search_url = f"{self.BASE_URL}/search?q={self.keyword}"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(4)

        # Scroll to load all results
        await self._scroll_to_bottom(page, pause=2.0, max_scrolls=30)

        urls = set()
        links = await page.query_selector_all("a[href$='.html']")
        for link in links:
            href = await link.get_attribute("href")
            if href and self._is_product_url(href):
                clean = href.split("?")[0]
                full = self._make_absolute(clean)
                urls.add(full)

        # Fallback: try the kids-baby category page
        if not urls:
            await page.goto(self._get_start_url(), wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(3)
            await self._scroll_to_bottom(page, pause=2.0, max_scrolls=20)

            links = await page.query_selector_all("a[href$='.html']")
            for link in links:
                href = await link.get_attribute("href")
                if href and self._is_product_url(href):
                    clean = href.split("?")[0]
                    full = self._make_absolute(clean)
                    urls.add(full)

        return list(urls)

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)

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

        if not product.product:
            product.product = await self._safe_text(page, "h1, [class*='product-name']")
        if not product.brand:
            product.brand = await self._safe_text(page, "[class*='brand'], .product-brand, [class*='designer']")
        if not product.price:
            product.price = await self._safe_text(page, "[class*='price']")
        if not product.description:
            product.description = await self._safe_text(page, "[class*='description'], .product-details")

        features = await self._safe_all_text(page, "[class*='feature'] li, .product-description li")
        if features:
            product.features = " ; ".join(features[:15])

        specs = await self._extract_spec_table(page, "[class*='spec'], table")
        product.weight = specs.get("weight", "")
        product.color = specs.get("color", specs.get("colour", ""))

        return product
