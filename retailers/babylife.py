import asyncio
import re
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class BabyLifeScraper(BaseStrollerScraper):
    """BabyLife UAE - Odoo e-commerce platform.
    Product URLs: /shop/PRODUCT-NAME-ID (e.g., /shop/belecoo-baby-stroller-1243)
    Must filter out: /shop/cart, /shop/wishlist, /shop/all-brands, /shop/category/*
    """
    RETAILER_NAME = "BabyLife UAE"
    BASE_URL = "https://www.babylifeuae.com"
    LISTING_URL = "https://www.babylifeuae.com/shop/category/gear-strollers-prams-2"

    # Non-product /shop/ paths to exclude
    _EXCLUDE_PATHS = {
        "/shop/cart", "/shop/wishlist", "/shop/all-brands",
        "/shop/checkout", "/shop/address", "/shop/confirm",
        "/shop/payment", "/shop/login", "/shop/change_pricelist",
    }

    def _is_product_url(self, href: str) -> bool:
        """Check if URL is an Odoo product page."""
        if not href:
            return False
        path = href.split("?")[0].rstrip("/")

        # Must be under /shop/
        if "/shop/" not in path:
            return False

        # Exclude known non-product paths
        for ex in self._EXCLUDE_PATHS:
            if ex in path:
                return False

        # Exclude category pages
        if "/shop/category/" in path:
            return False

        # Exclude Arabic version duplicates
        if "/ar/shop/" in path:
            return False

        # Odoo product URLs end with a numeric ID
        # e.g., /shop/belecoo-baby-stroller-1243
        segments = path.split("/")
        last_segment = segments[-1] if segments else ""
        # Check if last segment contains a trailing number (product ID)
        if re.search(r'-\d+$', last_segment) or re.match(r'\d+$', last_segment):
            return True

        return False

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        urls = set()

        # Load the strollers category page
        await page.goto(self._get_start_url(), wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)

        # Scroll to load all products
        await self._scroll_to_bottom(page, pause=1.5, max_scrolls=20)

        # Collect product links
        links = await page.query_selector_all("a[href*='/shop/']")
        for link in links:
            href = await link.get_attribute("href")
            if href and self._is_product_url(href):
                clean = href.split("?")[0]
                full = self._make_absolute(clean)
                urls.add(full)

        # Try pagination
        page_num = 2
        while page_num <= 10:
            paged_url = f"{self._get_start_url()}?page={page_num}"
            try:
                await page.goto(paged_url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(2)

                new_count = 0
                links = await page.query_selector_all("a[href*='/shop/']")
                for link in links:
                    href = await link.get_attribute("href")
                    if href and self._is_product_url(href):
                        clean = href.split("?")[0]
                        full = self._make_absolute(clean)
                        if full not in urls:
                            urls.add(full)
                            new_count += 1

                if new_count == 0:
                    break
            except Exception:
                break
            page_num += 1
            await random_delay(1.0, 2.0)

        # Fallback: search
        if not urls:
            search_url = f"{self.BASE_URL}/shop?search={self.keyword}"
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(2)
                links = await page.query_selector_all("a[href*='/shop/']")
                for link in links:
                    href = await link.get_attribute("href")
                    if href and self._is_product_url(href):
                        urls.add(self._make_absolute(href.split("?")[0]))
            except Exception:
                pass

        return list(urls)

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(2)

        product = StrollerProduct()

        # JSON-LD
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

        # Odoo DOM selectors
        if not product.product:
            product.product = await self._safe_text(page, "h1, #product_detail h1, .product_detail_name")
        if not product.brand:
            product.brand = await self._safe_text(page, "[class*='brand'], .product-brand")
        if not product.price:
            # Odoo uses specific price selectors
            product.price = await self._safe_text(
                page,
                ".product_price .oe_price .oe_currency_value, "
                ".product_price span[class*='price'], "
                "[class*='price'] .oe_currency_value, "
                ".product_price"
            )
            if product.price and not product.price.startswith("AED"):
                product.price = f"AED {product.price}"
        if not product.description:
            product.description = await self._safe_text(
                page,
                "#product_full_description, .product_description, "
                "[class*='description']"
            )

        features = await self._safe_all_text(page, "[class*='description'] li, [class*='feature'] li")
        if features:
            product.features = " ; ".join(features[:15])

        specs = await self._extract_spec_table(page, "table, [class*='spec']")
        product.weight = specs.get("weight", "")
        product.color = specs.get("color", specs.get("colour", ""))
        product.suitable_for = specs.get("suitable for", specs.get("age", ""))

        return product
