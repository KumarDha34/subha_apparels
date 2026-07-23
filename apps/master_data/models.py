import re
import colorsys
import nepali_datetime
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Party(TimeStampedModel):
    """Client/Customer who places garment orders."""
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    code_prefix = models.CharField(
        max_length=10, blank=True,
        help_text="Short prefix used in generated order codes, e.g. 'HU' for Huba. Auto-derived from name if left blank.",
    )
    pan_vat = models.CharField(max_length=30, blank=True, verbose_name="PAN / VAT No.")
    credit_terms = models.CharField(max_length=30, blank=True, help_text="e.g. NET 30, NET 15, Advance, COD.")
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                       help_text="Maximum outstanding receivable allowed for this buyer.")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code_prefix:
            self.code_prefix = (re.sub(r"[^A-Za-z]", "", self.name or "")[:2] or "XX").upper()
        super().save(*args, **kwargs)


NEPALI_MONTHS = [
    "Baisakh", "Jestha", "Ashadh", "Shrawan", "Bhadra", "Ashwin",
    "Kartik", "Mangsir", "Poush", "Magh", "Falgun", "Chaitra",
]


class Product(TimeStampedModel):
    """Product / Style master. `code` is always system-generated:
    <first 2 letters of name>-<first 3 letters of current Nepali (BS)
    month>-<3-digit sequence, resets every BS month>, e.g. "TE-ASH-001"."""
    class ProductType(models.TextChoices):
        APPAREL = "Apparel", "Apparel"
        KNITWEAR = "Knitwear", "Knitwear"
        BOTTOMWEAR = "Bottomwear", "Bottomwear"
        OUTERWEAR = "Outerwear", "Outerwear"
        ACCESSORY = "Accessory", "Accessory"
        OTHER = "Other", "Other"

    code = models.CharField(max_length=50, unique=True, blank=True)
    name = models.CharField(max_length=200)
    product_type = models.CharField(
        max_length=50, choices=ProductType.choices, default=ProductType.APPAREL, blank=True,
        help_text="Broad classification of the style, e.g. Apparel.",
    )
    category = models.CharField(
        max_length=100, blank=True,
        help_text="Style category, e.g. T-Shirts, Hoodies, Cargos, Leggings.",
    )
    description = models.TextField(blank=True)
    fabric_types = models.ManyToManyField(
        "FabricType", blank=True, related_name="products",
        help_text="Fabric options this style can be made in (e.g. Pique, Single Jersey).",
    )
    image = models.ImageField(
        upload_to="products/images/", blank=True, null=True,
        help_text="Uploaded reference image of the style (optional).",
    )
    measurement_chart_file = models.FileField(
        upload_to="products/charts/", blank=True, null=True,
        help_text="Uploaded measurement-chart document, e.g. a PDF (optional).",
    )
    image_url = models.URLField(
        max_length=500, blank=True,
        help_text="Legacy image link — kept for older styles; new styles upload an image instead.",
    )
    measurement_chart_url = models.URLField(
        max_length=500, blank=True,
        help_text="Legacy measurement-chart link — kept for older styles; new styles upload a file instead.",
    )
    measurement_chart = models.JSONField(
        default=list, blank=True,
        help_text="Size-wise measurement spec: a list of rows like "
                  "[{'param': 'Chest (in)', 'sizes': {'S': '38', 'M': '40', 'L': '42'}}].",
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_code()
        super().save(*args, **kwargs)

    def _generate_code(self):
        today_bs = nepali_datetime.date.today()
        month_code = NEPALI_MONTHS[today_bs.month - 1][:3].upper()
        name_letters = (re.sub(r"[^A-Za-z]", "", self.name or "")[:2] or "XX").upper()

        count_this_month = 0
        for created_at in Product.objects.values_list("created_at", flat=True):
            bs = nepali_datetime.date.from_datetime_date(timezone.localtime(created_at).date())
            if bs.year == today_bs.year and bs.month == today_bs.month:
                count_this_month += 1

        increment = count_this_month + 1
        while True:
            code = f"{name_letters}-{month_code}-{increment:03d}"
            if not Product.objects.filter(code=code).exists():
                return code
            increment += 1


class ProductComponent(TimeStampedModel):
    """A garment sub-piece (Front Panel, Back Panel, Sleeve, Collar, ...)
    that must be cut in matching quantities before a bundle of complete
    garments can be finalized. A product with zero components is untracked
    at the component level -- cutting/bundling behave exactly as if this
    model didn't exist. `is_primary` designates which component's cut
    quantity represents "how many complete garments" (the denominator for
    average-consumption checks and Fixed/Ratio quantity caps) -- enforced
    in the serializer, not editable directly by the user."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="components")
    name = models.CharField(max_length=100)
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("product", "name")

    def __str__(self):
        return f"{self.product} / {self.name}"


# Common garment/apparel color names -> a representative hex. Anything not
# in here (or not matching a word within a compound name, e.g. "Navy Blue")
# falls back to a deterministic hash-derived color, so the same name always
# renders the same swatch even when it's not a recognized keyword.
COMMON_COLOR_HEX = {
    "red": "#E53935", "blue": "#1E88E5", "green": "#43A047", "yellow": "#FDD835",
    "black": "#111111", "white": "#FAFAFA", "grey": "#9E9E9E", "gray": "#9E9E9E",
    "navy": "#001F54", "navy blue": "#001F54", "maroon": "#800000", "pink": "#F48FB1",
    "purple": "#8E24AA", "orange": "#FB8C00", "brown": "#6D4C41", "beige": "#E8DCC8",
    "cream": "#FFF8E1", "off white": "#F5F1E8", "sky blue": "#87CEEB", "royal blue": "#4169E1",
    "olive": "#808000", "mustard": "#E1AD01", "teal": "#00897B", "turquoise": "#1ABC9C",
    "coral": "#FF7F50", "peach": "#FFDAB9", "lavender": "#B39DDB", "magenta": "#D81B60",
    "cyan": "#00BCD4", "gold": "#FFD700", "silver": "#C0C0C0", "charcoal": "#36454F",
    "khaki": "#C3B091", "tan": "#D2B48C", "rust": "#B7410E", "burgundy": "#800020",
    "wine": "#722F37", "mint": "#98FF98", "lime": "#C6FF00", "indigo": "#3F51B5",
    "violet": "#7C4DFF", "crimson": "#DC143C", "scarlet": "#FF2400", "ivory": "#FFFFF0",
    "chocolate": "#5C4033", "denim": "#1560BD", "baby pink": "#F4C2C2", "hot pink": "#FF69B4",
    "fuchsia": "#FF00FF", "salmon": "#FA8072", "mauve": "#E0B0FF", "rose": "#FF007F",
}


class Color(TimeStampedModel):
    name = models.CharField(max_length=100)
    hex_code = models.CharField(max_length=7, blank=True, default="", help_text="e.g. #1E3A8A")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("name", "hex_code")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.hex_code:
            self.hex_code = self._generate_hex()
        super().save(*args, **kwargs)

    def _generate_hex(self):
        key = (self.name or "").strip().lower()
        if key in COMMON_COLOR_HEX:
            return COMMON_COLOR_HEX[key]
        for word in reversed(key.split()):
            if word in COMMON_COLOR_HEX:
                return COMMON_COLOR_HEX[word]
        h = 0
        for ch in key or "color":
            h = (h * 31 + ord(ch)) & 0xFFFFFFFF
        r, g, b = colorsys.hls_to_rgb((h % 360) / 360, 0.5, 0.55)
        return "#{:02X}{:02X}{:02X}".format(int(r * 255), int(g * 255), int(b * 255))


class FabricType(TimeStampedModel):
    name = models.CharField(max_length=100)
    gsm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    composition = models.CharField(max_length=200, blank=True, help_text="e.g. 100% Cotton")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.gsm} GSM)" if self.gsm else self.name


class Accessory(TimeStampedModel):
    """Non-fabric purchasable item (zipper, button, thread, etc). One
    flexible model rather than per-type tables -- `size_spec` is a short
    free-text field whose label the frontend swaps per `accessory_type`
    (e.g. "Length" for zippers, "Size" for buttons, "Count" for thread)."""

    class AccessoryType(models.TextChoices):
        ZIPPER = "ZIPPER", "Zipper"
        BUTTON = "BUTTON", "Button"
        THREAD = "THREAD", "Thread"
        ELASTIC = "ELASTIC", "Elastic"
        LABEL = "LABEL", "Label"
        OTHER = "OTHER", "Other"

    class Unit(models.TextChoices):
        # No "Rolls": a roll is a physical package, not a measurement unit.
        PIECES = "PIECES", "Pieces"
        METERS = "METERS", "Meters"
        YARDS = "YARDS", "Yards"
        KILOGRAMS = "KILOGRAMS", "Kilograms"
        CONES = "CONES", "Cones"
        DOZEN = "DOZEN", "Dozen"

    accessory_type = models.CharField(max_length=20, choices=AccessoryType.choices)
    name = models.CharField(max_length=150)
    color = models.ForeignKey(Color, on_delete=models.SET_NULL, null=True, blank=True, default=None, related_name="accessories")
    size_spec = models.CharField(max_length=100, blank=True, default="", help_text="e.g. 20mm, 18L, 40/2")
    unit = models.CharField(max_length=20, choices=Unit.choices, default=Unit.PIECES)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("accessory_type", "name", "size_spec", "color")
        verbose_name_plural = "Accessories"

    def __str__(self):
        label = f"{self.get_accessory_type_display()} — {self.name}"
        return f"{label} ({self.size_spec})" if self.size_spec else label


# Real-world garment size order. Anything not recognized here (a custom
# size name) keeps whatever display_order it was given (default 0).
SIZE_RANK = {
    "XXS": 0, "2XS": 0,
    "XS": 10,
    "S": 20, "SMALL": 20,
    "M": 30, "MEDIUM": 30,
    "L": 40, "LARGE": 40,
    "XL": 50,
    "XXL": 60, "2XL": 60,
    "XXXL": 70, "3XL": 70,
    "XXXXL": 80, "4XL": 80,
    "XXXXXL": 90, "5XL": 90,
    "6XL": 100,
}


class Size(TimeStampedModel):
    name = models.CharField(max_length=20, unique=True, help_text="e.g. S, M, L, XL")
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["display_order"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        rank = self._auto_rank()
        if rank is not None:
            self.display_order = rank
        elif self.pk is None and not self.display_order:
            # Unrecognized custom size, no explicit order given -> append at
            # the end instead of defaulting to 0 (which would sort it first).
            current_max = Size.objects.aggregate(models.Max("display_order"))["display_order__max"] or 0
            self.display_order = current_max + 1
        super().save(*args, **kwargs)

    def _auto_rank(self):
        key = re.sub(r"[\s\-]", "", (self.name or "")).upper()
        if key in SIZE_RANK:
            return SIZE_RANK[key]
        if key.isdigit():
            return 1000 + int(key)
        return None


class Vendor(TimeStampedModel):
    """Supplier of fabric / raw materials."""

    class PaymentTerms(models.TextChoices):
        NET_15 = "NET_15", "Net 15"
        NET_30 = "NET_30", "Net 30"
        NET_45 = "NET_45", "Net 45"
        COD = "COD", "Cash on Delivery"
        ADVANCE = "ADVANCE", "Advance"

    company_name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    gst_number = models.CharField(max_length=50, blank=True)
    payment_terms = models.CharField(max_length=20, choices=PaymentTerms.choices, blank=True)
    bank_details = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.company_name
