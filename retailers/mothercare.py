import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class MothercareScraper(BaseStrollerScraper):
    RETAILER_NAME = "Mothercare"
    BASE_URL = "https://www.mothercare.ae"
    LISTING_URL = "https://www.mothercare.ae/en/shop-strollers"

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        await page.goto(self._get_start_url(), wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(5)  # JS-rendered SPA, needs time to hydrate

        # Click "load more products" button until all products are shown
        for _ in range(30):
            btn = await page.query_selector("button.pager-button")
            if not btn:
                break
            try:
                visible = await btn.is_visible()
                if not visible:
                    break
                await btn.scroll_into_view_if_needed()
                await btn.click()
                await asyncio.sleep(3)
                await random_delay(0.5, 1.5)
            except Exception:
                break

        # Extract product URLs from product cards
        urls = set()
        links = await page.query_selector_all("a.product-item-title[href], a[data-link='pdp'][href]")

        for link in links:
            href = await link.get_attribute("href")
            if href and "/buy-" in href:
                clean = href.split("?")[0]
                # Ensure proper absolute URL (href is like /en/buy-...)
                if clean.startswith("/"):
                    full = f"https://www.mothercare.ae{clean}"
                else:
                    full = clean
                urls.add(full)

        return list(urls)

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)  # Wait for JS to render product details

        product = StrollerProduct()

        # JSON-LD first — most reliable source on Mothercare
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

        # DOM fallbacks for title
        if not product.product:
            product.product = await self._safe_text(page, "h6.pdp-product__title")

        # DOM fallback for brand from attributes section
        if not product.brand:
            product.brand = await self._safe_text(
                page,
                ".pdp-product-description__attribute--product_brand span:not(.pdp-product-description__attribute--label)"
            )

        # DOM fallback for price
        if not product.price:
            price_text = await self._safe_text(page, ".pdp-product__prices span.dropin-price")
            if price_text:
                product.price = price_text.strip()

        # Meta tag fallbacks
        if not product.price:
            meta_price = await self._safe_attr(page, 'meta[name="product:price-amount"]', "content")
            if meta_price:
                product.price = f"AED {meta_price}"

        if not product.brand:
            # Try dataLayer
            try:
                brand = await page.evaluate("""
                    () => {
                        if (window.dataLayer) {
                            for (const entry of window.dataLayer) {
                                if (entry.ecommerce && entry.ecommerce.items) {
                                    const item = entry.ecommerce.items[0];
                                    if (item && item.item_brand) return item.item_brand;
                                }
                            }
                        }
                        return '';
                    }
                """)
                if brand:
                    product.brand = brand
            except Exception:
                pass

        # Color from attributes section
        product.color = await self._safe_text(
            page,
            ".pdp-product-description__attribute--color span:not(.pdp-product-description__attribute--label)"
        )

        # Description from accordion
        if not product.description:
            # Try clicking to expand the description accordion
            try:
                details_el = await page.query_selector("details.pdp-product__description")
                if details_el:
                    summary = await details_el.query_selector("summary")
                    if summary:
                        await summary.click()
                        await asyncio.sleep(0.5)
            except Exception:
                pass
            product.description = await self._safe_text(
                page, ".pdp-product__description--details.accordion-item-body"
            )

        # Features — try to get bullet points from description
        features = await self._safe_all_text(
            page,
            ".pdp-product__description--details li, "
            ".pdp-product__description ul li"
        )
        if features:
            product.features = " ; ".join(features[:15])

        # Specs from attributes section
        try:
            attrs = await page.query_selector_all(".pdp-product-description__attribute")
            for attr_el in attrs:
                label_el = await attr_el.query_selector(".pdp-product-description__attribute--label")
                if not label_el:
                    continue
                label = (await label_el.inner_text()).strip().lower()
                # Get the sibling span (value)
                spans = await attr_el.query_selector_all("span:not(.pdp-product-description__attribute--label)")
                value = ""
                for span in spans:
                    text = (await span.inner_text()).strip()
                    if text:
                        value = text
                        break

                if not value:
                    continue

                if "weight" in label:
                    product.weight = value
                elif "colour" in label or "color" in label:
                    if not product.color:
                        product.color = value
                elif "age" in label or "suitable" in label:
                    product.suitable_for = value
        except Exception:
            pass

        return product
