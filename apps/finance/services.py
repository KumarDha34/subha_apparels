"""Receiving logic shared by the manual `receive` action and the
synchronous customer-supplied path. Kept out of views.py/serializers.py so
the Fabric-vs-Accessory stock branching only lives in one place."""
from decimal import Decimal
from django.utils import timezone
from apps.store.models import FabricStock, StockTransaction, AccessoryStock, AccessoryStockTransaction, Unit as FabricUnit
from .models import PurchaseOrder, PurchaseOrderItem, Invoice, PaymentRecord


def apply_receipt(item, delta, rate, po, user):
    """Bump one item's received_quantity (and rate, if given) and push
    `delta` into Fabric/Accessory stock as a RECEIPT transaction."""
    item.received_quantity += delta
    if rate is not None:
        item.rate = rate
    item.save(update_fields=["received_quantity", "rate", "updated_at"])

    reference = po.po_number
    remarks = f"Received from {po.po_number}"
    if item.material_type == PurchaseOrderItem.MaterialType.FABRIC:
        rolls = item.no_of_rolls or 1
        is_customer = po.po_type == PurchaseOrder.POType.CUSTOMER_SUPPLIED
        # A roll is a physical package, not a unit: when fabric arrives as
        # several rolls (a customer supplying 5 rolls of White 110 m), each
        # roll becomes its own FabricStock row measured in metres/kg, so
        # Cutting can pick, use and return rolls individually. Vendor/bulk
        # single-roll receipts keep merging into one running-balance row.
        if rolls > 1 or is_customer:
            per_roll = (delta / rolls).quantize(Decimal("0.01"))
            # Tag the roll number with the colour so multi-colour POs don't
            # produce clashing labels (PO-X-WHT1 vs PO-X-BLK1).
            tag = (item.color.name[:3].upper() if item.color_id else "R")
            for i in range(1, rolls + 1):
                qty = delta - per_roll * (rolls - 1) if i == rolls else per_roll
                stock = FabricStock.objects.create(
                    fabric_type=item.fabric_type, color=item.color,
                    unit=item.unit or FabricUnit.METERS, vendor=po.vendor,
                    supplied_by_party=(po.party if is_customer else None),
                    roll_number=f"{po.po_number}-{tag}{i}",
                )
                StockTransaction.objects.create(
                    fabric_stock=stock, transaction_type=StockTransaction.TransactionType.RECEIPT,
                    quantity=qty, reference=reference, remarks=remarks, created_by=user,
                )
                stock.available_quantity = qty
                stock.save(update_fields=["available_quantity", "updated_at"])
        else:
            # Single-roll vendor/bulk receipts merge into one running-balance
            # row -- the aggregate row is the blank-roll_number one, so it must
            # NOT collide with the per-roll stocks (which carry a roll_number).
            # filter().first() (not get_or_create) keeps this safe even if more
            # than one aggregate row already exists for this fabric+colour.
            stock = FabricStock.objects.filter(
                fabric_type=item.fabric_type, color=item.color, roll_number="",
            ).first()
            if stock is None:
                stock = FabricStock.objects.create(
                    fabric_type=item.fabric_type, color=item.color, roll_number="",
                    unit=item.unit or FabricUnit.METERS, vendor=po.vendor,
                )
            StockTransaction.objects.create(
                fabric_stock=stock, transaction_type=StockTransaction.TransactionType.RECEIPT,
                quantity=delta, reference=reference, remarks=remarks, created_by=user,
            )
            stock.available_quantity += delta
            stock.save(update_fields=["available_quantity", "updated_at"])
    else:
        accessory_defaults = {"vendor": po.vendor}
        if po.po_type == PurchaseOrder.POType.CUSTOMER_SUPPLIED:
            accessory_defaults["supplied_by_party"] = po.party
        stock, _ = AccessoryStock.objects.get_or_create(accessory=item.accessory, defaults=accessory_defaults)
        AccessoryStockTransaction.objects.create(
            accessory_stock=stock, transaction_type=AccessoryStockTransaction.TransactionType.RECEIPT,
            quantity=delta, reference=reference, remarks=remarks, created_by=user,
        )
        stock.available_quantity += delta
        stock.save(update_fields=["available_quantity", "updated_at"])


def recompute_receipt_status(po):
    items = list(po.items.all())
    if not items:
        return
    if all(i.received_quantity >= i.quantity for i in items):
        po.receipt_status = PurchaseOrder.ReceiptStatus.RECEIVED
    elif any(i.received_quantity > 0 for i in items):
        po.receipt_status = PurchaseOrder.ReceiptStatus.PARTIALLY_RECEIVED
    else:
        po.receipt_status = PurchaseOrder.ReceiptStatus.PENDING
    po.save(update_fields=["receipt_status", "updated_at"])


def sync_invoice(po):
    """One auto-generated Invoice per PO: get (never duplicate) and
    recompute subtotal from every item's received_quantity * rate, every
    time receive() is called -- keeps partial receipts in sync."""
    subtotal = sum((i.received_quantity or 0) * (i.rate or 0) for i in po.items.all())
    invoice = po.invoices.order_by("id").first()
    if invoice is None:
        Invoice.objects.create(purchase_order=po, vendor=po.vendor, invoice_date=timezone.localdate(), subtotal=subtotal)
    else:
        invoice.subtotal = subtotal
        invoice.save()


def receive_customer_supplied(po, user):
    """CUSTOMER_SUPPLIED bypasses manual receiving entirely: every item is
    fully received at creation time, stock updates immediately, and no
    Invoice is created (no money changes hands for customer-owned goods)."""
    for item in po.items.all():
        remaining = item.quantity - item.received_quantity
        if remaining > 0:
            apply_receipt(item, remaining, rate=None, po=po, user=user)
    po.receipt_status = PurchaseOrder.ReceiptStatus.RECEIVED
    po.save(update_fields=["receipt_status", "updated_at"])


def record_payment(invoice, amount, payment_method, payment_date, notes, user):
    """Records one payment installment against an invoice. Each PaymentRecord
    row stores the CUMULATIVE amount paid to date (matching the model's own
    save() which computes due_amount = total_amount - paid_amount), so the
    latest row is always the current running balance; Invoice.payment_status
    mirrors that same cumulative state (UNPAID/PARTIALLY_PAID/PAID)."""
    last = invoice.payment_records.order_by("-id").first()
    prior_cumulative = last.paid_amount if last else 0
    cumulative_paid = prior_cumulative + amount
    if cumulative_paid > invoice.total_amount:
        raise ValueError(f"Payment of {amount} exceeds the remaining due amount.")

    record_status = PaymentRecord.PaymentStatus.PAID if cumulative_paid >= invoice.total_amount else PaymentRecord.PaymentStatus.PARTIALLY_PAID
    record = PaymentRecord.objects.create(
        purchase_order=invoice.purchase_order, invoice=invoice,
        total_amount=invoice.total_amount, paid_amount=cumulative_paid, payment_status=record_status,
        invoice_date=invoice.invoice_date, due_date=invoice.due_date, payment_date=payment_date,
        payment_method=payment_method, notes=notes, recorded_by=user,
    )

    if cumulative_paid <= 0:
        invoice.payment_status = Invoice.PaymentStatus.UNPAID
    elif cumulative_paid >= invoice.total_amount:
        invoice.payment_status = Invoice.PaymentStatus.PAID
    else:
        invoice.payment_status = Invoice.PaymentStatus.PARTIALLY_PAID
    invoice.save(update_fields=["payment_status", "updated_at"])
    return record


def sync_invoice_status(invoice):
    """Re-derive a supplier invoice's payment status against its CURRENT total.
    Call after the total changes (e.g. an extra cost is added AFTER payment):
    a fully-paid bill that grows becomes PARTIALLY_PAID with a fresh balance
    due, while the paid amount stays untouched. Keeps the latest PaymentRecord's
    running balance in step so 'due' is always total - paid."""
    from decimal import Decimal
    last = invoice.payment_records.order_by("-id").first()
    paid = last.paid_amount if last else Decimal("0")
    # keep the running-balance row aligned to the new total (its save() recomputes due_amount)
    if last and last.total_amount != invoice.total_amount:
        last.total_amount = invoice.total_amount
        last.payment_status = (PaymentRecord.PaymentStatus.PAID if paid >= invoice.total_amount
                               else PaymentRecord.PaymentStatus.PARTIALLY_PAID)
        last.save(update_fields=["total_amount", "due_amount", "payment_status", "updated_at"])
    if paid <= 0:
        status = Invoice.PaymentStatus.UNPAID
    elif paid >= invoice.total_amount:
        status = Invoice.PaymentStatus.PAID
    else:
        status = Invoice.PaymentStatus.PARTIALLY_PAID
    if invoice.payment_status != status:
        invoice.payment_status = status
        invoice.save(update_fields=["payment_status", "updated_at"])
    return status
