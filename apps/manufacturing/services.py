from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from apps.inventory.models import Product, StockRecord

from .models import ManufacturingOrder, MaterialPlan, MaterialPlanItem


class MRPService:
    @staticmethod
    @transaction.atomic
    def run_mrp(plan_id, company_id):
        plan = (
            MaterialPlan.objects.select_for_update()
            .filter(id=plan_id, company_id=company_id, is_deleted=False)
            .first()
        )
        if plan is None:
            raise ValueError("Material plan was not found for this company.")
        company = plan.company

        # Clear existing items
        plan.items.filter(plan__company=company).delete()

        # 1. Get all Confirmed or In Progress MOs up to target_date
        mos = ManufacturingOrder.objects.filter(
            company=company,
            bom__company=company,
            product__company=company,
            status__in=[
                ManufacturingOrder.Status.CONFIRMED,
                ManufacturingOrder.Status.IN_PROGRESS,
            ],
            planned_start_date__lte=plan.target_date,
        ).select_related("bom")

        # 2. Aggregate raw material requirements
        requirements = {}  # product_id -> Decimal qty
        for mo in mos:
            remaining_mo_qty = Decimal(mo.quantity_to_produce) - Decimal(
                mo.quantity_produced
            )
            if remaining_mo_qty <= 0:
                continue

            for line in mo.bom.lines.filter(
                bom__company=company, component__company=company
            ):
                comp_id = line.component_id
                qty_per_mo = Decimal(line.quantity) / Decimal(mo.bom.quantity)
                req_qty = qty_per_mo * remaining_mo_qty

                if line.scrap_percentage > 0:
                    req_qty += req_qty * (Decimal(line.scrap_percentage) / Decimal(100))

                if comp_id in requirements:
                    requirements[comp_id] += req_qty
                else:
                    requirements[comp_id] = req_qty

        # 3. Compare with on-hand inventory
        for comp_id, req_qty in requirements.items():
            product = Product.objects.get(id=comp_id, company=company)

            # Get available quantity across all warehouses for this company
            on_hand = StockRecord.objects.filter(
                company=company,
                product=product,
                warehouse__company=company,
                is_deleted=False,
            ).aggregate(total=Sum("quantity_on_hand"))["total"]
            available = Decimal(on_hand) if on_hand else Decimal(0)

            shortage = req_qty - available
            if shortage < 0:
                shortage = Decimal(0)

            if req_qty > 0 or shortage > 0:
                MaterialPlanItem.objects.create(
                    plan=plan,
                    product=product,
                    required_quantity=req_qty,
                    available_quantity=available,
                    shortage=shortage,
                    planned_order_date=plan.target_date,  # Simplification: order it all for the target date
                )

        plan.status = MaterialPlan.Status.COMPLETED
        plan.save(update_fields=["status"])
        return plan
