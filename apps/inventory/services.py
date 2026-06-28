from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from .models import Product, StockMovement

class InventoryAnalyticsService:
    
    @staticmethod
    def compute_abc_analysis(company):
        """
        Compute ABC classification for all active stockable products in the company
        based on the consumption value over the past 12 months.
        A: Top 80%
        B: Next 15%
        C: Bottom 5%
        """
        one_year_ago = timezone.now().date() - timedelta(days=365)
        
        # Calculate total consumption value per product
        # Delivery, Production Out, etc. represent consumption
        consumption_types = [
            StockMovement.MovementType.DELIVERY,
            StockMovement.MovementType.PRODUCTION_OUT
        ]
        
        # We need to aggregate the absolute value of quantity * unit_cost
        # Since Delivery quantity is usually negative, we multiply by -1
        products_usage = []
        total_usage_value = Decimal('0')
        
        for product in Product.objects.filter(company=company, is_active=True, product_type=Product.ProductType.STOCKABLE):
            movements = StockMovement.objects.filter(
                product=product,
                movement_type__in=consumption_types,
                movement_date__gte=one_year_ago
            )
            
            # Since outbound movements are negative quantity, we multiply by -1 to get positive consumption
            usage = movements.aggregate(
                val=Sum(ExpressionWrapper(F('quantity') * F('unit_cost') * -1, output_field=DecimalField()))
            )['val'] or Decimal('0')
            
            if usage > 0:
                products_usage.append({'product': product, 'usage': usage})
                total_usage_value += usage
            else:
                # If no usage, automatically C
                product.abc_classification = 'C'
                product.save(update_fields=['abc_classification'])
                
        if not total_usage_value:
            return
            
        # Sort products by usage descending
        products_usage.sort(key=lambda x: x['usage'], reverse=True)
        
        cumulative_value = Decimal('0')
        
        for item in products_usage:
            cumulative_value += item['usage']
            percent = (cumulative_value / total_usage_value) * 100
            
            if percent <= 80:
                classification = 'A'
            elif percent <= 95:
                classification = 'B'
            else:
                classification = 'C'
                
            prod = item['product']
            if prod.abc_classification != classification:
                prod.abc_classification = classification
                prod.save(update_fields=['abc_classification'])
