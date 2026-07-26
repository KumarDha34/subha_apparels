from decimal import Decimal
from datetime import date, timedelta
from django.utils import timezone
from django.db.models import Sum, Count, Q, F
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from apps.users.permissions import ReadOnlyOrHasRole, HasRole
from apps.cutting.models import Bundle
from .models import Operator, BundleAssignment, OperatorIncome
from .services import order_piece_rate, assignment_labor_cost
from .serializers import (
    OperatorSerializer,
    BundleAssignmentSerializer, OperatorIncomeSerializer,
)


def get_own_operator(request):
    """Resolve the Operator profile linked to the logged-in user, for the
    operator's own self-service dashboard. None if there isn't one."""
    return getattr(request.user, "operator_profile", None)


class OperatorViewSet(viewsets.ModelViewSet):
    queryset = Operator.objects.all().order_by("name")
    serializer_class = OperatorSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "PRODUCTION_SUPERVISOR"]
    filterset_fields = ["operator_type","is_active"]
    search_fields = ["name", "contact", "email"]

    @action(detail=True, methods=["post"])
    def add_member(self, request, pk=None):
        """Add an individual operator as a member of this GROUP."""
        group = self.get_object()
        if group.operator_type != Operator.OperatorType.GROUP:
            return Response({"detail": "Members can only be added to a GROUP operator."}, status=400)
        try:
            member = Operator.objects.get(pk=request.data.get("member_id"))
        except Operator.DoesNotExist:
            return Response({"detail": "Operator not found."}, status=404)
        if member.id == group.id:
            return Response({"detail": "A group can't be its own member."}, status=400)
        member.group = group
        member.save(update_fields=["group", "updated_at"])
        return Response(self.get_serializer(group).data)

    @action(detail=True, methods=["post"])
    def remove_member(self, request, pk=None):
        """Remove a member from this group."""
        group = self.get_object()
        try:
            member = group.members.get(pk=request.data.get("member_id"))
        except Operator.DoesNotExist:
            return Response({"detail": "That operator isn't a member of this group."}, status=404)
        member.group = None
        member.is_group_leader = False
        member.save(update_fields=["group", "is_group_leader", "updated_at"])
        return Response(self.get_serializer(group).data)

    @action(detail=True, methods=["post"])
    def set_leader(self, request, pk=None):
        """Mark one member as the group's leader (only one at a time)."""
        group = self.get_object()
        try:
            member = group.members.get(pk=request.data.get("member_id"))
        except Operator.DoesNotExist:
            return Response({"detail": "That operator isn't a member of this group."}, status=404)
        group.members.filter(is_group_leader=True).update(is_group_leader=False)
        member.is_group_leader = True
        member.save(update_fields=["is_group_leader", "updated_at"])
        return Response(self.get_serializer(group).data)

    @action(detail=True, methods=["get"])
    def report(self, request, pk=None):
        """Operator-wise production, earnings, and efficiency in one call."""
        operator = self.get_object()
        assignments = operator.assignments.all()
        completed = assignments.filter(status__in=[BundleAssignment.Status.COMPLETED, BundleAssignment.Status.QUALITY_CHECKED])
        total_defects = assignments.aggregate(d=Sum("defects"))["d"] or 0
        rejected = assignments.filter(shortage_reason_status=BundleAssignment.ShortageStatus.REJECTED)
        excused = assignments.filter(shortage_reason_status=BundleAssignment.ShortageStatus.APPROVED)
        incomes = operator.incomes.all()
        pieces_issued = assignments.aggregate(p=Sum("issued_quantity"))["p"] or 0
        pieces_returned = assignments.aggregate(p=Sum("returned_quantity"))["p"] or 0
        # Efficiency % = (Returned - Defects) / Received * 100
        # Quality Rate % = (Returned - Defects) / Returned * 100
        efficiency_pct = round((pieces_returned - total_defects) / pieces_issued * 100, 2) if pieces_issued else None
        quality_rate_pct = round((pieces_returned - total_defects) / pieces_returned * 100, 2) if pieces_returned else None
        # Live earnings + a day-by-day breakdown of accepted output and the
        # money it earned -- paid on each assignment's rate_per_piece (the rate
        # Production set at allocation), so this is always exactly rate x pieces
        # returned, independent of whether an OperatorIncome statement exists yet.
        completed_dated = completed.select_related("bundle__cutting_order__order_item").order_by("completion_date")
        total_earned = Decimal("0")
        daily = {}
        for a in completed_dated:
            cost = assignment_labor_cost(a)
            total_earned += cost
            key = a.completion_date.isoformat() if a.completion_date else "Unrecorded"
            row = daily.setdefault(key, {"date": key, "bundles": 0, "pieces": 0, "amount": Decimal("0")})
            row["bundles"] += 1
            row["pieces"] += a.returned_quantity or 0
            row["amount"] += cost
        daily_list = [{**r, "amount": float(r["amount"])} for r in daily.values()]

        # Bundle-by-bundle history: what was received (issued), returned,
        # lost (shortage), rejected (defects) and earned on every assignment.
        assignment_rows = []
        for a in assignments.select_related(
            "bundle__color", "bundle__size",
            "bundle__cutting_order__order", "bundle__cutting_order__order_item__product",
        ).order_by("-completion_date", "-assigned_date", "-id"):
            bundle = a.bundle
            co = bundle.cutting_order
            product = co.order_item.product if (co and co.order_item_id) else None
            issued = a.issued_quantity if a.issued_quantity is not None else bundle.quantity
            assignment_rows.append({
                "bundle_number": bundle.bundle_number,
                "order_number": co.order.order_number if (co and co.order_id) else "—",
                "product": f"{product.code} — {product.name}" if product else "—",
                "color": bundle.color.name if bundle.color_id else "",
                "size": bundle.size.name if bundle.size_id else "",
                "received": issued,
                "returned": a.returned_quantity,
                "lost": a.shortage_quantity,
                "defects": a.defects or 0,
                "status": a.status,
                "shortage_status": a.shortage_reason_status,
                "shortage_reason": a.shortage_reason or "",
                "assigned_date": a.assigned_date.isoformat() if a.assigned_date else None,
                "completion_date": a.completion_date.isoformat() if a.completion_date else None,
                "earned": float(assignment_labor_cost(a)),
                "rate": float(order_piece_rate(a)),
            })

        data = {
            "operator": OperatorSerializer(operator).data,
            "production": {
                "total_assignments": assignments.count(),
                "bundles_received": assignments.count(),
                "completed_bundles": completed.count(),
                "total_pieces": completed.aggregate(p=Sum("bundle__quantity"))["p"] or 0,
                "pieces_issued": pieces_issued,
                "pieces_returned": pieces_returned,
                "pieces_completed": pieces_returned,
                "pieces_lost": (
                    (rejected.aggregate(i=Sum("issued_quantity"))["i"] or 0)
                    - (rejected.aggregate(r=Sum("returned_quantity"))["r"] or 0)
                ),
                "pieces_excused": (
                    (excused.aggregate(i=Sum("issued_quantity"))["i"] or 0)
                    - (excused.aggregate(r=Sum("returned_quantity"))["r"] or 0)
                ),
                "total_defects": total_defects,
                "quality_pass_rate": (
                    round(assignments.filter(quality_check_passed=True).count() / assignments.count() * 100, 2)
                    if assignments.count() else None
                ),
                "efficiency_pct": efficiency_pct,
                "quality_rate_pct": quality_rate_pct,
            },
            "earnings": {
                "total_earned": float(total_earned),
                "total_income": incomes.aggregate(t=Sum("total_income"))["t"] or 0,
                "pending_amount": (
                    incomes.exclude(payment_status="PAID")
                    .aggregate(t=Sum(F("total_income") - F("paid_amount")))["t"] or 0
                ),
                "paid_amount": incomes.aggregate(t=Sum("paid_amount"))["t"] or 0,
            },
            "daily": daily_list,
            "assignments": assignment_rows,
        }
        return Response(data)

    @action(detail=True, methods=["get"])
    def trends(self, request, pk=None):
        """Last 8 weeks of completed work, for a lightweight trend chart."""
        from django.db.models.functions import TruncWeek
        operator = self.get_object()
        eight_weeks_ago = timezone.now().date() - timedelta(weeks=8)
        rows = (
            operator.assignments.filter(
                status__in=[BundleAssignment.Status.COMPLETED, BundleAssignment.Status.QUALITY_CHECKED],
                completion_date__gte=eight_weeks_ago,
            )
            .annotate(week=TruncWeek("completion_date"))
            .values("week")
            .annotate(bundles_completed=Count("id"), pieces_completed=Sum("returned_quantity"))
            .order_by("week")
        )
        return Response(list(rows))

    @action(detail=True, methods=["post"])
    def add_member(self, request, pk=None):
        """Add an individual operator to a group"""
        group = self.get_object()
        
        if group.operator_type != Operator.OperatorType.GROUP:
            return Response(
                {"detail": "Only GROUP type operators can have members."}, 
                status=400
            )
        
        member_id = request.data.get("member_id")
        if not member_id:
            return Response({"detail": "member_id is required."}, status=400)
        
        try:
            member = Operator.objects.get(pk=member_id)
        except Operator.DoesNotExist:
            return Response({"detail": "Member not found."}, status=404)
        
        if member.operator_type == Operator.OperatorType.GROUP:
            return Response(
                {"detail": "A group cannot be added as a member to another group."}, 
                status=400
            )
        
        # Remove from any existing group
        if member.group:
            member.group = None
            member.save()
        
        member.group = group
        member.is_group_leader = False
        member.save()
        
        return Response({
            "detail": f"{member.name} added to group {group.name}.",
            "group": self.get_serializer(group).data
        })

    @action(detail=True, methods=["post"])
    def remove_member(self, request, pk=None):
        """Remove a member from a group"""
        group = self.get_object()
        member_id = request.data.get("member_id")
        
        if not member_id:
            return Response({"detail": "member_id is required."}, status=400)
        
        try:
            member = Operator.objects.get(pk=member_id, group=group)
        except Operator.DoesNotExist:
            return Response({"detail": "Member not found in this group."}, status=404)
        
        member.group = None
        member.is_group_leader = False
        member.save()
        
        return Response({
            "detail": f"{member.name} removed from group.",
            "group": self.get_serializer(group).data
        })

    @action(detail=True, methods=["post"])
    def set_leader(self, request, pk=None):
        """Set a member as group leader"""
        group = self.get_object()
        member_id = request.data.get("member_id")
        
        if not member_id:
            return Response({"detail": "member_id is required."}, status=400)
        
        try:
            member = Operator.objects.get(pk=member_id, group=group)
        except Operator.DoesNotExist:
            return Response({"detail": "Member not found in this group."}, status=404)
        
        # Remove leader status from all members
        group.members.filter(is_group_leader=True).update(is_group_leader=False)
        
        # Set new leader
        member.is_group_leader = True
        member.save()
        
        return Response({
            "detail": f"{member.name} is now group leader.",
            "group": self.get_serializer(group).data
        })


class BundleAssignmentViewSet(viewsets.ModelViewSet):
    """Bundle -> Operator lifecycle: ASSIGNED -> IN_PROGRESS -> COMPLETED -> QUALITY_CHECKED.
    Production Supervisors/Admins manage assignments for everyone; an
    Operator can only act on their own assignments via `my/`, `complete/`,
    and `quality_check/` (self-reported progress)."""
    queryset = BundleAssignment.objects.select_related("bundle", "operator").all().order_by("-created_at")
    serializer_class = BundleAssignmentSerializer
    required_roles = ["ADMIN", "PRODUCTION_SUPERVISOR"]
    filterset_fields = ["status", "operator", "bundle", "shortage_reason_status"]

    def get_permissions(self):
        if self.action in ("my", "start", "return_bundle", "quality_check"):
            return [IsAuthenticated()]
        if self.action == "pay_pieces":
            # Accounts pays operators piece-by-piece.
            self.required_roles = ["ADMIN", "ACCOUNTS", "PRODUCTION_SUPERVISOR"]
        return [ReadOnlyOrHasRole()]

    @action(detail=False, methods=["get"])
    def work_summary(self, request):
        """Complete piece-level work + pay breakdown for one operator.
        Query: ?operator=<id>. Returns every completed bundle (order, product,
        size, pieces completed / paid / pending, rate, amounts), the bundles
        still in progress, and roll-up totals -- so Accounts can pay specific
        pieces and see exactly what's paid, pending or still being worked."""
        op_id = request.query_params.get("operator")
        if not op_id:
            return Response({"detail": "operator is required."}, status=400)
        qs = self.get_queryset().filter(operator_id=op_id)
        done = qs.filter(status__in=[BundleAssignment.Status.COMPLETED, BundleAssignment.Status.QUALITY_CHECKED])
        in_prog = qs.filter(status__in=[BundleAssignment.Status.ASSIGNED, BundleAssignment.Status.IN_PROGRESS, BundleAssignment.Status.RETURNED])
        completed = self.get_serializer(done, many=True).data
        in_progress = self.get_serializer(in_prog, many=True).data
        return Response({
            "completed": completed,
            "in_progress": in_progress,
            "totals": {
                "pieces_completed": sum(r["returned_quantity"] or 0 for r in completed),
                "pieces_paid": sum(r["paid_quantity"] or 0 for r in completed),
                "pieces_pending": sum(r["pending_quantity"] for r in completed),
                "pieces_in_progress": sum((r["issued_quantity"] or 0) for r in in_progress),
                "amount_earned": round(sum(r["earned_amount"] for r in completed), 2),
                "amount_paid": round(sum(r["paid_amount"] for r in completed), 2),
                "amount_pending": round(sum(r["pending_amount"] for r in completed), 2),
            },
        })

    @action(detail=True, methods=["post"])
    def pay_pieces(self, request, pk=None):
        """Pay specific completed pieces on this bundle. Body: {quantity}
        (defaults to all pending). Marks the pieces paid and books an
        OperatorIncome record for rate x pieces."""
        a = self.get_object()
        if a.status not in (BundleAssignment.Status.COMPLETED, BundleAssignment.Status.QUALITY_CHECKED):
            return Response({"detail": "Only completed / quality-checked pieces can be paid."}, status=400)
        pending = max((a.returned_quantity or 0) - (a.paid_quantity or 0), 0)
        if pending <= 0:
            return Response({"detail": "Nothing pending to pay on this bundle."}, status=400)
        raw = request.data.get("quantity")
        try:
            qty = pending if raw in (None, "") else int(raw)
        except (TypeError, ValueError):
            return Response({"detail": "quantity must be a whole number."}, status=400)
        if qty <= 0 or qty > pending:
            return Response({"detail": f"quantity must be between 1 and {pending} (pending)."}, status=400)
        rate = Decimal(a.rate_per_piece or 0)
        amount = rate * qty
        a.paid_quantity = (a.paid_quantity or 0) + qty
        a.save(update_fields=["paid_quantity", "updated_at"])
        co = a.bundle.cutting_order
        onum = co.order.order_number if (co and co.order_id) else ""
        today = date.today()
        income = OperatorIncome.objects.create(
            operator=a.operator, period_start=today, period_end=today,
            bundles_completed=1, pieces_completed=qty, rate_applied=rate,
            total_income=amount, paid_amount=amount,
            payment_status=OperatorIncome.PaymentStatus.PAID, payment_date=today,
            remarks=f"Paid {qty} pc(s) of bundle {a.bundle.bundle_number}" + (f" (order {onum})" if onum else ""),
        )
        return Response({"paid": qty, "amount": float(amount), "income": income.id,
                         "assignment": self.get_serializer(a).data})

    def _check_owns_assignment(self, request, assignment):
        if request.user.role == "ADMIN" or request.user.role == "PRODUCTION_SUPERVISOR":
            return
        own_operator = get_own_operator(request)
        if request.user.role == "OPERATOR" and own_operator and assignment.operator_id == own_operator.id:
            return
        raise PermissionDenied("You can only act on your own assigned bundles.")

    @action(detail=False, methods=["get"])
    def my(self, request):
        """Operator self-service: bundles currently assigned to me."""
        own_operator = get_own_operator(request)
        if not own_operator:
            return Response([])
        qs = self.get_queryset().filter(operator=own_operator)
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        assignment = self.get_object()
        self._check_owns_assignment(request, assignment)
        if assignment.status != BundleAssignment.Status.ASSIGNED:
            return Response({"detail": "Only a freshly-assigned bundle can be started."}, status=400)
        assignment.status = BundleAssignment.Status.IN_PROGRESS
        assignment.save(update_fields=["status"])
        assignment.bundle.status = Bundle.Status.IN_PROGRESS
        assignment.bundle.save(update_fields=["status"])
        return Response(self.get_serializer(assignment).data)

    @action(detail=True, methods=["post"], url_path="return")
    def return_bundle(self, request, pk=None):
        """Operator (or a supervisor entering on their behalf) returns
        pieces. A shortfall requires a reason and sits at RETURNED --
        pending Admin review -- until resolved; no shortfall finalizes
        (accepts) the assignment immediately."""
        assignment = self.get_object()
        self._check_owns_assignment(request, assignment)
        returned_quantity = request.data.get("returned_quantity")
        if returned_quantity is None:
            return Response({"detail": "returned_quantity is required."}, status=400)
        returned_quantity = int(returned_quantity)
        issued_quantity = assignment.issued_quantity or assignment.bundle.quantity
        if returned_quantity < 0 or returned_quantity > issued_quantity:
            return Response({"detail": f"returned_quantity must be between 0 and {issued_quantity} (issued)."}, status=400)

        # Return date: defaults to today, may be a future date, never a past one.
        return_date = request.data.get("return_date")
        completion = date.today()
        if return_date:
            try:
                completion = date.fromisoformat(str(return_date))
            except ValueError:
                return Response({"detail": "return_date must be a valid date (YYYY-MM-DD)."}, status=400)
            if completion < date.today():
                return Response({"detail": "return_date cannot be in the past."}, status=400)

        assignment.returned_quantity = returned_quantity
        assignment.completion_date = completion   # record when the pieces came back
        shortage = issued_quantity - returned_quantity
        if shortage <= 0:
            assignment.shortage_reason_status = BundleAssignment.ShortageStatus.NOT_APPLICABLE
            assignment.status = BundleAssignment.Status.COMPLETED
            assignment.bundle.status = Bundle.Status.COMPLETED
            assignment.bundle.save(update_fields=["status"])
        else:
            shortage_reason = request.data.get("shortage_reason")
            if not shortage_reason:
                return Response({"detail": "shortage_reason is required when returned pieces are fewer than issued."}, status=400)
            assignment.shortage_reason = shortage_reason
            assignment.shortage_reason_status = BundleAssignment.ShortageStatus.PENDING_REVIEW
            assignment.status = BundleAssignment.Status.RETURNED
        assignment.save(update_fields=[
            "returned_quantity", "shortage_reason", "shortage_reason_status", "status", "completion_date",
        ])
        return Response(self.get_serializer(assignment).data)

    @action(detail=True, methods=["post"])
    def quality_check(self, request, pk=None):
        assignment = self.get_object()
        # Quality checks are recorded by supervisors/admins, not by the operator themselves.
        if request.user.role not in ("ADMIN", "PRODUCTION_SUPERVISOR"):
            raise PermissionDenied("Only a Production Supervisor can record a quality check.")
        # Decoupled from shortage-review status: QC is about garment quality
        # on the pieces actually returned, not an accounting dispute -- it
        # must not stall behind a pending Admin shortage decision.
        if assignment.returned_quantity is None:
            return Response({"detail": "The operator hasn't returned any pieces to quality-check yet."}, status=400)
        passed = request.data.get("passed", True)
        defects = int(request.data.get("defects", 0) or 0)
        defect_reason = request.data.get("defect_reason", "")
        if defects > 0 and not defect_reason:
            return Response({"detail": "defect_reason is required when defects > 0."}, status=400)
        assignment.quality_check_passed = passed
        assignment.defects = defects
        assignment.defect_reason = defect_reason
        assignment.status = BundleAssignment.Status.QUALITY_CHECKED if passed else assignment.status
        assignment.save(update_fields=["quality_check_passed", "defects", "defect_reason", "status"])
        if passed:
            assignment.bundle.status = Bundle.Status.QUALITY_CHECKED
            assignment.bundle.save(update_fields=["status"])
        return Response(self.get_serializer(assignment).data)

    @action(detail=True, methods=["post"])
    def review_shortage(self, request, pk=None):
        """Admin-only: resolves a pending shortage reason, either way
        finalizing (accepting) the assignment -- while PENDING_REVIEW, the
        returned pieces are not yet considered accepted."""
        if not (request.user.is_superuser or request.user.role == "ADMIN"):
            raise PermissionDenied("Only an Admin can review a shortage reason.")
        assignment = self.get_object()
        if assignment.shortage_reason_status != BundleAssignment.ShortageStatus.PENDING_REVIEW:
            return Response({"detail": "This assignment has no pending shortage review."}, status=400)
        approved = bool(request.data.get("approved"))
        assignment.shortage_reviewed_by = request.user
        assignment.shortage_reviewed_at = timezone.now()
        assignment.shortage_review_notes = request.data.get("notes", "")
        assignment.shortage_reason_status = (
            BundleAssignment.ShortageStatus.APPROVED if approved else BundleAssignment.ShortageStatus.REJECTED
        )
        assignment.status = BundleAssignment.Status.COMPLETED
        assignment.completion_date = date.today()
        assignment.save(update_fields=[
            "shortage_reviewed_by", "shortage_reviewed_at", "shortage_review_notes",
            "shortage_reason_status", "status", "completion_date",
        ])
        assignment.bundle.status = Bundle.Status.COMPLETED
        assignment.bundle.save(update_fields=["status"])
        return Response(self.get_serializer(assignment).data)

    @action(detail=True, methods=["post"])
    def reassign(self, request, pk=None):
        """Fail-safe: create a fresh assignment for a different operator,
        keeping this record's history (e.g. after a failed quality check)."""
        assignment = self.get_object()
        new_operator_id = request.data.get("operator")
        if not new_operator_id:
            return Response({"operator": "Required."}, status=status.HTTP_400_BAD_REQUEST)
        new_assignment = BundleAssignment.objects.create(
            bundle=assignment.bundle,
            operator_id=new_operator_id,
            assigned_by=request.user,
            remarks=f"Reassigned from assignment #{assignment.id}",
        )
        assignment.bundle.status = Bundle.Status.ASSIGNED
        assignment.bundle.save(update_fields=["status"])
        return Response(self.get_serializer(new_assignment).data, status=status.HTTP_201_CREATED)


class OperatorIncomeViewSet(viewsets.ModelViewSet):
    """Income = Bundles Completed x Rate/Bundle + Pieces Completed x Rate/Piece."""
    queryset = OperatorIncome.objects.select_related("operator").all()
    serializer_class = OperatorIncomeSerializer
    required_roles = ["ADMIN", "ACCOUNTS", "PRODUCTION_SUPERVISOR"]
    filterset_fields = ["operator", "payment_status"]

    def get_permissions(self):
        if self.action == "my":
            return [IsAuthenticated()]
        return [ReadOnlyOrHasRole()]

    @action(detail=False, methods=["get"])
    def my(self, request):
        """Operator self-service: my own earnings history."""
        own_operator = get_own_operator(request)
        if not own_operator:
            return Response([])
        qs = self.get_queryset().filter(operator=own_operator)
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=False, methods=["post"])
    def calculate(self, request):
        """
        Body: {operator, period_start, period_end}
        Sums completed/quality-checked assignments in that window. The
        operator is paid the per-piece rate Production set on the bundle
        assignment (BundleAssignment.rate_per_piece) times the pieces they
        actually returned -- e.g. 29 pieces returned at a rate of 250/pc
        earns 29 x 250 = 7,250. Computed via the shared assignment_labor_cost
        helper the per-order P&L view also uses, so the two never drift.
        """
        operator_id = request.data.get("operator")
        period_start = request.data.get("period_start")
        period_end = request.data.get("period_end")
        if not all([operator_id, period_start, period_end]):
            return Response({"detail": "operator, period_start, period_end are required."}, status=400)

        operator = Operator.objects.get(pk=operator_id)
        assignments = BundleAssignment.objects.filter(
            operator=operator,
            status__in=[BundleAssignment.Status.COMPLETED, BundleAssignment.Status.QUALITY_CHECKED],
            completion_date__range=[period_start, period_end],
        ).select_related("bundle__cutting_order__order_item")

        bundles_completed = assignments.count()
        # Real accepted output -- what the operator actually returned and
        # had accepted -- not the bundle's nominal size (which ignores any shortage).
        pieces_completed = assignments.aggregate(p=Sum("returned_quantity"))["p"] or 0

        total_income = Decimal("0")
        last_rate_applied = Decimal("0")
        for assignment in assignments:
            total_income += assignment_labor_cost(assignment)
            rate = order_piece_rate(assignment)
            if rate:
                last_rate_applied = rate

        income = OperatorIncome.objects.create(
            operator=operator,
            period_start=period_start,
            period_end=period_end,
            bundles_completed=bundles_completed,
            pieces_completed=pieces_completed,
            rate_applied=last_rate_applied,
            total_income=total_income,
        )
        return Response(self.get_serializer(income).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def mark_paid(self, request, pk=None):
        """Body: {amount} (optional) -- partial payment; omit for full
        settlement of whatever remains due."""
        income = self.get_object()
        amount = request.data.get("amount")
        remaining = income.total_income - income.paid_amount
        amount = Decimal(str(amount)) if amount is not None else remaining
        if amount <= 0 or amount > remaining:
            return Response({"detail": f"amount must be between 0 and {remaining} (remaining)."}, status=400)
        income.paid_amount += amount
        income.payment_date = date.today()
        income.payment_status = (
            OperatorIncome.PaymentStatus.PAID if income.paid_amount >= income.total_income
            else OperatorIncome.PaymentStatus.PARTIALLY_PAID
        )
        income.save(update_fields=["paid_amount", "payment_status", "payment_date"])
        return Response(self.get_serializer(income).data)
