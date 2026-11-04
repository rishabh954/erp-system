import json
import logging
from decimal import Decimal, InvalidOperation

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.views import View

from apps.company.views import CompanyMixin
from apps.inventory.models import Product, ProductCategory, StockMovement, Warehouse
from apps.pos.models import POSOrder, POSOrderLine, POSPayment, POSSession

logger = logging.getLogger(__name__)


def _to_decimal(value, field_name, *, max_digits=15, decimal_places=4):
    try:
        amount = forms.DecimalField(
            max_digits=max_digits, decimal_places=decimal_places
        ).clean(value)
    except (ValidationError, InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid decimal amount.") from exc
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
            company=self.company(),
            user=request.user,
            status=POSSession.Status.OPEN,
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
            if not isinstance(data, dict):
                raise ValueError("Request body must be a JSON object.")
            session_id = data.get("session_id")
            cart = data.get("cart", [])
            payment_method = data.get(
                "payment_method", POSPayment.PaymentMethod.CASH
            )
            tendered = _to_decimal(
                data.get("tendered", 0),
                "Tendered amount",
                max_digits=15,
                decimal_places=2,
            )
            if payment_method not in POSPayment.PaymentMethod.values:
                raise ValueError("Select a valid payment method.")
            if not isinstance(cart, list):
                raise ValueError("Cart must be a list of items.")
            if not cart:
                raise ValueError("Cart is empty.")

            session = POSSession.objects.get(
                id=session_id,
                company=self.company(),
                user=request.user,
                status=POSSession.Status.OPEN,
            )

            prepared_items = []
            subtotal = Decimal("0")
            tax_total = Decimal("0")
            for index, item in enumerate(cart):
                if not isinstance(item, dict):
                    raise ValueError(f"Cart item {index + 1} is invalid.")
                product = Product.objects.select_related("tax").get(
                    id=item.get("id"),
                    company=self.company(),
                    is_active=True,
                    is_sellable=True,
                    is_deleted=False,
                )
                qty = _to_decimal(item.get("qty"), "Quantity")
                submitted_price = _to_decimal(
                    item.get("price"),
                    "Unit price",
                    max_digits=15,
                    decimal_places=2,
                )
                price = product.sale_price.quantize(Decimal("0.01"))
                if qty <= 0:
                    raise ValueError("Quantity must be greater than zero.")
                if submitted_price != price:
                    raise ValueError(
                        f"Price for {product.name} does not match the current product price."
                    )
                tax = product.tax if product.tax and product.tax.is_active else None
                if product.tax_id and tax is None:
                    raise ValueError(
                        f"Product {product.name} has an inactive tax configured."
                    )
                if tax and tax.company_id != self.company().pk:
                    raise ValueError(
                        f"Product {product.name} has a tax configured for another company."
                    )
                line_subtotal = (qty * price).quantize(Decimal("0.01"))
                line_tax = tax.compute(line_subtotal) if tax else Decimal("0")
                subtotal += line_subtotal
                tax_total += line_tax
                prepared_items.append((product, qty, price, line_subtotal, line_tax))

            total = subtotal + tax_total
            if payment_method == POSPayment.PaymentMethod.CASH:
                if tendered < total:
                    raise ValueError("Tendered amount cannot be less than the total.")
                change = tendered - total
            else:
                if tendered < total:
                    raise ValueError("Tendered amount cannot be less than the total.")
                if tendered > total:
                    raise ValueError("Non-cash payment cannot exceed the total.")
                change = Decimal("0")

            with transaction.atomic():
                order = POSOrder.objects.create(
                    company=self.company(),
                    session=session,
                    status=POSOrder.Status.PAID,
                    subtotal=subtotal,
                    tax_amount=tax_total,
                    total=total,
                )

                for product, qty, price, line_subtotal, line_tax in prepared_items:
                    POSOrderLine.objects.create(
                        order=order,
                        product=product,
                        quantity=qty,
                        unit_price=price,
                        subtotal=line_subtotal,
                        tax_amount=line_tax,
                        discount_amount=Decimal("0"),
                    )

                    from apps.inventory.services import StockService

                    StockService(company=self.company(), user=request.user).adjust_stock(
                        product=product,
                        warehouse=session.warehouse,
                        qty_input=qty,
                        adjustment_type="remove",
                        movement_type=StockMovement.MovementType.DELIVERY,
                        reference_type="POSOrder",
                        reference_id=str(order.id),
                    )

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
        except (ValidationError, ValueError) as exc:
            return JsonResponse(
                {"status": "error", "message": str(exc)}, status=400
            )
        except Product.DoesNotExist:
            return JsonResponse(
                {"status": "error", "message": "A product in the cart was not found."},
                status=400,
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
