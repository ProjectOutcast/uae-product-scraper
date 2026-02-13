from .mumzworld import MumzworldScraper
from .babyshop import BabyshopScraper
from .mamasandpapas import MamasAndPapasScraper
from .ellijunior import EllieJuniorScraper
from .ounass import OunassScraper
from .bloomingdales import BloomingdalesScraper
from .galerieslafayette import GaleriesLafayetteScraper
from .fivelittleducks import FiveLittleDucksScraper
from .mothercare import MothercareScraper
from .jikel import JikelScraper
from .birdsandbees import BirdsAndBeesScraper
from .juniorcouture import JuniorCoutureScraper
from .lebouquet import LeBouquetScraper
from .babycare import BabyCareScraper
from .nanan import NananScraper
from .babylife import BabyLifeScraper

# DISABLED — sites are dead/unreachable (Feb 2026):
# from .firstcry import FirstCryScraper      # Heavy JS SPA, nothing renders
# from .momstore import MomStoreScraper      # SSL certificate error
# from .sophiababy import SophiaBabyScraper  # DNS resolution failure
# from .babykish import BabyKishScraper      # Brand showcase, not e-commerce
# from .babiesandmore import BabiesAndMoreScraper  # Clothing-only, no strollers/gear
# from .eggsandsoldiers import EggsAndSoldiersScraper  # WooCommerce - 0 stroller products found


def get_scraper_registry():
    return {
        "Mumzworld": MumzworldScraper,
        "Babyshop": BabyshopScraper,
        "Mamas & Papas": MamasAndPapasScraper,
        "Ellie Junior": EllieJuniorScraper,
        "Ounass": OunassScraper,
        "Bloomingdales": BloomingdalesScraper,
        "Galeries Lafayette": GaleriesLafayetteScraper,
        "Five Little Ducks": FiveLittleDucksScraper,
        "Mothercare": MothercareScraper,
        "Jikel": JikelScraper,
        "Birds and Bees": BirdsAndBeesScraper,
        "Junior Couture": JuniorCoutureScraper,
        "Le Bouquet": LeBouquetScraper,
        "Baby Care": BabyCareScraper,
        "Nanan": NananScraper,
        "BabyLife UAE": BabyLifeScraper,
    }
