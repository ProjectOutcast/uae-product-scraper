import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class NananScraper(BaseStrollerScraper):
    """Nanan UAE - Magento-based baby store.
    Product links use Magento's a.product-item-link selector.
    Category pages like /accessories.html, /bags.html must be filtered out.
    """
    RETAILER_NAME = "Nanan"
    BASE_URL = "https://www.nanan.ae/en"
    LISTING_URL = "https://www.nanan.ae/en/strollers.html"

    # Known category pages to exclude
    _CATEGORY_PAGES = {
        "strollers.html", "accessories.html", "bags.html",
        "clothing.html", "shoes.html", "bedding.html",
    }

    def _is_product_url(self, href: str) -> bool:
        """Check if URL is a Magento product page (not category)."""
        if not href or not href.endswith(".html"):
            return False
        path = href.split("?")[0]
        basename = path.rstrip("/").split("/")[-1]

        # Exclude known category pages
        if basename in self._CATEGORY_PAGES:
            return False

        # Exclude pages with subcategory paths like /accessories/tape.html
        # Product pages are usually /en/product-name.html (2-3 segments)
        # But some category pages are /en/accessories/subcategory.html
        path_after_en = path.split("/en/")[-1] if "/en/" in path else path
        segments = [s for s in path_after_en.split("/") if s]

        # If there's a subcategory (e.g., /en/accessories/tape.html), likely not a product
        # unless it's a deep product URL
        if len(segments) >= 2:
            parent = segments[0].replace(".html", "")
            if parent in ("accessories", "bags", "clothing", "shoes", "bedding",
                         "nursery", "feeding", "bathing"):
                return False

        return True

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        urls = set()
        page_num = 1

        while page_num <= 20:
            url = f"{self._get_start_url()}?p={page_num}" if page_num > 1 else self._get_start_url()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(3)
            except Exception:
                break

            # Use Magento-specific product link selector (most reliable)
            links = await page.query_selector_all("a.product-item-link")

            # Fallback to broader selectors
            if not links:
                links = await page.query_selector_all(
                    ".product-item a[href$='.html'], "
                    ".product-card a[href$='.html']"
                )

            new_count = 0
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
            page_num += 1
            await random_delay(1.5, 3.0)

        # Fallback: try Magento search
        if not urls:
            try:
                search_url = f"https://www.nanan.ae/en/catalogsearch/result/?q={self.keyword}"
                await page.goto(search_url, wait_until="domcontentloaded")
                await asyncio.sleep(2)

                links = await page.query_selector_all("a.product-item-link, .product-item a[href$='.html']")
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

        # Magento DOM selectors
        if not product.product:
            product.product = await self._safe_text(page, "h1.page-title span, h1.page-title, h1")
        if not product.brand:
            product.brand = await self._safe_text(page, "[class*='brand'], .product-brand")
        if not product.price:
            product.price = await self._safe_text(
                page,
                ".price-wrapper .price, .special-price .price, "
                "[class*='price'] .price, .price-box .price"
            )
        if not product.description:
            product.description = await self._safe_text(
                page,
                "#product-description, .product.attribute.description, "
                "[class*='description']"
            )

        # Magento spec table
        specs = await self._extract_spec_table(page, ".additional-attributes, .product-specs, table.data")
        product.weight = specs.get("weight", "")
        product.color = specs.get("color", specs.get("colour", ""))
        product.frame_color = specs.get("frame color", specs.get("frame colour", ""))
        product.suitable_for = specs.get("suitable for", specs.get("age", specs.get("recommended age", "")))

        features = await self._safe_all_text(page, ".product-description li, [class*='feature'] li")
        if features:
            product.features = " ; ".join(features[:15])

        return product
