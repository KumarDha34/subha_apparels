"""
Wipe ALL business data and re-seed a rich, realistic, end-to-end factory
dataset so every dashboard shows multiple, connected, real-world records and
every scenario/condition is represented.

Walks the real sequence for each order:
    Master Data -> Merchandising (Order) -> Store (Purchase + Receive + Pay)
    -> Cutting (Cut + Bundle + Issue Accessories) -> Production (Receive +
    Assign bundle & accessories + Return + QC) -> Finishing (Operations + QC +
    Pack + Dispatch) -> Accounts (Income + Expenses + Operator payments).

Scenarios/conditions covered across ~14 orders spread over the last 8 weeks:
  * both FIXED_QUANTITY and RATIO_BASED order types
  * every pipeline stage: confirmed, cutting, production, finishing, dispatched,
    delivered, and a cancelled order
  * order-specific, bulk, and customer-supplied purchases
  * over-consumption cutting orders (approved override + one pending review)
  * operator shortages (pending review, approved, rejected) and QC defects
  * partial / full / overdue / unpaid supplier invoices
  * paid / partially-paid / pending operator income
  * low-stock fabric & accessory alerts
  * finishing rejects, packing, dispatch + delivery
  * unread notifications in the bell

Usage:
    python manage.py seed_factory_data          # wipe + reseed
    python manage.py seed_factory_data --keep    # reseed without wiping
"""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.users.models import User, Notification, ActivityLog, PasswordResetRequest
from apps.master_data.models import (
    Party, Product, ProductComponent, Color, Size, FabricType, Vendor, Accessory,
)
from apps.store.models import (
    FabricStock, StockTransaction, AccessoryStock, AccessoryStockTransaction, Unit, FinishedGoodsReceipt,
)
from apps.orders.models import Order, OrderItem, OrderItemColor, OrderItemColorSize
from apps.finance.models import (
    PurchaseOrder, PurchaseOrderItem, Invoice, PaymentRecord, IncomeRecord, ExpenseRecord, Quotation,
)
from apps.finance import services as finance_services
from apps.cutting.models import CuttingOrder, CuttingPiece, Bundle, Marker
from apps.operators.models import Operator, OperatorRate, BundleAssignment, OperatorIncome
from apps.operators.services import assignment_labor_cost, order_piece_rate
from apps.production.models import (
    BundleReceipt, ProductionQualityCheck, AccessoryIssue, BundleAccessoryIssue, OperatorAccessoryIssue, ProcessDispatch,
)
from apps.finishing.models import (
    FinishingReceipt, FinishingOperation, FinishingQualityCheck, Packing, Dispatch,
)

STAGE_RANK = {"confirmed": 1, "cutting": 2, "production": 3, "finishing": 4, "dispatched": 5}
D = lambda v: Decimal(str(v))


class Command(BaseCommand):
    help = "Wipe all business data and seed a rich, realistic end-to-end factory dataset."

    def add_arguments(self, parser):
        parser.add_argument("--keep", action="store_true", help="Do not wipe existing data first.")

    # ---------------------------------------------------------------- wipe
    def wipe(self):
        for model in [
            ActivityLog, PasswordResetRequest, OperatorAccessoryIssue, ProcessDispatch,
            Quotation, PaymentRecord, Invoice, PurchaseOrderItem, PurchaseOrder, IncomeRecord, ExpenseRecord,
            FinishedGoodsReceipt, Dispatch, Packing, FinishingQualityCheck, FinishingOperation, FinishingReceipt,
            ProductionQualityCheck, BundleReceipt, BundleAccessoryIssue, AccessoryIssue,
            OperatorIncome, BundleAssignment, OperatorRate, Operator,
            Bundle, CuttingPiece, CuttingOrder, Marker,
            OrderItemColorSize, OrderItemColor, OrderItem, Order,
            StockTransaction, AccessoryStockTransaction, FabricStock, AccessoryStock,
            ProductComponent, Accessory, Product, Color, Size, FabricType, Vendor, Party,
            Notification,
        ]:
            model.objects.all().delete()
        self.stdout.write(self.style.WARNING("Wiped all business data."))

    def user(self, email, role, name):
        u = User.objects.filter(email=email).first()
        if not u:
            first, _, last = name.partition(" ")
            u = User.objects.create_user(email=email, password="Passw0rd!123", role=role,
                                          first_name=first, last_name=last)
        return u

    # ------------------------------------------------------------- handle
    def handle(self, *args, **options):
        if not options["keep"]:
            self.wipe()
        today = timezone.localdate()

        admin = User.objects.filter(role="ADMIN").first() or self.user("admin@factory.com", "ADMIN", "Factory Admin")
        merch = self.user("merch@factory.com", "MERCHANDISE", "Mira Merchant")
        store = self.user("store@factory.com", "STORE_MANAGER", "Suraj Store")
        cutter = self.user("cutting@factory.com", "CUTTING_SUPERVISOR", "Chandra Cutter")
        prod = self.user("production@factory.com", "PRODUCTION_SUPERVISOR", "Prakash Production")
        finish = self.user("finishing@factory.com", "FINISHING_SUPERVISOR", "Fima Finishing")
        accounts = self.user("accounts@factory.com", "ACCOUNTS", "Anita Accounts")

        # ============================ MASTER DATA ============================
        parties = {
            "everest": Party.objects.create(name="Everest Apparels", contact_person="Nabin Shrestha", phone="9801000001", email="buy@everestapparels.com", address="Thamel, Kathmandu", code_prefix="EV"),
            "himalaya": Party.objects.create(name="Himalayan Threads", contact_person="Puja Karki", phone="9801000002", email="orders@himalayanthreads.com", address="Lakeside, Pokhara", code_prefix="HT"),
            "ktm": Party.objects.create(name="Kathmandu Fashion House", contact_person="Rajesh Maharjan", phone="9801000003", email="info@ktmfashion.com", address="Pulchowk, Lalitpur", code_prefix="KF"),
            "annapurna": Party.objects.create(name="Annapurna Garments", contact_person="Sabina Gurung", phone="9801000004", email="sales@annapurnagarments.com", address="Butwal", code_prefix="AN"),
        }
        vendors = {
            "sunrise": Vendor.objects.create(company_name="Sunrise Textiles", contact_person="Bikash Rai", phone="9802000001", payment_terms="NET_30", gst_number="GST-SUN-01"),
            "gorkha": Vendor.objects.create(company_name="Gorkha Fabric Mills", contact_person="Deepak Thapa", phone="9802000002", payment_terms="NET_15", gst_number="GST-GOR-02"),
            "terai": Vendor.objects.create(company_name="Terai Trims & Accessories", contact_person="Anil Yadav", phone="9802000003", payment_terms="COD", gst_number="GST-TER-03"),
        }
        fabrics = {
            "jersey": FabricType.objects.create(name="Single Jersey", gsm=D("180"), composition="100% Cotton"),
            "fleece": FabricType.objects.create(name="Terry Fleece", gsm=D("320"), composition="80% Cotton 20% Poly"),
            "twill": FabricType.objects.create(name="Cotton Twill", gsm=D("240"), composition="98% Cotton 2% Spandex"),
            "pique": FabricType.objects.create(name="Pique Knit", gsm=D("210"), composition="100% Cotton"),
            "rib": FabricType.objects.create(name="Rib Knit", gsm=D("220"), composition="95% Cotton 5% Lycra"),
        }
        colors = {n: Color.objects.create(name=n) for n in
                  ["Navy Blue", "White", "Black", "Maroon", "Olive", "Sky Blue", "Grey", "Mustard"]}
        sizes = {n: Size.objects.create(name=n) for n in ["XS", "S", "M", "L", "XL", "XXL"]}
        def _chart(rows):
            # rows = [(param, {S:.., M:.., L:..}), ...]
            return [{"param": p, "sizes": s} for p, s in rows]

        def _img(label):
            return f"https://placehold.co/600x600/E66239/ffffff?text={label}"

        products = {
            "tshirt": Product.objects.create(
                name="Classic Crew T-Shirt", description="180 GSM cotton crew-neck tee", image_url=_img("Crew+Tee"),
                measurement_chart=_chart([("Chest (in)", {"S": "38", "M": "40", "L": "42", "XL": "44"}),
                                          ("Body Length (in)", {"S": "27", "M": "28", "L": "29", "XL": "30"}),
                                          ("Sleeve (in)", {"S": "8", "M": "8.5", "L": "9", "XL": "9.5"})])),
            "hoodie": Product.objects.create(
                name="Pullover Hoodie", description="320 GSM fleece pullover hoodie", image_url=_img("Hoodie"),
                measurement_chart=_chart([("Chest (in)", {"S": "42", "M": "44", "L": "46", "XL": "48"}),
                                          ("Body Length (in)", {"S": "26", "M": "27", "L": "28", "XL": "29"}),
                                          ("Sleeve (in)", {"S": "24", "M": "24.5", "L": "25", "XL": "25.5"})])),
            "cargo": Product.objects.create(
                name="Cargo Pant", description="Cotton twill 6-pocket cargo", image_url=_img("Cargo+Pant"),
                measurement_chart=_chart([("Waist (in)", {"S": "30", "M": "32", "L": "34", "XL": "36"}),
                                          ("Inseam (in)", {"S": "30", "M": "31", "L": "31", "XL": "32"}),
                                          ("Thigh (in)", {"S": "23", "M": "24", "L": "25", "XL": "26"})])),
            "polo": Product.objects.create(
                name="Polo Shirt", description="Pique knit polo with placket", image_url=_img("Polo"),
                measurement_chart=_chart([("Chest (in)", {"S": "39", "M": "41", "L": "43", "XL": "45"}),
                                          ("Body Length (in)", {"S": "27.5", "M": "28.5", "L": "29.5", "XL": "30.5"})])),
            "kidtee": Product.objects.create(
                name="Kids Round-Neck Tee", description="Soft cotton kids tee", image_url=_img("Kids+Tee"),
                measurement_chart=_chart([("Chest (in)", {"XS": "26", "S": "28", "M": "30", "L": "32"}),
                                          ("Body Length (in)", {"XS": "18", "S": "20", "M": "22", "L": "24"})])),
            "legging": Product.objects.create(
                name="Ladies Legging", description="Rib-knit stretch legging", image_url=_img("Legging"),
                measurement_chart=_chart([("Waist (in)", {"S": "24", "M": "26", "L": "28", "XL": "30"}),
                                          ("Length (in)", {"S": "36", "M": "37", "L": "38", "XL": "38"})])),
        }
        components = []  # product components no longer used

        accessories = {
            "label": Accessory.objects.create(accessory_type="LABEL", name="Woven Neck Label", size_spec="Standard", unit="PIECES"),
            "care": Accessory.objects.create(accessory_type="LABEL", name="Care Label", size_spec="Standard", unit="PIECES"),
            "thread": Accessory.objects.create(accessory_type="THREAD", name="Sewing Thread", size_spec="40/2", unit="CONES"),
            "polybag": Accessory.objects.create(accessory_type="OTHER", name="Poly Bag", size_spec="12x16", unit="PIECES"),
            "drawcord": Accessory.objects.create(accessory_type="OTHER", name="Drawcord", size_spec="5mm", unit="METERS"),
            "zipper": Accessory.objects.create(accessory_type="ZIPPER", name="Metal Zipper", size_spec="18cm", unit="PIECES"),
            "button": Accessory.objects.create(accessory_type="BUTTON", name="Plastic Button", size_spec="18L", unit="PIECES"),
            "elastic": Accessory.objects.create(accessory_type="ELASTIC", name="Elastic Band", size_spec="25mm", unit="METERS"),
        }
        markers = {}  # markers replaced by layer-based cutting

        operators = []
        op_user = User.objects.filter(role="OPERATOR").first()
        for i, (nm, skill) in enumerate([
            ("Ram Bahadur", "EXPERT"), ("Sita Sharma", "EXPERT"), ("Gita Thapa", "INTERMEDIATE"),
            ("Hari Gurung", "INTERMEDIATE"), ("Bimala Rai", "BEGINNER"), ("Krishna Magar", "EXPERT"),
            ("Sunita Lama", "INTERMEDIATE"), ("Dipak Shrestha", "BEGINNER"),
        ]):
            operators.append(Operator.objects.create(
                operator_type="INDIVIDUAL", name=nm, skill_level=skill, is_active=(i != 7),
                joined_date=today - timedelta(days=200 + i * 12),
                user_account=op_user if i == 0 else None,
            ))

        # ---- Bulk accessory purchase (received + paid) so Store has stock ----
        self._bulk_accessory_purchase(vendors["terai"], store, accounts, today, accessories)
        # ---- Bulk fabric purchase (partially received, sets up a low-stock item) ----
        self._bulk_fabric_purchase(vendors["gorkha"], store, accounts, today, fabrics, colors)

        # ============================ ORDERS FLOW ============================
        F = "FIXED_QUANTITY"
        R = "RATIO_BASED"
        scenarios = [
            # ===================== DISPATCHED & DELIVERED =====================
            # 1) Clean FIXED order, vendor fabric, full payment, delivered.
            dict(key="FIX", party="everest", product="tshirt", fabric="jersey", vendor="sunrise", type=F,
                 stage="dispatched", offset=60, delivered=True, avg="1.60", rate="45", fabric_rate="210",
                 sell="640", pay="full", inner=True, fusing=True,
                 colors=[("White", {"S": 30, "M": 40, "L": 20}), ("Black", {"S": 20, "M": 25, "L": 15})]),
            # 2) Clean RATIO order, CUSTOMER-SUPPLIED multi-roll, half-roll White, delivered.
            dict(key="RAT", party="ktm", product="polo", fabric="pique", vendor="sunrise", type=R,
                 stage="dispatched", offset=45, delivered=True, avg="1.80", rate="60", fabric_rate="0",
                 sell="900", pay="full", fusing=True, supply="customer", sets=15,
                 cutting_instruction="Customer-supplied rolls: use only HALF of each roll for the White colour, return the rest to Store.",
                 colors=[("White", {"S": 4, "M": 4, "L": 1}), ("Black", {"S": 2, "M": 3, "L": 2})]),
            # 3) Dispatched but only PARTIALLY paid (receivable outstanding).
            dict(key="D3", party="himalaya", product="hoodie", fabric="fleece", vendor="gorkha", type=F,
                 stage="dispatched", offset=52, avg="2.40", rate="120", fabric_rate="330", sell="1450", pay="partial", inner=True, resting=True,
                 colors=[("Maroon", {"M": 40, "L": 60, "XL": 40})]),
            # 4) Dispatched with an OVERDUE supplier bill.
            dict(key="D4", party="annapurna", product="kidtee", fabric="jersey", vendor="sunrise", type=F,
                 stage="dispatched", offset=48, avg="0.90", rate="30", fabric_rate="205", sell="360", pay="overdue",
                 colors=[("Sky Blue", {"XS": 80, "S": 120, "M": 100})]),
            # ========================== FINISHING ============================
            dict(key="F1", party="annapurna", product="cargo", fabric="twill", vendor="gorkha", type=F,
                 stage="finishing", offset=22, avg="1.90", rate="98", fabric_rate="285", sell="1200", pay="half", fusing=True,
                 colors=[("Olive", {"M": 70, "L": 90, "XL": 60})]),
            dict(key="F2", party="everest", product="legging", fabric="rib", vendor="gorkha", type=R,
                 stage="finishing", offset=20, avg="1.30", rate="42", fabric_rate="260", sell="560", pay="overdue", sets=120,
                 colors=[("Grey", {"S": 2, "M": 2, "L": 1})]),
            # ================ PRODUCTION (operator shortage states) ===========
            dict(key="P1", party="ktm", product="tshirt", fabric="jersey", vendor="sunrise", type=F,
                 stage="production", offset=15, avg="1.60", rate="46", fabric_rate="215", sell="620", pay="half", shortage="pending",
                 colors=[("Navy Blue", {"S": 50, "M": 100, "L": 50})]),
            dict(key="P2", party="himalaya", product="kidtee", fabric="jersey", vendor="sunrise", type=F,
                 stage="production", offset=14, avg="0.90", rate="30", fabric_rate="205", sell="360", pay="half", shortage="approved",
                 colors=[("Mustard", {"XS": 70, "S": 100, "M": 90})]),
            dict(key="P3", party="annapurna", product="cargo", fabric="twill", vendor="gorkha", type=F,
                 stage="production", offset=13, avg="1.90", rate="98", fabric_rate="285", sell="1200", pay="none", fusing=True, shortage="rejected",
                 colors=[("Grey", {"M": 70, "L": 90})]),
            # ============ CUTTING (over-consumption + customer-supplied) ======
            dict(key="C1", party="everest", product="polo", fabric="pique", vendor="sunrise", type=F,
                 stage="cutting", offset=9, avg="1.80", rate="62", fabric_rate="245", sell="840", pay="none", overconsume="approved",
                 colors=[("Maroon", {"S": 40, "M": 80, "L": 40})]),
            dict(key="C2", party="himalaya", product="kidtee", fabric="jersey", vendor="sunrise", type=F,
                 stage="cutting", offset=8, avg="0.90", rate="32", fabric_rate="205", sell="380", pay="none", overconsume="pending",
                 colors=[("Mustard", {"XS": 70, "S": 100, "M": 90})]),
            dict(key="C3", party="ktm", product="tshirt", fabric="jersey", vendor="sunrise", type=F,
                 stage="cutting", offset=6, avg="1.60", rate="46", fabric_rate="0", sell="620", pay="none", supply="customer",
                 cutting_instruction="Customer-supplied: use HALF of each White roll, return the rest.",
                 colors=[("White", {"S": 50, "M": 100, "L": 50})]),
            # ===================== CONFIRMED (awaiting) =======================
            dict(key="N1", party="everest", product="legging", fabric="rib", vendor="gorkha", type=R,
                 stage="confirmed", offset=4, avg="1.30", rate="44", fabric_rate="260", sell="580", pay="none", sets=90,
                 colors=[("Olive", {"S": 2, "M": 2, "L": 1})]),
            dict(key="N2", party="annapurna", product="tshirt", fabric="jersey", vendor="sunrise", type=F,
                 stage="confirmed", offset=3, avg="1.60", rate="45", fabric_rate="210", sell="620", pay="none",
                 colors=[("Navy Blue", {"S": 40, "M": 80, "L": 80})]),
            # ========================== CANCELLED ============================
            dict(key="X1", party="ktm", product="polo", fabric="pique", vendor="sunrise", type=F,
                 stage="confirmed", offset=25, cancelled=True, avg="1.80", rate="60", fabric_rate="240", sell="800", pay="none",
                 colors=[("Black", {"M": 60, "L": 60})]),
        ]

        ctx = dict(parties=parties, vendors=vendors, fabrics=fabrics, colors=colors, sizes=sizes,
                   products=products, components=components, accessories=accessories, markers=markers,
                   operators=operators, merch=merch, store=store, cutter=cutter, prod=prod,
                   finish=finish, accounts=accounts, admin=admin, today=today)
        op_cycle = [0]
        for sc in scenarios:
            self.build_order(sc, ctx, op_cycle)

        # ---- A spread of quotations across every status (Accounts dashboard) ----
        quote_specs = [
            ("everest", "tshirt", 500, "48", 20, "DRAFT"),
            ("himalaya", "hoodie", 300, "135", 15, "SENT"),
            ("ktm", "polo", 800, "62", 25, "ACCEPTED"),
            ("annapurna", "cargo", 250, "100", 10, "REJECTED"),
            ("everest", "kidtee", 1000, "34", -5, "SENT"),   # already past valid_till -> auto-EXPIRED on view
        ]
        for pkey, prodkey, qty, rate, days, st in quote_specs:
            Quotation.objects.create(
                party=parties[pkey], product=products[prodkey], quantity=qty, rate_per_piece=D(rate),
                valid_till=today + timedelta(days=days), status=st, created_by=accounts,
                terms="50% advance, balance before dispatch. Delivery in 30 days.")

        # ---- Operator income statements (paid on the order's per-piece rate) ----
        for idx, op in enumerate(operators):
            done = op.assignments.filter(status__in=["COMPLETED", "QUALITY_CHECKED"], returned_quantity__isnull=False)
            if not done.exists():
                continue
            total = sum((assignment_labor_cost(a) for a in done), Decimal("0"))
            pieces = sum((a.returned_quantity or 0) for a in done)
            rate = next((order_piece_rate(a) for a in done if order_piece_rate(a)), Decimal("0"))
            inc = OperatorIncome.objects.create(
                operator=op, period_start=today - timedelta(days=35), period_end=today,
                bundles_completed=done.count(), pieces_completed=pieces, rate_applied=rate, total_income=total,
            )
            # Mix of paid / partially-paid / pending statements.
            if idx % 3 == 0:
                inc.paid_amount = total; inc.payment_status = "PAID"; inc.payment_date = today
            elif idx % 3 == 1:
                inc.paid_amount = (total / 2).quantize(D("0.01")); inc.payment_status = "PARTIALLY_PAID"; inc.payment_date = today
            inc.save(update_fields=["paid_amount", "payment_status", "payment_date"])

        # ---- One process shortfall awaiting Admin approval (Approvals panel) ----
        from apps.production.models import ProcessDispatch as _PD
        _pend = _PD.objects.filter(department="WASHING", status="RECEIVED").order_by("id").first()
        if _pend:
            _pend.quantity_received = max(_pend.quantity_sent - 8, 0)
            _pend.loss_reason = "8 pieces damaged during washing (colour bleed) — awaiting Admin decision."
            _pend.loss_status = _PD.LossStatus.PENDING
            _pend.status = _PD.Status.PENDING_APPROVAL
            _pend.save(update_fields=["quantity_received", "loss_reason", "loss_status", "status"])

        # ---- Overhead expenses across the last several weeks ----
        for cat, amt, days, note in [
            ("RENT", 45000, 30, "Factory rent — this month"), ("RENT", 45000, 60, "Factory rent — last month"),
            ("UTILITIES", 18500, 20, "Electricity & water"), ("UTILITIES", 17200, 50, "Electricity & water"),
            ("SALARY", 62000, 30, "Supervisory staff salary"), ("MAINTENANCE", 7500, 15, "Sewing machine servicing"),
            ("OTHER", 4200, 8, "Office supplies & courier"),
        ]:
            ExpenseRecord.objects.create(category=cat, amount=D(amt), expense_date=today - timedelta(days=days),
                                         remarks=note, recorded_by=accounts)

        # ---- Nudge a few fabric stocks below reorder (Store + KPI alerts) ----
        for st in FabricStock.objects.order_by("id")[:3]:
            st.reorder_level = st.available_quantity + D("60"); st.save(update_fields=["reorder_level"])
        for ast in AccessoryStock.objects.order_by("id")[:2]:
            ast.reorder_level = ast.available_quantity + D("500"); ast.save(update_fields=["reorder_level"])

        # ---- Store issues accessories directly to operators (with usage) ----
        from apps.store.models import AccessoryStockTransaction as AST
        thread = AccessoryStock.objects.filter(accessory=accessories["thread"]).first()
        button = AccessoryStock.objects.filter(accessory=accessories["button"]).first()
        for idx, op in enumerate(operators):
            done = op.assignments.filter(status__in=["COMPLETED", "QUALITY_CHECKED"], returned_quantity__isnull=False)
            pieces = sum((a.returned_quantity or 0) for a in done)
            if not pieces:
                continue
            for stock, per_pc, unit_issue in [(thread, D("0.02"), D("12")), (button, D("6"), None)]:
                if not stock:
                    continue
                issued = (unit_issue if unit_issue is not None else (D(pieces) * per_pc * D("1.2")).quantize(D("1")))
                if stock.available_quantity < issued:
                    continue
                used = (D(pieces) * per_pc).quantize(D("0.01"))
                if used > issued:
                    used = issued
                oai = OperatorAccessoryIssue.objects.create(
                    operator=op, accessory_stock=stock, issued_quantity=issued, used_quantity=used,
                    pieces_covered=int(pieces), issued_date=today - timedelta(days=8),
                    issued_by=store, remarks="Issued for stitching")
                AST.objects.create(accessory_stock=stock, transaction_type="ISSUE", quantity=issued,
                                   reference=oai.issue_number, remarks=f"Direct to operator {op.name}", created_by=store)
                stock.available_quantity -= issued
                stock.save(update_fields=["available_quantity"])

        # ---- Activity log (who did what, spread across recent days) ----
        self._seed_activity(ctx)

        # ---- A couple of pending password-reset requests (Users page) ----
        PasswordResetRequest.objects.create(email=store.email, user=store)
        PasswordResetRequest.objects.create(email=finish.email, user=finish)

        # ---- Notifications (bell) ----
        for u, msg, link in [
            (admin, "3 bundle shortage reasons are awaiting your review.", "/production/bundle-allocation/"),
            (admin, "Cutting order flagged over-consumption — approval needed.", "/cutting/record-cut/"),
            (prod, "New bundles received from Cutting are ready to assign.", "/production/bundle-allocation/"),
            (finish, "Order EV — pieces sent from Production for finishing.", "/finishing/operations/"),
            (accounts, "A supplier invoice is overdue for payment.", "/accounts/payments/"),
        ]:
            Notification.objects.create(recipient=u, message=msg, link=link, is_read=False)

        self.print_summary()

    # ------------------------------------------------------- bulk purchases
    def _bulk_accessory_purchase(self, vendor, store, accounts, today, accessories):
        po = PurchaseOrder.objects.create(vendor=vendor, po_type="BULK", po_date=today - timedelta(days=42), created_by=store)
        for acc, qty, rate in [
            (accessories["label"], 30000, "1.50"), (accessories["care"], 30000, "0.80"),
            (accessories["thread"], 1600, "120"), (accessories["polybag"], 30000, "2.00"),
            (accessories["drawcord"], 4000, "6.00"), (accessories["zipper"], 3000, "18"),
            (accessories["button"], 12000, "1.20"), (accessories["elastic"], 2500, "9"),
        ]:
            poi = PurchaseOrderItem.objects.create(purchase_order=po, material_type="ACCESSORY", accessory=acc, quantity=qty, unit=acc.unit)
            finance_services.apply_receipt(poi, D(qty), D(rate), po, store)
        finance_services.recompute_receipt_status(po)
        finance_services.sync_invoice(po)
        inv = po.invoices.first()
        finance_services.record_payment(inv, inv.total_amount, "BANK_TRANSFER", today - timedelta(days=38), "Bulk accessories settled", accounts)

    def _order_specific_accessories(self, order, vendor, ctx, order_date, sc, total_pieces):
        """A small order-specific accessory PO: thread plus the product's main
        closure (zipper/button/drawcord/elastic), bought for this order so the
        Stock page can auto-suggest the order when issuing them."""
        acc = ctx["accessories"]
        picks = [(acc["thread"], max(2, total_pieces // 400), "120")]
        closure = {"cargo": ("zipper", "18"), "hoodie": ("drawcord", "6"),
                   "polo": ("button", "1.2"), "legging": ("elastic", "9")}.get(sc["product"])
        if closure:
            picks.append((acc[closure[0]], total_pieces, closure[1]))
        po = PurchaseOrder.objects.create(vendor=vendor, related_order=order, po_type="ORDER_SPECIFIC",
                                          po_date=order_date + timedelta(days=1), created_by=ctx["store"])
        for a, qty, rate in picks:
            poi = PurchaseOrderItem.objects.create(purchase_order=po, material_type="ACCESSORY", accessory=a, quantity=D(qty), unit=a.unit)
            finance_services.apply_receipt(poi, D(qty), D(rate), po, ctx["store"])
        finance_services.recompute_receipt_status(po)
        finance_services.sync_invoice(po)

    def _bulk_fabric_purchase(self, vendor, store, accounts, today, fabrics, colors):
        """A partially-received bulk fabric PO -> general stock + a PARTIALLY_RECEIVED PO."""
        po = PurchaseOrder.objects.create(vendor=vendor, po_type="BULK", po_date=today - timedelta(days=25), created_by=store)
        i1 = PurchaseOrderItem.objects.create(purchase_order=po, material_type="FABRIC", fabric_type=fabrics["jersey"], color=colors["Grey"], quantity=D("800"), unit=Unit.METERS)
        i2 = PurchaseOrderItem.objects.create(purchase_order=po, material_type="FABRIC", fabric_type=fabrics["pique"], color=colors["Sky Blue"], quantity=D("600"), unit=Unit.METERS)
        finance_services.apply_receipt(i1, D("500"), D("205"), po, store)   # partial
        finance_services.recompute_receipt_status(po)                        # -> PARTIALLY_RECEIVED
        finance_services.sync_invoice(po)
        inv = po.invoices.first()
        finance_services.record_payment(inv, (inv.total_amount / 2).quantize(D("0.01")), "CHEQUE", today - timedelta(days=18), "50% advance on bulk fabric", accounts)

    # ---------------------------------------------------- one order, end-to-end
    def build_order(self, sc, ctx, op_cycle):
        today = ctx["today"]
        order_date = today - timedelta(days=sc["offset"])
        stage = STAGE_RANK[sc["stage"]]
        is_ratio = sc["type"] == "RATIO_BASED"
        product = ctx["products"][sc["product"]]
        fabric = ctx["fabrics"][sc["fabric"]]
        vendor = ctx["vendors"][sc["vendor"]]
        party = ctx["parties"][sc["party"]]
        avg = D(sc["avg"])
        has_components = bool(sc.get("components"))
        prod_components = ctx["components"] if has_components else []

        # pieces per colour
        def color_pieces_map():
            m = {}
            for cname, sizeqty in sc["colors"]:
                m[cname] = (sum(sizeqty.values()) * sc["sets"]) if is_ratio else sum(sizeqty.values())
            return m
        color_pieces = color_pieces_map()
        total_pieces = sum(color_pieces.values())
        sell_total = D(total_pieces) * D(sc["sell"])

        # --- 1. MERCHANDISING: create + confirm ---
        order = Order(party=party, order_date=order_date, order_type=sc["type"], is_repeat=sc.get("repeat", False),
                      total_order_amount=sell_total, created_by=ctx["merch"], remarks=f"Seeded order {sc['key']}",
                      cutting_instruction=sc.get("cutting_instruction", ""))
        order.save()
        item = OrderItem.objects.create(order=order, product=product, fabric_type=fabric, approved_average=avg,
                                        price_per_piece=D(sc["rate"]), inner_required=sc.get("inner", False),
                                        fusing_required=sc.get("fusing", False), resting_needed=sc.get("resting", False))
        # Per-colour "use half roll": demo it on the first colour whenever the
        # order carries a half-roll cutting instruction.
        half_colors = {sc["colors"][0][0]} if "half" in (sc.get("cutting_instruction", "") or "").lower() else set()
        color_oic = {}
        for cname, sizeqty in sc["colors"]:
            oic = OrderItemColor.objects.create(order_item=item, color=ctx["colors"][cname], half_roll=(cname in half_colors))
            color_oic[cname] = oic
            for sname, val in sizeqty.items():
                OrderItemColorSize.objects.create(
                    order_item_color=oic, size=ctx["sizes"][sname],
                    quantity=(None if is_ratio else val), ratio_part=(val if is_ratio else None))
        order.advance_status(Order.Status.CONFIRMED)

        if sc.get("cancelled"):
            order.status = Order.Status.CANCELLED
            order.save(update_fields=["status"])
            return
        if stage < STAGE_RANK["cutting"]:
            self._advance_income(order, ctx, dispatched=False)
            return

        # --- 2. STORE: purchase fabric, receive, pay (or customer-supplied) ---
        customer_supplied = sc.get("supply") == "customer"
        color_stock = {}
        po = PurchaseOrder.objects.create(
            vendor=(None if customer_supplied else vendor),
            party=(party if customer_supplied else None),
            related_order=order, po_type=("CUSTOMER_SUPPLIED" if customer_supplied else "ORDER_SPECIFIC"),
            po_date=order_date + timedelta(days=1), created_by=ctx["store"])
        for cname, pcs in color_pieces.items():
            fabric_qty = (D(pcs) * avg * D("1.06")).quantize(D("0.01"))
            # Customer-supplied fabric arrives as several physical rolls (~25 m
            # each) -> multiple stock rolls the order then selects, like the
            # real-world flow; vendor fabric is one running-balance row.
            rolls = min(8, max(2, int(fabric_qty // 25))) if customer_supplied else 1
            PurchaseOrderItem.objects.create(purchase_order=po, material_type="FABRIC", fabric_type=fabric,
                                             color=ctx["colors"][cname], quantity=fabric_qty, unit=Unit.METERS, no_of_rolls=rolls)
        if customer_supplied:
            # Customers often supply their own accessories too (thread, zippers,
            # labels) -- received straight to stock, tagged to that customer.
            for acc_key, aqty in [("thread", max(2, total_pieces // 400)), ("zipper", total_pieces), ("label", total_pieces)]:
                acc = ctx["accessories"].get(acc_key)
                if acc:
                    PurchaseOrderItem.objects.create(purchase_order=po, material_type="ACCESSORY",
                                                     accessory=acc, quantity=D(aqty), unit=acc.unit)
            finance_services.receive_customer_supplied(po, ctx["store"])
        else:
            for poi in po.items.all():
                finance_services.apply_receipt(poi, poi.quantity, D(sc["fabric_rate"]), po, ctx["store"])
            finance_services.recompute_receipt_status(po)
            finance_services.sync_invoice(po)
            inv = po.invoices.first()
            inv.due_date = order_date + timedelta(days=30)
            inv.save(update_fields=["due_date"])
            self._pay_supplier(inv, sc.get("pay", "none"), order_date, today, ctx["accounts"])
            # Some accessories are bought specifically for THIS order -- the
            # Stock page auto-links them to it when issuing to an operator.
            self._order_specific_accessories(order, vendor, ctx, order_date, sc, total_pieces)
        for cname in color_pieces:
            color_stock[cname] = FabricStock.objects.filter(fabric_type=fabric, color=ctx["colors"][cname]).order_by("-id").first()
        # Associate rolls with the order's colours (Merchandising "selects the
        # rolls"). Customer-supplied orders link ALL of their own received
        # rolls (identified by this PO's number); general/ratio orders link the
        # shared stock row.
        for cname, oic in color_oic.items():
            if customer_supplied:
                own = FabricStock.objects.filter(fabric_type=fabric, color=ctx["colors"][cname],
                                                 roll_number__startswith=po.po_number)
                oic.rolls.add(*own)
            elif is_ratio and color_stock.get(cname):
                oic.rolls.add(color_stock[cname])

        order.advance_status(Order.Status.IN_CUTTING)

        # --- 3. CUTTING: cut, bundle ---
        bundles = []
        for ci, (cname, sizeqty) in enumerate(sc["colors"]):
            stock = color_stock[cname]
            pcs = color_pieces[cname]
            overc = sc.get("overconsume") if ci == 0 else None
            # Plain cutting-stage orders are left RECEIVED (fabric in, not cut)
            # so the cutting master can do the new layer-based cut in the UI.
            do_cut = stage > STAGE_RANK["cutting"] or overc
            if do_cut:
                actual_avg = (avg * D("1.18")) if overc else avg
                used = (D(pcs) * actual_avg).quantize(D("0.01"))
                wastage = (used * D("0.04")).quantize(D("0.01"))
                issue_qty = (used + wastage).quantize(D("0.01"))
            else:
                actual_avg = avg
                used = D("0"); wastage = D("0")
                issue_qty = (D(pcs) * avg * D("1.05")).quantize(D("0.01"))
            co = CuttingOrder.objects.create(
                order=order, order_item=item, fabric_issued=stock, fabric_issued_quantity=issue_qty,
                fabric_used_quantity=used, wastage_quantity=wastage, total_pieces_cut=(pcs if do_cut else None),
                actual_average=(actual_avg.quantize(D("0.001")) if do_cut else None),
                average_status=("DONT_CUT" if overc else ("CUT" if do_cut else "PENDING")),
                average_override_approved=(overc == "approved"),
                average_override_by=(ctx["admin"] if overc == "approved" else None),
                average_override_at=(timezone.now() if overc == "approved" else None),
                average_override_remarks=("Approved — fabric relaxation accepted for this lot." if overc == "approved" else ""),
                status=("CUTTING" if overc == "pending" else ("COMPLETED" if do_cut else "RECEIVED")),
                received_at=(None if do_cut else timezone.now()), received_by=(None if do_cut else ctx["cutter"]),
                marker=None,
                ratio_sets_cut=(sc["sets"] if (is_ratio and do_cut) else None),
                cutting_date=order_date + timedelta(days=3), supervisor=ctx["cutter"])
            StockTransaction.objects.create(fabric_stock=stock, transaction_type="ISSUE", quantity=issue_qty,
                                            reference=co.cutting_number, remarks=f"Issued to {co.cutting_number}", created_by=ctx["store"])
            stock.available_quantity -= issue_qty
            stock.save(update_fields=["available_quantity"])

            if not do_cut:
                continue  # left at RECEIVED for the UI layer flow — no pieces/bundles yet

            # Cut pieces (per component when the product tracks them).
            for sname, val in sizeqty.items():
                qty = (val * sc["sets"]) if is_ratio else val
                if prod_components:
                    for comp in prod_components:
                        CuttingPiece.objects.create(cutting_order=co, color=ctx["colors"][cname], size=ctx["sizes"][sname], component=comp, quantity=qty)
                else:
                    CuttingPiece.objects.create(cutting_order=co, color=ctx["colors"][cname], size=ctx["sizes"][sname], quantity=qty)
                # A pending over-consumption order is blocked -> no bundles yet.
                if overc == "pending":
                    continue
                remaining = qty
                while remaining > 0:
                    bq = min(60, remaining)
                    bundles.append(Bundle.objects.create(cutting_order=co, color=ctx["colors"][cname], size=ctx["sizes"][sname], quantity=bq, status="CREATED"))
                    remaining -= bq

        if stage < STAGE_RANK["production"]:
            self._advance_income(order, ctx, dispatched=False)
            return

        # --- 4. PRODUCTION: accessory issue (from Cutting), receive, assign+accessory, return, QC ---
        order.advance_status(Order.Status.IN_PRODUCTION)
        order_accessory_issue = self._cutting_issues_accessory(order, order_date, total_pieces, ctx)

        accepted_total = 0
        for idx, b in enumerate(bundles):
            b.sent_to_production_at = timezone.now(); b.status = "RECEIVED"
            b.save(update_fields=["sent_to_production_at", "status"])
            BundleReceipt.objects.create(bundle=b, received_by=ctx["prod"])
            op = ctx["operators"][op_cycle[0] % len(ctx["operators"])]
            op_cycle[0] += 1

            issued = b.quantity
            returned, defects, defect_reason = issued, 0, ""
            shortage_status, shortage_reason = "NOT_APPLICABLE", ""
            reviewed_by = reviewed_at = None
            if idx % 5 == 4:
                defects = 2; defect_reason = "Loose stitching found on collar"
            # Shortage behaviour depends on the scenario flag.
            if sc.get("shortage") and idx % 4 == 3:
                returned = max(issued - 4, 0)
                shortage_reason = "4 pieces damaged during handling"
                if sc["shortage"] == "pending":
                    shortage_status = "PENDING_REVIEW"
                elif sc["shortage"] == "rejected":
                    shortage_status = "REJECTED"; reviewed_by = ctx["admin"]; reviewed_at = timezone.now()
                else:
                    shortage_status = "APPROVED"; reviewed_by = ctx["admin"]; reviewed_at = timezone.now()

            # Pending-review shortages are not yet finalized/QC'd.
            is_pending = shortage_status == "PENDING_REVIEW"
            status = "RETURNED" if is_pending else "QUALITY_CHECKED"
            completion = None if is_pending else min(order_date + timedelta(days=6 + idx % 4), today)
            BundleAssignment.objects.create(
                bundle=b, operator=op, issued_quantity=issued,
                returned_quantity=(returned if (returned != issued or not is_pending) else returned),
                defects=defects, defect_reason=defect_reason,
                quality_check_passed=(None if is_pending else True), status=status, completion_date=completion,
                shortage_reason=shortage_reason, shortage_reason_status=shortage_status,
                shortage_reviewed_by=reviewed_by, shortage_reviewed_at=reviewed_at, assigned_by=ctx["prod"])
            b.status = "RECEIVED" if is_pending else "QUALITY_CHECKED"
            b.save(update_fields=["status"])
            if not is_pending:
                accepted_total += returned

            if order_accessory_issue:
                BundleAccessoryIssue.objects.create(bundle=b, accessory_issue=order_accessory_issue, operator=op,
                                                    issued_quantity=b.quantity, issued_by=ctx["prod"])

        if stage < STAGE_RANK["finishing"] or accepted_total == 0:
            self._advance_income(order, ctx, dispatched=False)
            return

        # --- 5. FINISHING: receive, operations, QC, pack ---
        order.advance_status(Order.Status.IN_FINISHING)
        FinishingReceipt.objects.create(order=order, quantity_sent=accepted_total, sent_by=ctx["prod"])

        # Production sends pieces out to processing departments, and receives
        # them back (a few pieces lost to each process).
        procs = []
        if sc["product"] == "hoodie":
            procs.append(("WASHING", "6.50", max(1, accepted_total // 140)))
        if sc["product"] in ("tshirt", "kidtee"):
            procs.append(("PRINTING", "8.00", max(1, accepted_total // 120)))
        if sc["product"] in ("polo", "cargo"):
            procs.append(("EMBROIDERY", "5.00", max(1, accepted_total // 150)))
        procs.append(("FINISHING", "2.50", accepted_total // 300))
        for dept, cpp, loss in procs:
            recv = accepted_total - loss
            ProcessDispatch.objects.create(
                order=order, department=dept, quantity_sent=accepted_total, sent_date=order_date + timedelta(days=11),
                sent_by=ctx["prod"], quantity_received=recv, received_date=order_date + timedelta(days=13),
                received_by=ctx["finish"], is_outsourced=(dept != "FINISHING"),
                cost=(D(cpp) * D(accepted_total)).quantize(D("0.01")), status="RECEIVED",
                remarks=f"{dept.title()} process")

        # Finishing does QC only: pass / alter / fail.
        rejects = max(1, accepted_total // 130)
        altered = max(1, accepted_total // 90)
        FinishingQualityCheck.objects.create(order=order, checked_by=ctx["finish"], quantity_checked=accepted_total,
                                             quantity_passed=accepted_total - rejects - altered, quantity_altered=altered,
                                             quantity_rejected=rejects, notes="Final AQL inspection")
        passed = accepted_total - rejects
        Packing.objects.create(order=order, packed_by=ctx["finish"], quantity_packed=passed, carton_count=max(1, passed // 50))

        if stage < STAGE_RANK["dispatched"]:
            self._advance_income(order, ctx, dispatched=False)
            return

        # --- 6. DISPATCH (+ delivery) ---
        dispatch = Dispatch.objects.create(order=order, dispatched_by=ctx["finish"], dispatch_date=order_date + timedelta(days=14),
                                           status="DISPATCHED", quantity_dispatched=passed, carrier="Nepal Cargo Movers",
                                           mode_of_transport="ROAD", transport_cost=D("4500"), tracking_number=f"TRK-{order.order_number}")
        if sc.get("delivered"):
            dispatch.status = "DELIVERED"; dispatch.delivery_date = order_date + timedelta(days=18)
            dispatch.delivery_acknowledged_by = party.contact_person
            dispatch.save(update_fields=["status", "delivery_date", "delivery_acknowledged_by"])
        order.advance_status(Order.Status.DISPATCHED)
        # Finished goods logged into Store's finished-goods register.
        FinishedGoodsReceipt.objects.create(
            order=order, quantity=passed, dispatch_reference=dispatch.tracking_number,
            received_at=timezone.now(), received_by=ctx["store"],
            remarks="Auto-logged from dispatch.")
        self._advance_income(order, ctx, dispatched=True)

    # --------------------------------------------------- helpers
    def _seed_activity(self, ctx):
        """Populate the admin Activity Log with realistic 'who did what' rows
        spread across the last ~12 days (middleware writes real ones going
        forward)."""
        now = timezone.now()
        templates = [
            (ctx["merch"], "MERCHANDISE", "Merchandising", "Created order"),
            (ctx["merch"], "MERCHANDISE", "Merchandising", "Confirmed order"),
            (ctx["store"], "STORE_MANAGER", "Store", "Received purchase order"),
            (ctx["store"], "STORE_MANAGER", "Store", "Issued fabric to cutting"),
            (ctx["cutter"], "CUTTING_SUPERVISOR", "Cutting", "Recorded the cut for cutting order"),
            (ctx["cutter"], "CUTTING_SUPERVISOR", "Cutting", "Sent to Production bundle"),
            (ctx["cutter"], "CUTTING_SUPERVISOR", "Cutting", "Created accessory issue"),
            (ctx["prod"], "PRODUCTION_SUPERVISOR", "Production", "Created bundle assignment"),
            (ctx["prod"], "PRODUCTION_SUPERVISOR", "Production", "Quality-checked bundle assignment"),
            (ctx["prod"], "PRODUCTION_SUPERVISOR", "Production", "Sent to Finishing hand-off"),
            (ctx["finish"], "FINISHING_SUPERVISOR", "Finishing", "Created finishing operation"),
            (ctx["finish"], "FINISHING_SUPERVISOR", "Finishing", "Dispatched dispatch"),
            (ctx["accounts"], "ACCOUNTS", "Accounts", "Paid invoice"),
            (ctx["accounts"], "ACCOUNTS", "Accounts", "Created income record"),
            (ctx["admin"], "ADMIN", "Admin", "Reviewed shortage for bundle assignment"),
        ]
        made = []
        for day in range(0, 12):
            for i, (u, role, dept, action) in enumerate(templates):
                if (day * 3 + i) % 4:  # keep ~1 in 4 -> a realistic daily handful
                    continue
                log = ActivityLog.objects.create(
                    user=u, user_name=(u.get_full_name() or u.username), role=role,
                    department=dept, action=action, method="POST", path="/api/(seeded)/")
                made.append((log.pk, now - timedelta(days=day, hours=(i % 9) + 1, minutes=(i * 11) % 60)))
        for pk, ts in made:
            ActivityLog.objects.filter(pk=pk).update(created_at=ts)  # auto_now_add ignores create() value

    def _cutting_issues_accessory(self, order, order_date, total_pieces, ctx):
        stock = AccessoryStock.objects.filter(accessory=ctx["accessories"]["label"]).first()
        if not stock or stock.available_quantity < total_pieces:
            return None
        issue = AccessoryIssue.objects.create(order=order, accessory_stock=stock, issued_quantity=total_pieces,
                                              issued_date=order_date + timedelta(days=4), issued_by=ctx["cutter"])
        AccessoryStockTransaction.objects.create(accessory_stock=stock, transaction_type="ISSUE", quantity=total_pieces,
                                                  reference=issue.issue_number, created_by=ctx["cutter"])
        stock.available_quantity -= total_pieces
        stock.save(update_fields=["available_quantity"])
        return issue

    def _pay_supplier(self, inv, mode, order_date, today, accounts):
        if mode == "full":
            finance_services.record_payment(inv, inv.total_amount, "BANK_TRANSFER", order_date + timedelta(days=10), "Invoice settled in full", accounts)
        elif mode == "half":
            finance_services.record_payment(inv, (inv.total_amount / 2).quantize(D("0.01")), "CHEQUE", order_date + timedelta(days=8), "50% advance to supplier", accounts)
        elif mode == "overdue":
            inv.due_date = today - timedelta(days=5)  # past due, unpaid
            inv.save(update_fields=["due_date"])
        # "none" -> leave unpaid but not overdue

    def _advance_income(self, order, ctx, dispatched):
        total = order.total_order_amount
        IncomeRecord.objects.get_or_create(order=order, income_type="ADVANCE", defaults=dict(
            amount=(total * D("0.4")).quantize(D("0.01")), received_date=order.order_date + timedelta(days=2),
            remarks="40% advance on order confirmation", recorded_by=ctx["accounts"]))
        if dispatched:
            IncomeRecord.objects.get_or_create(order=order, income_type="FINAL", defaults=dict(
                amount=(total * D("0.6")).quantize(D("0.01")), received_date=order.order_date + timedelta(days=16),
                remarks="Balance 60% on dispatch", recorded_by=ctx["accounts"]))

    def print_summary(self):
        s = self.style.SUCCESS
        self.stdout.write(s("\n===== Rich factory data seeded ====="))
        self.stdout.write(f"Parties {Party.objects.count()} · Vendors {Vendor.objects.count()} · Products {Product.objects.count()} · "
                          f"Colors {Color.objects.count()} · Operators {Operator.objects.count()} · Markers {Marker.objects.count()}")
        self.stdout.write("Orders %d (dispatched %d, finishing %d, production %d, cutting %d, confirmed %d, cancelled %d)" % (
            Order.objects.count(), Order.objects.filter(status="DISPATCHED").count(),
            Order.objects.filter(status="IN_FINISHING").count(), Order.objects.filter(status="IN_PRODUCTION").count(),
            Order.objects.filter(status="IN_CUTTING").count(), Order.objects.filter(status="CONFIRMED").count(),
            Order.objects.filter(status="CANCELLED").count()))
        self.stdout.write(f"Cutting orders {CuttingOrder.objects.count()} (over-consumption {CuttingOrder.objects.filter(average_status='DONT_CUT').count()}) · "
                          f"Bundles {Bundle.objects.count()} · Assignments {BundleAssignment.objects.count()} "
                          f"(pending-review {BundleAssignment.objects.filter(shortage_reason_status='PENDING_REVIEW').count()})")
        self.stdout.write(f"Accessory issues {AccessoryIssue.objects.count()} · Allocations {BundleAccessoryIssue.objects.count()} · "
                          f"Dispatches {Dispatch.objects.count()} (delivered {Dispatch.objects.filter(status='DELIVERED').count()})")
        self.stdout.write(f"POs {PurchaseOrder.objects.count()} · Invoices {Invoice.objects.count()} · Income {IncomeRecord.objects.count()} · "
                          f"Expenses {ExpenseRecord.objects.count()} · Operator incomes {OperatorIncome.objects.count()} · Notifications {Notification.objects.count()}")
        self.stdout.write(f"Activity log rows {ActivityLog.objects.count()} · Password-reset requests {PasswordResetRequest.objects.count()} · "
                          f"Operator accessory issues {OperatorAccessoryIssue.objects.count()}")
        self.stdout.write(s("Done. Log in as admin to explore every dashboard.\n"))
