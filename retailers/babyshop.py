import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class BabyshopScraper(BaseStrollerScraper):
    """Babyshop (Landmark Group) - React/Next.js SPA.
    Product URLs follow pattern: /ae/en/buy-PRODUCT-NAME/p/ID
    """
    RETAILER_NAME = "Babyshop"
    BASE_URL = "https://www.babyshopstores.com"
    LISTING_URL = "https://www.babyshopstores.com/ae/en/c/baby-gear-strollersandprams-strollers"

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        await page.goto(self._get_start_url(), wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(6)  # Heavy JS SPA needs time to hydrate

        # Scroll to load all products — Babyshop uses lazy loading
        await self._scroll_to_bottom(page, pause=2.0, max_scrolls=40)

        # Also try clicking Load More / Show More
        for _ in range(20):
            btn = await page.query_selector(
                "button:has-text('Load More'), button:has-text('Show More'), "
                "[class*='loadMore'], [class*='showMore']"
            )
            if not btn:
                break
            try:
                if not await btn.is_visible():
                    break
                await btn.scroll_into_view_if_needed()
                await btn.click()
                await asyncio.sleep(2)
            except Exception:
                break

        urls = set()
        # Primary selector: product links with /p/ pattern
        links = await page.query_selector_all("a[href*='/p/']")
        for link in links:
            href = await link.get_attribute("href")
            if href and "/p/" in href and "/buy-" in href:
                clean = href.split("?")[0]
                if clean.startswith("/"):
                    full = f"https://www.babyshopstores.com{clean}"
                else:
                    full = clean
                urls.add(full)

        # Fallback: broader product card selectors
        if not urls:
            links = await page.query_selector_all(
                ".product-card a[href], .product-tile a[href], "
                "[class*='product'] a[href*='/buy-']"
            )
            for link in links:
                href = await link.get_attribute("href")
                if href and "/buy-" in href:
                    clean = href.split("?")[0]
                    if clean.startswith("/"):
                        full = f"https://www.babyshopstores.com{clean}"
                    else:
                        full = clean
                    urls.add(full)

        return list(urls)

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(4)  # Wait for JS rendering

        product = StrollerProduct()

        # JSON-LD is the most reliable source
        ld = await self._extract_json_ld(page)
        if ld:
            product.product = ld.get("name", "")
            product.description = ld.get("description", "")
            img = ld.get("image", "")
            if isinstance(img, list):
                product.image_url = img[0] if img else ""
            else:
                product.image_url = img
            offers = ld.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if offers.get("price"):
                product.price = f"AED {offers['price']}"
            brand_info = ld.get("brand", {})
            if isinstance(brand_info, dict):
                product.brand = brand_info.get("name", "")
            elif isinstance(brand_info, str):
                product.brand = brand_info

        # Try dataLayer for additional data
        if not product.brand or not product.price:
            try:
                dl_data = await page.evaluate("""
                    () => {
                        if (window.dataLayer) {
                            for (const entry of window.dataLayer) {
                                if (entry.ecommerce && entry.ecommerce.items) {
                                    const item = entry.ecommerce.items[0];
                                    return {
                                        brand: item.item_brand || '',
                                        price: item.price || '',
                                        name: item.item_name || '',
                                    };
                                }
                            }
                        }
                        return null;
                    }
                """)
                if dl_data:
                    if not product.brand and dl_data.get("brand"):
                        product.brand = dl_data["brand"]
                    if not product.price and dl_data.get("price"):
                        product.price = f"AED {dl_data['price']}"
                    if not product.product and dl_data.get("name"):
                        product.product = dl_data["name"]
            except Exception:
                pass

        # DOM fallbacks
        if not product.product:
            product.product = await self._safe_text(page, "h1")
        if not product.brand:
            product.brand = await self._safe_text(page, "[class*='brand'], .product-brand, [data-testid*='brand']")
        if not product.price:
            price_text = await self._safe_text(page, "[class*='price'] span, [class*='Price'], .product-price")
            if price_text:
                product.price = price_text.strip()

        if not product.description:
            product.description = await self._safe_text(page, "[class*='description'], .product-description, [class*='detail']")

        # Specs
        specs = await self._extract_spec_table(page, "[class*='spec'], [class*='detail'], table")
        product.weight = specs.get("weight", "")
        product.color = specs.get("color", specs.get("colour", ""))
        product.suitable_for = specs.get("suitable for", specs.get("age", specs.get("age range", "")))

        # Features
        features = await self._safe_all_text(page, "[class*='feature'] li, .product-description li, [class*='detail'] li")
        if features:
            product.features = " ; ".join(features[:15])

        return product
