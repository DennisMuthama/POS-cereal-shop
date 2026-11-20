from decimal import Decimal

from django.core.management.base import BaseCommand

from inventory.models import Cereal

# name, local name, category, icon, shelf life (days), low-stock alert (kg)
CATALOGUE = [
    # Grains
    ("Maize (Whole)", "Mahindi", "GRAIN", "🌽", 365, 50),
    ("Githeri Mix (Maize & Beans)", "Githeri", "GRAIN", "🥣", 270, 20),
    ("Millet", "Wimbi", "GRAIN", "🌾", 365, 20),
    ("Sorghum", "Mtama", "GRAIN", "🌾", 365, 20),
    ("Oats", "", "GRAIN", "🥣", 270, 10),
    # Rice
    ("Rice - Pishori", "Mchele wa Pishori", "RICE", "🍚", 365, 50),
    ("Rice - Basmati", "Mchele wa Basmati", "RICE", "🍚", 365, 25),
    ("Rice - Long Grain", "Mchele", "RICE", "🍚", 365, 25),
    # Flours
    ("Maize Flour", "Unga wa Mahindi (Posho)", "FLOUR", "🌽", 180, 50),
    ("Wheat Flour", "Unga wa Ngano", "FLOUR", "🍞", 180, 50),
    ("Millet Flour", "Unga wa Wimbi", "FLOUR", "🌾", 120, 20),
    ("Sorghum Flour", "Unga wa Mtama", "FLOUR", "🌾", 120, 20),
    ("Cassava Flour", "Unga wa Muhogo", "FLOUR", "🍠", 180, 20),
    ("Porridge Flour (Uji)", "Unga wa Uji", "FLOUR", "🥣", 120, 20),
    # Beans & pulses
    ("Beans - Rosecoco", "Maharagwe", "PULSE", "🫘", 365, 30),
    ("Beans - Yellow", "Maharagwe ya Njano", "PULSE", "🫘", 365, 30),
    ("Beans - Red Kidney", "Maharagwe Mekundu", "PULSE", "🫘", 365, 20),
    ("Black Beans (Njahi)", "Njahi", "PULSE", "🫘", 365, 20),
    ("Green Grams", "Ndengu", "PULSE", "🌱", 365, 30),
    ("Pigeon Peas", "Mbaazi", "PULSE", "🌱", 365, 20),
    ("Cowpeas", "Kunde", "PULSE", "🌱", 365, 20),
    ("Lentils", "", "PULSE", "🫘", 365, 10),
    ("Chickpeas", "", "PULSE", "🫘", 365, 10),
    # Other
    ("Groundnuts", "Karanga", "OTHER", "🥜", 180, 20),
]


class Command(BaseCommand):
    help = "Loads common Kenyan cereals into the catalogue (inactive until stock is received). Safe to run again."

    def handle(self, *args, **options):
        created = 0
        for name, local, category, icon, shelf, low in CATALOGUE:
            _, was_created = Cereal.objects.get_or_create(
                name=name,
                defaults={
                    "swahili_name": local,
                    "category": category,
                    "icon": icon,
                    "shelf_life_days": shelf,
                    "low_stock_kg": Decimal(low),
                    "price_per_kg": Decimal("0"),
                    "is_active": False,
                },
            )
            created += int(was_created)
        self.stdout.write(self.style.SUCCESS(f"Catalogue ready: {created} new, {len(CATALOGUE) - created} already there."))