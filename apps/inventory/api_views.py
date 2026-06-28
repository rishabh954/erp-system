import json
from django.db import models
from django.http import JsonResponse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Product, StockRecord

class BarcodeScanAPIView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            barcode = data.get('barcode', '').strip()
            
            if not barcode:
                return JsonResponse({'success': False, 'error': 'Barcode is required'}, status=400)
                
            company = request.user.primary_company
            
            # 1. Check Product Barcode or SKU
            product = Product.objects.filter(company=company, is_active=True).filter(
                models.Q(barcode=barcode) | models.Q(sku=barcode)
            ).first()
            
            if product:
                return JsonResponse({
                    'success': True,
                    'type': 'product',
                    'data': {
                        'id': str(product.pk),
                        'sku': product.sku,
                        'name': product.name,
                        'total_stock': float(product.total_stock)
                    }
                })
                
            # 2. Check Stock Record Batch/Serial/Barcode
            stock_record = StockRecord.objects.filter(
                product__company=company
            ).filter(
                models.Q(barcode=barcode) | 
                models.Q(batch_number=barcode) | 
                models.Q(serial_number=barcode)
            ).first()
            
            if stock_record:
                return JsonResponse({
                    'success': True,
                    'type': 'stock_record',
                    'data': {
                        'id': str(stock_record.pk),
                        'product_sku': stock_record.product.sku,
                        'product_name': stock_record.product.name,
                        'warehouse': stock_record.warehouse.name,
                        'bin_location': stock_record.bin_location.name if stock_record.bin_location else None,
                        'quantity_on_hand': float(stock_record.quantity_on_hand)
                    }
                })
                
            return JsonResponse({'success': False, 'error': 'Barcode not found'}, status=404)
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
