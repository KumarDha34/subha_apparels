from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from apps.users.permissions import ReadOnlyOrHasRole
from apps.users.services import notify_role
from apps.store.models import StockTransaction
from apps.orders.models import Order, OrderItemColor, OrderItemColorSize
from .models import CuttingOrder, CuttingPiece, Bundle, Marker
from .serializers import CuttingOrderSerializer, CuttingPieceSerializer, BundleSerializer, MarkerSerializer


class MarkerViewSet(viewsets.ModelViewSet):
    queryset = Marker.objects.select_related("fabric_type").all().order_by("-created_at")
    serializer_class = MarkerSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "CUTTING_SUPERVISOR"]
    search_fields = ["marker_number", "name"]
    filterset_fields = ["fabric_type", "is_active"]


class CuttingOrderViewSet(viewsets.ModelViewSet):
    queryset = CuttingOrder.objects.select_related("order", "order_item", "fabric_issued", "supervisor", "marker").all().order_by("-created_at")
    serializer_class = CuttingOrderSerializer
    permission_classes = [ReadOnlyOrHasRole]
    # Store issues the fabric (creates the record, which deducts stock);
    # Cutting Supervisor manages it from there (receive, cut, bundle).
    required_roles = ["ADMIN", "STORE_MANAGER", "CUTTING_SUPERVISOR"]
    filterset_fields = ["status", "order", "average_status"]
    search_fields = ["cutting_number", "order__order_number"]

    def _require_cutting_role(self, request):
        if not (request.user.is_superuser or request.user.role in ("ADMIN", "CUTTING_SUPERVISOR")):
            raise PermissionDenied("Only a Cutting Supervisor can do this.")

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        """Cutting's own confirmation that it physically received what
        Store issued -- a distinct event from the issue itself."""
        self._require_cutting_role(request)
        cutting_order = self.get_object()
        if cutting_order.status != CuttingOrder.Status.FABRIC_ISSUED:
            return Response({"detail": "Only fabric awaiting receipt can be received."}, status=400)
        cutting_order.received_at = timezone.now()
        cutting_order.received_by = request.user
        cutting_order.status = CuttingOrder.Status.RECEIVED
        cutting_order.save(update_fields=["received_at", "received_by", "status", "updated_at"])
        return Response(self.get_serializer(cutting_order).data)

    @action(detail=True, methods=["post"])
    def start_cutting(self, request, pk=None):
        self._require_cutting_role(request)
        cutting_order = self.get_object()
        if cutting_order.status != CuttingOrder.Status.RECEIVED:
            return Response({"detail": "Only received fabric can start cutting."}, status=400)
        cutting_order.status = CuttingOrder.Status.CUTTING
        cutting_order.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(cutting_order).data)

    def _primary_component_id(self, cutting_order):
        """The one component (if any) whose cut quantity represents "how
        many complete garments" -- the denominator for the average check
        and the number checked against Fixed caps / Ratio ceilings. None
        when the product has no components defined (pre-component behavior)."""
        if not cutting_order.order_item_id:
            return None
        primary = cutting_order.order_item.product.components.filter(is_active=True, is_primary=True).first()
        return primary.id if primary else None

    @action(detail=True, methods=["post"])
    def record_cut(self, request, pk=None):
        """Records the actual cut result and runs the approved-vs-actual
        average check. Branches on the order's type: Fixed orders accept a
        manually-entered piece breakdown capped at the ordered quantity;
        Ratio orders compute the piece breakdown from a Marker's fabric
        efficiency and how many complete ratio sets were cut. Safe to call
        again (before bundling starts) to correct a mistake: replaces the
        whole CuttingPiece set rather than appending to it."""
        self._require_cutting_role(request)
        cutting_order = self.get_object()
        if cutting_order.status == CuttingOrder.Status.COMPLETED:
            return Response({"detail": "This cutting order is already completed."}, status=400)
        if cutting_order.status not in (CuttingOrder.Status.RECEIVED, CuttingOrder.Status.CUTTING):
            return Response({"detail": "Fabric must be received before recording a cut."}, status=400)
        if cutting_order.bundles.exists():
            return Response({"detail": "Bundles already created from this cutting order -- pieces are locked."}, status=400)

        order_type = cutting_order.order.order_type if cutting_order.order else None
        primary_component_id = self._primary_component_id(cutting_order)

        if order_type == Order.OrderType.RATIO_BASED:
            return self._record_cut_ratio(request, cutting_order, primary_component_id)
        return self._record_cut_fixed(request, cutting_order, order_type, primary_component_id)

    def _record_cut_fixed(self, request, cutting_order, order_type, primary_component_id):
        fabric_used_quantity = request.data.get("fabric_used_quantity")
        raw_pieces = request.data.get("pieces") or []
        if fabric_used_quantity is None:
            return Response({"detail": "fabric_used_quantity is required."}, status=400)
        if not raw_pieces:
            return Response({"detail": "At least one piece row is required."}, status=400)

        if order_type == Order.OrderType.FIXED_QUANTITY and not cutting_order.order_item_id:
            return Response({
                "detail": "Could not determine which order item this cutting order belongs to -- the "
                          "Fixed-Quantity cap can't be enforced without it. Check that this fabric roll "
                          "is linked to exactly one product item on the order.",
            }, status=400)

        fabric_used_quantity = Decimal(str(fabric_used_quantity))
        wastage_quantity = Decimal(str(request.data.get("wastage_quantity") or 0))
        pieces = [
            {
                "color": int(p["color"]), "size": int(p["size"]),
                "component": int(p["component"]) if p.get("component") else None,
                "quantity": int(p["quantity"]),
            }
            for p in raw_pieces
        ]

        if order_type == Order.OrderType.FIXED_QUANTITY and cutting_order.order_item_id:
            error = self._check_fixed_caps(cutting_order, pieces, primary_component_id)
            if error:
                return Response({"detail": error}, status=400)

        return self._write_pieces_and_finalize(cutting_order, pieces, fabric_used_quantity, wastage_quantity, primary_component_id)

    def _check_fixed_caps(self, cutting_order, pieces, primary_component_id):
        """Returns an error message if any piece would push the cumulative
        cut quantity (across every CuttingOrder sharing this order_item)
        past what Merchandising actually ordered for that color+size."""
        order_item = cutting_order.order_item
        for p in pieces:
            if p["component"] != primary_component_id:
                continue  # caps are about garment count, not sub-components
            try:
                order_item_color = order_item.colors.get(color_id=p["color"])
                size_line = order_item_color.size_lines.get(size_id=p["size"])
            except (OrderItemColor.DoesNotExist, OrderItemColorSize.DoesNotExist):
                continue
            ordered_qty = size_line.quantity
            if ordered_qty is None:
                continue
            prior = (
                CuttingPiece.objects.filter(
                    cutting_order__order_item=order_item, color_id=p["color"], size_id=p["size"],
                    component_id=primary_component_id,
                ).exclude(cutting_order=cutting_order).aggregate(q=Sum("quantity"))["q"] or 0
            )
            if prior + p["quantity"] > ordered_qty:
                return (
                    f"Cutting {size_line.size.name} would exceed the ordered quantity ({ordered_qty}) -- "
                    f"already cut {prior}, attempting {p['quantity']} more."
                )
        return None

    def _record_cut_ratio(self, request, cutting_order, primary_component_id):
        marker_id = request.data.get("marker")
        sets_cut = request.data.get("sets_cut")
        raw_pieces = request.data.get("pieces") or []
        if not marker_id or not sets_cut:
            return Response({"detail": "marker and sets_cut are required."}, status=400)
        if not raw_pieces:
            return Response({"detail": "At least one piece row is required."}, status=400)

        try:
            marker = Marker.objects.get(pk=marker_id)
        except Marker.DoesNotExist:
            return Response({"detail": "Marker not found."}, status=400)

        sets_cut = int(sets_cut)
        if sets_cut <= 0:
            return Response({"detail": "sets_cut must be greater than 0."}, status=400)

        wastage_quantity = Decimal(str(request.data.get("wastage_quantity") or 0))
        fabric_used_quantity = Decimal(sets_cut) * marker.avg_consumption_per_set
        if fabric_used_quantity + wastage_quantity > cutting_order.fabric_issued_quantity:
            return Response({
                "detail": f"{sets_cut} sets would need {fabric_used_quantity} meters (plus {wastage_quantity} "
                          f"wastage) -- more than the {cutting_order.fabric_issued_quantity} issued.",
            }, status=400)

        order_item_color = OrderItemColor.objects.filter(
            order_item=cutting_order.order_item, rolls=cutting_order.fabric_issued,
        ).first()
        if order_item_color is None:
            return Response({"detail": "Could not determine the size ratio for this cutting order -- check the order's roll assignment."}, status=400)
        ratio_by_size = {sl.size_id: sl.ratio_part for sl in order_item_color.size_lines.all()}

        pieces = []
        for p in raw_pieces:
            size_id, color_id, quantity = int(p["size"]), int(p["color"]), int(p["quantity"])
            component_id = int(p["component"]) if p.get("component") else None
            ratio_part = ratio_by_size.get(size_id)
            if not ratio_part:
                return Response({"detail": "One of the submitted sizes is not part of this order's ratio."}, status=400)
            ceiling = ratio_part * sets_cut
            if quantity > ceiling:
                return Response({"detail": f"Quantity {quantity} exceeds the ratio-computed ceiling ({ceiling}) for this size."}, status=400)
            pieces.append({"color": color_id, "size": size_id, "component": component_id, "quantity": quantity})

        cutting_order.marker = marker
        cutting_order.ratio_sets_cut = sets_cut
        cutting_order.save(update_fields=["marker", "ratio_sets_cut", "updated_at"])

        return self._write_pieces_and_finalize(cutting_order, pieces, fabric_used_quantity, wastage_quantity, primary_component_id)

    def _write_pieces_and_finalize(self, cutting_order, pieces, fabric_used_quantity, wastage_quantity, primary_component_id):
        total_pieces_cut = sum(p["quantity"] for p in pieces if p["component"] == primary_component_id)
        if total_pieces_cut <= 0:
            return Response({"detail": "Total pieces cut must be greater than 0."}, status=400)

        with transaction.atomic():
            seen = set()
            for p in pieces:
                CuttingPiece.objects.update_or_create(
                    cutting_order=cutting_order, color_id=p["color"], size_id=p["size"], component_id=p["component"],
                    defaults={"quantity": p["quantity"]},
                )
                seen.add((p["color"], p["size"], p["component"]))
            for piece in cutting_order.pieces.all():
                if (piece.color_id, piece.size_id, piece.component_id) not in seen:
                    piece.delete()

            cutting_order.fabric_used_quantity = fabric_used_quantity
            cutting_order.wastage_quantity = wastage_quantity
            cutting_order.total_pieces_cut = total_pieces_cut

            if cutting_order.order_item_id and cutting_order.order_item.approved_average:
                actual_average = fabric_used_quantity / total_pieces_cut
                cutting_order.actual_average = actual_average
                if actual_average > cutting_order.order_item.approved_average:
                    cutting_order.average_status = CuttingOrder.AverageStatus.DONT_CUT
                    cutting_order.status = CuttingOrder.Status.CUTTING
                else:
                    cutting_order.average_status = CuttingOrder.AverageStatus.CUT
                    cutting_order.status = CuttingOrder.Status.COMPLETED
            else:
                cutting_order.average_status = CuttingOrder.AverageStatus.NOT_APPLICABLE
                cutting_order.status = CuttingOrder.Status.COMPLETED

            cutting_order.save(update_fields=[
                "fabric_used_quantity", "wastage_quantity", "total_pieces_cut",
                "actual_average", "average_status", "status", "updated_at",
            ])
        return Response(self.get_serializer(cutting_order).data)

    @action(detail=True, methods=["post"])
    def record_layer(self, request, pk=None):
        """Layer-based cutting. The cutting master lays fabric in a spread and
        enters: layer length, number of layers, and the pieces cut per size in
        ONE layer (the marker ratio). We then:
          * add pieces per size = pieces-per-layer x no_of_layers,
          * auto-create bundles -- one bundle per cut position, each holding
            `no_of_layers` pieces (one piece per layer),
          * roll the fabric used / average into the cutting order.
        Multiple lays can be recorded; each adds its own pieces + bundles, so
        different rolls/lays never share a bundle and stay identifiable."""
        self._require_cutting_role(request)
        co = self.get_object()
        if co.status == CuttingOrder.Status.COMPLETED:
            return Response({"detail": "This cutting order is already completed."}, status=400)
        if co.status not in (CuttingOrder.Status.RECEIVED, CuttingOrder.Status.CUTTING):
            return Response({"detail": "Fabric must be received before recording a lay."}, status=400)

        try:
            layer_length = Decimal(str(request.data.get("layer_length")))
            no_of_layers = int(request.data.get("no_of_layers"))
        except (TypeError, ValueError, InvalidOperation):
            return Response({"detail": "layer_length and no_of_layers are required numbers."}, status=400)
        if layer_length <= 0 or no_of_layers <= 0:
            return Response({"detail": "layer_length and no_of_layers must be greater than 0."}, status=400)

        try:
            rows = [{"size": int(r["size"]), "per_layer": int(r.get("pieces_per_layer") or 0)}
                    for r in (request.data.get("sizes") or [])]
        except (TypeError, ValueError):
            return Response({"detail": "Invalid size rows."}, status=400)
        rows = [r for r in rows if r["per_layer"] > 0]
        if not rows:
            return Response({"detail": "Enter pieces-per-layer for at least one size."}, status=400)

        color = co.fabric_issued.color if co.fabric_issued_id else None
        components = list(co.order_item.product.components.filter(is_active=True)) if co.order_item_id else []
        fabric_used_this_lay = layer_length * no_of_layers
        lay_pieces = sum(r["per_layer"] for r in rows) * no_of_layers

        if (co.fabric_used_quantity or 0) + fabric_used_this_lay + (co.wastage_quantity or 0) + co.returned_quantity > co.fabric_issued_quantity:
            return Response({"detail": f"This lay needs {fabric_used_this_lay} m but only {co.remaining_quantity} m of the "
                                       f"issued fabric is left. Reduce the layers/length or return unused fabric."}, status=400)

        remarks = request.data.get("remarks", "")
        with transaction.atomic():
            for r in rows:
                total = r["per_layer"] * no_of_layers
                targets = components if components else [None]
                for comp in targets:
                    cp, _ = CuttingPiece.objects.get_or_create(
                        cutting_order=co, color=color, size_id=r["size"], component=comp, defaults={"quantity": 0})
                    cp.quantity += total
                    cp.save(update_fields=["quantity"])
                # one bundle per cut position -> no_of_layers pieces each.
                for _ in range(r["per_layer"]):
                    Bundle.objects.create(cutting_order=co, color=color, size_id=r["size"],
                                          quantity=no_of_layers, status=Bundle.Status.CREATED)

            co.fabric_used_quantity = (co.fabric_used_quantity or Decimal("0")) + fabric_used_this_lay
            co.layer_length = layer_length
            co.no_of_layers = (co.no_of_layers or 0) + no_of_layers
            co.total_pieces_cut = (co.total_pieces_cut or 0) + lay_pieces
            if remarks:
                co.remarks = (co.remarks + " | " if co.remarks else "") + remarks
            if co.order_item_id and co.order_item.approved_average and co.total_pieces_cut:
                co.actual_average = co.fabric_used_quantity / co.total_pieces_cut
                co.average_status = (CuttingOrder.AverageStatus.DONT_CUT
                                     if co.actual_average > co.order_item.approved_average
                                     else CuttingOrder.AverageStatus.CUT)
            else:
                co.average_status = CuttingOrder.AverageStatus.NOT_APPLICABLE
            co.status = CuttingOrder.Status.CUTTING
            co.save()
        return Response(self.get_serializer(co).data)

    @action(detail=True, methods=["post"])
    def send_to_production(self, request, pk=None):
        """Send ALL bundles from this cutting order to Production at once."""
        self._require_cutting_role(request)
        co = self.get_object()
        
        # Check if cutting order is completed
        if co.status != CuttingOrder.Status.COMPLETED:
            return Response(
                {"detail": "Only completed cutting orders can be sent to Production."},
                status=400
            )
        
        # Bundles not yet sent to Production.
        bundles = list(co.bundles.filter(sent_to_production_at__isnull=True))
        if not bundles:
            return Response(
                {"detail": "No bundles to send — all bundles from this cutting order have already been sent."},
                status=400,
            )

        # Send + auto-receive in one step so Production can allocate straight
        # away (no separate "receive bundles" click).
        from apps.production.models import BundleReceipt
        now = timezone.now()
        with transaction.atomic():
            for b in bundles:
                b.sent_to_production_at = now
                b.sent_by = request.user
                b.status = Bundle.Status.RECEIVED
                b.save(update_fields=["sent_to_production_at", "sent_by", "status", "updated_at"])
                BundleReceipt.objects.get_or_create(bundle=b, defaults={"received_by": request.user})
            # Bundles reaching the floor is the real start of production -- move
            # the order to IN_PRODUCTION so it shows up on Send to Process (even
            # from just the first of several cutting orders; sending is partial).
            if co.order_id:
                co.order.advance_status(Order.Status.IN_PRODUCTION)

        count = len(bundles)
        notify_role(
            "PRODUCTION_SUPERVISOR",
            f"{count} bundles from {co.cutting_number} (Order: {co.order.order_number}) sent to Production — ready to allocate.",
            link="/production/bundle-allocation/",
        )
        return Response({
            "detail": f"{count} bundles sent to Production.",
            "count": count, "cutting_order": co.cutting_number,
        })

    @action(detail=True, methods=["post"])
    def complete_cutting(self, request, pk=None):
        """Marks a cutting order finished once all lays are recorded."""
        self._require_cutting_role(request)
        co = self.get_object()
        if not co.pieces.exists():
            return Response({"detail": "Record at least one lay before completing this cutting order."}, status=400)
        if co.average_status == CuttingOrder.AverageStatus.DONT_CUT and not co.average_override_approved:
            return Response({"detail": "Over-consumption on this order needs Admin approval before it can be completed."}, status=400)
        co.status = CuttingOrder.Status.COMPLETED
        co.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(co).data)

    @action(detail=True, methods=["post"])
    def approve_override(self, request, pk=None):
        """Admin-only: unblocks (or explicitly rejects, logging why) a
        cutting order stuck at DONT_CUT."""
        if not (request.user.is_superuser or request.user.role == "ADMIN"):
            raise PermissionDenied("Only an Admin can approve a cutting override.")
        cutting_order = self.get_object()
        if cutting_order.average_status != CuttingOrder.AverageStatus.DONT_CUT:
            return Response({"detail": "This cutting order isn't blocked on an average mismatch."}, status=400)
        approved = bool(request.data.get("approved"))
        cutting_order.average_override_by = request.user
        cutting_order.average_override_at = timezone.now()
        cutting_order.average_override_remarks = request.data.get("remarks", "")
        update_fields = ["average_override_by", "average_override_at", "average_override_remarks", "updated_at"]
        if approved:
            cutting_order.average_override_approved = True
            cutting_order.status = CuttingOrder.Status.COMPLETED
            update_fields += ["average_override_approved", "status"]
        cutting_order.save(update_fields=update_fields)
        return Response(self.get_serializer(cutting_order).data)

    @action(detail=True, methods=["post"])
    def return_fabric(self, request, pk=None):
        """Hands leftover issued-but-unused fabric back to Store's stock."""
        self._require_cutting_role(request)
        cutting_order = self.get_object()
        quantity = request.data.get("quantity")
        if quantity is None:
            return Response({"detail": "quantity is required."}, status=400)
        quantity = Decimal(str(quantity))
        remaining = cutting_order.remaining_quantity
        if quantity <= 0 or quantity > remaining:
            return Response({"detail": f"quantity must be between 0 and {remaining} (remaining)."}, status=400)

        with transaction.atomic():
            StockTransaction.objects.create(
                fabric_stock=cutting_order.fabric_issued,
                transaction_type=StockTransaction.TransactionType.RETURN,
                quantity=quantity,
                reference=cutting_order.cutting_number,
                remarks=request.data.get("remarks") or f"Returned from cutting order {cutting_order.cutting_number}",
                created_by=request.user,
            )
            stock = cutting_order.fabric_issued
            stock.available_quantity += quantity
            stock.save(update_fields=["available_quantity", "updated_at"])
            cutting_order.returned_quantity += quantity
            cutting_order.returned_at = timezone.now()
            cutting_order.returned_by = request.user
            cutting_order.save(update_fields=["returned_quantity", "returned_at", "returned_by", "updated_at"])
        return Response(self.get_serializer(cutting_order).data)


class CuttingPieceViewSet(viewsets.ModelViewSet):
    queryset = CuttingPiece.objects.select_related("cutting_order", "color", "size", "component").all()
    serializer_class = CuttingPieceSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "CUTTING_SUPERVISOR"]
    filterset_fields = ["cutting_order", "cutting_order__order_item", "color", "size", "component"]


class BundleViewSet(viewsets.ModelViewSet):
    queryset = Bundle.objects.select_related("cutting_order", "color", "size", "sent_by").all().order_by("-created_at")
    serializer_class = BundleSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "CUTTING_SUPERVISOR", "PRODUCTION_SUPERVISOR"]
    # Plain lists only support exact-match lookups -- sent_to_production_at
    # needs `isnull` so Production's Receive Bundles page can query for
    # "created but not yet explicitly sent".
    filterset_fields = {
        "status": ["exact"], "cutting_order": ["exact"], "color": ["exact"],
        "size": ["exact"], "sent_to_production_at": ["isnull"],
    }
    search_fields = ["bundle_number"]

    @action(detail=False, methods=["post"])
    def combine(self, request):
        """Merge several same colour+size bundles from one cutting order into a
        single bundle -- e.g. two White/S bundles of 20 pcs each become one
        bundle of 40. Body: {bundle_ids: [...]}. Only bundles still on the
        cutting floor (status CREATED, not yet sent to Production) qualify; the
        first selected bundle is kept (its number lives on) and the rest are
        absorbed into it."""
        if not (request.user.is_superuser or request.user.role in ("ADMIN", "CUTTING_SUPERVISOR")):
            raise PermissionDenied("Only a Cutting Supervisor can combine bundles.")
        ids = request.data.get("bundle_ids") or []
        if not isinstance(ids, list) or len(ids) < 2:
            return Response({"detail": "Select at least two bundles to combine."}, status=400)
        bundles = list(Bundle.objects.filter(id__in=ids))
        if len(bundles) != len(set(ids)):
            return Response({"detail": "One or more selected bundles no longer exist."}, status=400)
        stuck = [b.bundle_number for b in bundles
                 if b.status != Bundle.Status.CREATED or b.sent_to_production_at is not None]
        if stuck:
            return Response({"detail": f"Already past cutting, can't combine: {', '.join(stuck)}."}, status=400)
        if len({b.cutting_order_id for b in bundles}) != 1 or len({b.color_id for b in bundles}) != 1 \
                or len({b.size_id for b in bundles}) != 1:
            return Response({"detail": "Only bundles of the same cutting order, colour and size can be combined."}, status=400)
        with transaction.atomic():
            keep = bundles[0]
            keep.quantity = sum(b.quantity for b in bundles)
            keep.save(update_fields=["quantity", "updated_at"])
            for b in bundles[1:]:
                b.delete()
        return Response(self.get_serializer(keep).data)

    @action(detail=True, methods=["post"])
    def send_to_production(self, request, pk=None):
        """Cutting's explicit hand-off -- Production can't receive a bundle
        until this has been called, even though it was already cut."""
        if not (request.user.is_superuser or request.user.role in ("ADMIN", "CUTTING_SUPERVISOR")):
            raise PermissionDenied("Only a Cutting Supervisor can send bundles to Production.")
        bundle = self.get_object()
        if bundle.sent_to_production_at is not None:
            return Response({"detail": "This bundle has already been sent to Production."}, status=400)
        bundle.sent_to_production_at = timezone.now()
        bundle.sent_by = request.user
        bundle.save(update_fields=["sent_to_production_at", "sent_by", "updated_at"])
        notify_role(
            "PRODUCTION_SUPERVISOR",
            f"{bundle.quantity} pcs ({bundle.bundle_number}) sent from {bundle.cutting_order.cutting_number} -- ready to receive.",
            link="/production/receive-bundles/",
        )
        return Response(self.get_serializer(bundle).data)
