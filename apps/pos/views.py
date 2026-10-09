import json
import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.views import View

from apps.company.views import CompanyMixin
from apps.inventory.models import Product, ProductCategory, StockMovement, Warehouse
from apps.pos.models import POSOrder, POSOrderLine, POSPayment, POSSession

logger = logging.getLogger(__name__)


def _to_decimal(value, field_name):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid decimal amount.") from exc
    if not amount.is_finite():
        raise ValueError(f"{field_name} must be a finite decimal amount.")
    return amount


class POSIndexView(CompanyMixin, View):
    required_permission = "pos.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "pos.create"
            elif request.method in ["PUT", "PATCH"]:
                return "pos.update"
            elif request.method == "DELETE":
                return "pos.delete"
        return self.required_permission
    def get(self, request, *args, **kwargs):
        # Ensure there is an open session for the user
        session = POSSession.objects.filter(
            user=request.user, status=POSSession.Status.OPEN
        ).first()
        if not session:
            # For simplicity, auto-create a session if there's a warehouse
            warehouse = Warehouse.objects.filter(company=self.company()).first()
            if not warehouse:
                # You'd typically show an error, but let's pass a flag
                return render(
                    request,
                    "sales/pos.html",
                    {"error": "No warehouse configured for this company."},
                )

            session = POSSession.objects.create(
                company=self.company(),
                user=request.user,
                warehouse=warehouse,
                starting_cash=0,
            )

        categories = ProductCategory.objects.filter(company=self.company())
        products = Product.objects.filter(
            company=self.company(), is_active=True
        ).select_related("category")

        # Serialize for frontend
        products_data = []
        for p in products:
            products_data.append(
                {
                    "id": str(p.id),
                    "name": p.name,
                    "price": str(p.sale_price),
                    "sale_price": str(p.sale_price),
                    "sku": p.sku,
                    "category_id": str(p.category.id) if p.category else None,
                    "image_url": p.image.url if p.image else None,
                }
            )

        context = {
            "session": session,
            "categories": categories,
            "products_json": json.dumps(products_data),
        }
        return render(request, "sales/pos.html", context)


class POSCheckoutAPIView(CompanyMixin, View):
    required_permission = "pos.create"
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            session_id = data.get("session_id")
            cart = data.get("cart", [])
            payment_method = data.get("payment_method", "cash")
            tendered = _to_decimal(data.get("tendered", 0), "Tendered amount")
            if tendered < 0:
                raise ValueError("Tendered amount cannot be negative.")

            if not cart:
                return JsonResponse(
                    {"status": "error", "message": "Cart is empty."}, status=400
                )

            session = POSSession.objects.get(
                id=session_id, user=request.user, status=POSSession.Status.OPEN
            )

            with transaction.atomic():
                # 1. Create Order
                subtotal = sum(
                    (
                        _to_decimal(item["price"], "Unit price")
                        * _to_decimal(item["qty"], "Quantity")
                        for item in cart
                    ),
                    Decimal("0"),
                )
                total = subtotal
                change = (
                    max(Decimal("0"), tendered - total)
                    if payment_method == "cash"
                    else Decimal("0")
                )

                order = POSOrder.objects.create(
                    company=self.company(),
                    session=session,
                    status=POSOrder.Status.PAID,
                    subtotal=subtotal,
                    total=total,
                )

                # 2. Create Lines & Deduct Stock
                from django.utils import timezone

                for item in cart:
                    product = Product.objects.get(id=item["id"], company=self.company())
                    qty = _to_decimal(item["qty"], "Quantity")
                    price = _to_decimal(item["price"], "Unit price")
                    if qty <= 0 or price < 0:
                        raise ValueError(
                            "Quantity must be positive and unit price cannot be negative."
                        )

                    POSOrderLine.objects.create(
                        order=order,
                        product=product,
                        quantity=qty,
                        unit_price=price,
                        subtotal=qty * price,
                    )

                    # Deduct Stock (wrap in try so a missing warehouse doesn't kill the sale)
                    try:
                        StockMovement.objects.create(
                            company=self.company(),
                            product=product,
                            warehouse=session.warehouse,
                            quantity=-qty,
                            movement_type=StockMovement.MovementType.DELIVERY,
                            movement_date=timezone.now().date(),
                            reference_type="POSOrder",
                            reference_id=str(order.id),
                        )
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning("Stock deduction failed: %s", e)

                # 3. Record Payment
                POSPayment.objects.create(
                    order=order,
                    method=payment_method,
                    amount=total,
                    tendered=tendered,
                    change=change,
                )

            return JsonResponse(
                {"status": "success", "order_number": order.number, "change": change}
            )

        except POSSession.DoesNotExist:
            return JsonResponse(
                {
                    "status": "error",
                    "message": "POS Session not found or already closed.",
                },
                status=400,
            )
        except Product.DoesNotExist:
            return JsonResponse(
                {"status": "error", "message": "A product in the cart was not found."},
                status=400,
            )
        except ValueError as exc:
            return JsonResponse(
                {"status": "error", "message": str(exc)}, status=400
            )
        except Exception:
            logger.error("POS checkout failed", exc_info=True)
            return JsonResponse(
                {
                    "status": "error",
                    "message": "Transaction failed",
                    "error": "An unexpected error occurred."
                },
                status=500,
            )
