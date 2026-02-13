import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class JuniorCoutureScraper(BaseStrollerScraper):
    """Junior Couture UAE - Magento/Salesforce Commerce.
    Product URLs: /en/brand-product-name/SKU.html
    Uses catalogsearch for keyword search.
    """
    RETAILER_NAME = "Junior Couture"
    BASE_URL = "https://www.juniorcouture.ae"
    LISTING_URL = "https://www.juniorcouture.ae/en/strollers"

    # CMS / non-product .html pages on Junior Couture
    _CMS_PAGES = {
        "returns-exchanges-policy", "store-locator", "about-us",
        "privacy-policy", "shipping-delivery", "contact-us",
        "terms-and-conditions", "faq", "gift-card", "size-guide",
    }

    def _is_product_url(self, href: str) -> bool:
        """Check if a URL is a product page."""
        if not href or not href.endswith(".html"):
            return False
        path = href.split("?")[0]
        # Must contain /en/
        if "/en/" not in path:
            return False
        # Exclude known non-product patterns
        excludes = [
            "/gift-card", "/category", "/search", "/cart",
            "/account", "/checkout", "/contact",
        ]
        for ex in excludes:
            if ex in path.lower():
                return False
        # Exclude CMS pages
        basename = path.rstrip("/").split("/")[-1].replace(".html", "")
        if basename in self._CMS_PAGES:
            return False
        # Product URLs have format: /en/brand-product-name/SKU.html
        # Must have at least 4 parts: ['', 'en', 'brand-product', 'SKU.html']
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 3:  # 'en', 'brand-product-name', 'SKU.html'
            # The SKU filename usually contains uppercase letters and digits
            sku_file = parts[-1].replace(".html", "")
            if any(c.isupper() for c in sku_file) and any(c.isdigit() for c in sku_file):
                return True
        return False

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        urls = set()

        # Try catalogsearch first (most reliable for Magento)
        search_url = f"{self.BASE_URL}/en/catalogsearch/result/?q={self.keyword}"
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(3)
            await self._scroll_to_bottom(page, pause=1.5, max_scrolls=20)

            links = await page.query_selector_all("a[href$='.html']")
            for link in links:
                href = await link.get_attribute("href")
                if href and self._is_product_url(href):
                    # Remove ?size= variants to deduplicate
                    clean = href.split("?")[0]
                    full = self._make_absolute(clean)
                    urls.add(full)
        except Exception:
            pass

        # Fallback: listing page
        if not urls:
            try:
                await page.goto(self._get_start_url(), wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(3)
                await self._scroll_to_bottom(page, pause=1.5, max_scrolls=20)

                links = await page.query_selector_all("a[href$='.html']")
                for link in links:
                    href = await link.get_attribute("href")
                    if href and self._is_product_url(href):
                        clean = href.split("?")[0]
                        full = self._make_absolute(clean)
                        urls.add(full)
            except Exception:
                pass

        # Fallback: homepage product links
        if not urls:
            try:
                await page.goto(f"{self.BASE_URL}/en/", wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(3)
                await self._scroll_to_bottom(page, pause=1.5, max_scrolls=10)

                links = await page.query_selector_all("a[href$='.html']")
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

        if not product.product:
            product.product = await self._safe_text(page, "h1.page-title span, h1.page-title, h1")
        if not product.brand:
            product.brand = await self._safe_text(page, "[class*='brand'], .product-brand")
        if not product.price:
            product.price = await self._safe_text(page, ".price-wrapper .price, .special-price .price, [class*='price'] .price")
        if not product.description:
            product.description = await self._safe_text(page, "[class*='description'], .product-description")

        features = await self._safe_all_text(page, "[class*='description'] li, [class*='feature'] li")
        if features:
            product.features = " ; ".join(features[:15])

        specs = await self._extract_spec_table(page, "table, .additional-attributes, [class*='spec']")
        product.weight = specs.get("weight", "")
        product.color = specs.get("color", specs.get("colour", ""))

        return product
