import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class JikelScraper(BaseStrollerScraper):
    """Jikel Baby - Custom single-page site (not a real e-commerce store).
    The site is a brand showcase at jikelbaby.ae with category pages
    like /strollers, /carseats, etc. It doesn't have individual product
    pages with /products/ URLs. Products are listed directly on category pages.
    We scrape product data directly from the category page cards.
    """
    RETAILER_NAME = "Jikel"
    BASE_URL = "https://www.jikelbaby.ae"
    LISTING_URL = "https://www.jikelbaby.ae/strollers"

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        """Jikel doesn't have individual product pages.
        Instead, we return the category URL as a marker and scrape cards
        directly from the listing page.
        """
        await page.goto(self._get_start_url(), wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)

        # Check if there are product cards on the page
        cards = await page.query_selector_all(
            ".product-card, .product-item, [class*='product'], "
            ".collection-products .grid-item, .grid-product"
        )

        if cards:
            # Return fake URLs based on card count so the scraper loop runs
            urls = []
            for i in range(len(cards)):
                urls.append(f"{self.BASE_URL}/strollers#product-{i}")
            return urls

        # Try jikelbaby.com (the .com version might have products)
        try:
            await page.goto("https://www.jikelbaby.com/collections", wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(2)
            links = await page.query_selector_all("a[href*='/products/']")
            urls = set()
            for link in links:
                href = await link.get_attribute("href")
                if href and "/products/" in href:
                    clean = href.split("?")[0]
                    if clean.startswith("/"):
                        full = f"https://www.jikelbaby.com{clean}"
                    else:
                        full = clean
                    urls.add(full)
            if urls:
                return list(urls)
        except Exception:
            pass

        return []

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        # If the URL is from jikelbaby.com, scrape normally
        if "jikelbaby.com" in url and "/products/" in url:
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
                product.product = await self._safe_text(
                    page,
                    "h1.product__title, h1.product-title, "
                    ".product-single__title, .product__title, h1"
                )
            product.brand = product.brand or "Jikel"
            if not product.price:
                product.price = await self._safe_text(
                    page,
                    ".product__price, .product-price, .price, "
                    "[class*='price'] .money, [class*='price']"
                )
            if not product.description:
                product.description = await self._safe_text(
                    page,
                    ".product__description, .product-description, "
                    ".product-single__description, [class*='description']"
                )
            # Try Shopify product data for name fallback
            if not product.product:
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
                        product.product = shopify_data.get("title", "")
                        if not product.brand or product.brand == "Jikel":
                            product.brand = shopify_data.get("vendor", "Jikel")
                except Exception:
                    pass

            # Fallback: use page title
            if not product.product:
                try:
                    title = await page.title()
                    if title:
                        # Strip store name from title
                        for sep in [" – ", " | ", " - "]:
                            if sep in title:
                                product.product = title.split(sep)[0].strip()
                                break
                        else:
                            product.product = title.strip()
                except Exception:
                    pass

            # Last resort: extract from meta og:title
            if not product.product:
                product.product = await self._safe_attr(page, 'meta[property="og:title"]', "content")

            features = await self._safe_all_text(page, ".product-description li, [class*='feature'] li")
            if features:
                product.features = " ; ".join(features[:15])

            return product

        # For jikelbaby.ae (brand showcase), scrape product card from listing
        if "#product-" in url:
            idx_str = url.split("#product-")[-1]
            try:
                idx = int(idx_str)
            except ValueError:
                return None

            # Navigate to listing page if not already there
            current = page.url
            if "/strollers" not in current:
                await page.goto(f"{self.BASE_URL}/strollers", wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(3)

            # Get product cards
            cards = await page.query_selector_all(
                ".product-card, .product-item, [class*='product'], "
                ".collection-products .grid-item, .grid-product"
            )

            if idx >= len(cards):
                return None

            card = cards[idx]
            product = StrollerProduct()
            product.brand = "Jikel"

            # Extract data from card
            product.product = await self._safe_text(card, "h2, h3, h4, .product-title, [class*='title']")
            product.price = await self._safe_text(card, ".price, [class*='price']")
            product.description = await self._safe_text(card, ".description, [class*='description'], p")

            # Try to get image
            img = await card.query_selector("img")
            if img:
                product.image_url = await img.get_attribute("src") or ""

            return product if product.product else None

        return None
