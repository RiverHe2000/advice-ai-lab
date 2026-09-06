"""The product master: fictional platform and external products with codes, types and
administration fees. Shared by the corpus generator (what an SoA can recommend), the
validators (does a product name resolve?), the extractors (fuzzy canonicalisation) and the
reconciliation (matching recommendations to holdings)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from rapidfuzz import fuzz, process

from advicedoc.schema import ProductType

PLATFORM_NAME = "Northshore Wealth"
LICENSEE_NAME = "Northshore Financial Advice Pty Ltd"
LICENSEE_AFSL = "AFSL 512 907"


@dataclass(frozen=True, slots=True)
class Product:
    code: str
    name: str
    product_type: ProductType
    admin_fee_pct: Decimal
    on_platform: bool
    usi: str | None = None


PRODUCTS: tuple[Product, ...] = (
    Product("NW-SUP-001", "Northshore Wealth Super", "super", Decimal("0.30"), True, "NWS0001AU"),
    Product(
        "NW-PEN-001", "Northshore Wealth Pension", "pension", Decimal("0.30"), True, "NWS0002AU"
    ),
    Product("NW-IDPS-01", "Northshore Wealth Investment Account", "idps", Decimal("0.25"), True),
    Product(
        "NW-MP-CON", "Northshore Conservative Portfolio", "managed_portfolio", Decimal("0.45"), True
    ),
    Product(
        "NW-MP-BAL", "Northshore Balanced Portfolio", "managed_portfolio", Decimal("0.55"), True
    ),
    Product("NW-MP-GRO", "Northshore Growth Portfolio", "managed_portfolio", Decimal("0.60"), True),
    Product(
        "NW-MP-ACC", "Northshore Accelerator Portfolio", "managed_portfolio", Decimal("0.70"), True
    ),
    Product("NW-MP-INC", "Northshore Income Portfolio", "managed_portfolio", Decimal("0.50"), True),
    Product("NW-CASH-01", "Northshore Cash Account", "cash", Decimal("0.00"), True),
    Product("NW-INS-LIF", "Northshore Life Cover", "insurance", Decimal("0.00"), True),
    Product("NW-INS-IP", "Northshore Income Protection", "insurance", Decimal("0.00"), True),
    Product("NW-INS-TPD", "Northshore TPD Cover", "insurance", Decimal("0.00"), True),
    Product("EX-SUP-AUR", "Aurora Super Fund", "super", Decimal("0.85"), False, "AUR0001AU"),
    Product("EX-SUP-KES", "Kestrel Industry Super", "super", Decimal("0.70"), False, "KES0001AU"),
    Product(
        "EX-SUP-SCR", "Southern Cross Retirement Fund", "super", Decimal("0.95"), False, "SCR0001AU"
    ),
    Product("EX-SUP-HBL", "Harbourline Super", "super", Decimal("0.80"), False, "HBL0001AU"),
    Product(
        "EX-SUP-TAL", "Tallowood Employer Super Plan", "super", Decimal("1.10"), False, "TAL0001AU"
    ),
    Product(
        "EX-PEN-AUR", "Aurora Account-Based Pension", "pension", Decimal("0.90"), False, "AUR0002AU"
    ),
    Product("EX-IDPS-OS", "Osprey Wrap Investment", "idps", Decimal("0.65"), False),
    Product("EX-MP-BLUE", "Bluegum Diversified Fund", "managed_portfolio", Decimal("1.20"), False),
    Product("EX-INS-SEN", "Sentinel Life and TPD", "insurance", Decimal("0.00"), False),
    Product("EX-INS-BEA", "Beacon Income Protection", "insurance", Decimal("0.00"), False),
    Product("EX-CASH-FB", "Fernbank Term Deposit", "cash", Decimal("0.00"), False),
)


class ProductMaster:
    def __init__(self, products: tuple[Product, ...] = PRODUCTS) -> None:
        self._products = products
        self._by_name = {p.name: p for p in products}
        self._by_code = {p.code: p for p in products}
        self._names = [p.name for p in products]

    @property
    def products(self) -> tuple[Product, ...]:
        return self._products

    def names(self) -> list[str]:
        return list(self._names)

    def get(self, name: str) -> Product | None:
        return self._by_name.get(name)

    def by_code(self, code: str) -> Product | None:
        return self._by_code.get(code)

    def of_type(
        self, product_type: ProductType, *, on_platform: bool | None = None
    ) -> list[Product]:
        return [
            p
            for p in self._products
            if p.product_type == product_type
            and (on_platform is None or p.on_platform == on_platform)
        ]

    def match(self, name: str, *, threshold: float = 0.0) -> tuple[Product | None, float]:
        """Best fuzzy match of ``name`` against the master (score 0-100)."""
        if not name.strip():
            return None, 0.0
        matched, score, _ = process.extractOne(name.strip(), self._names, scorer=fuzz.ratio)
        if score < threshold:
            return None, float(score)
        return self._by_name[str(matched)], float(score)


DEFAULT_MASTER = ProductMaster()
