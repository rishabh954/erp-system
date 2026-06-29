import csv
from django.http import HttpResponse

class ExportService:
    @staticmethod
    def export_csv(queryset, filename, fields=None):
        """
        Generic CSV export service.
        If fields is None, exports all model fields.
        """
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
        
        writer = csv.writer(response)
        
        if not queryset.exists():
            return response
            
        model = queryset.model
        if not fields:
            fields = [f.name for f in model._meta.fields]
            
        # Write headers
        writer.writerow([f.replace('_', ' ').title() for f in fields])
        
        # Write data
        for obj in queryset:
            row = []
            for field in fields:
                val = getattr(obj, field, '')
                # Handle callable fields or properties
                if callable(val):
                    try:
                        val = val()
                    except Exception:
                        pass
                row.append(str(val) if val is not None else '')
            writer.writerow(row)
            
        return response
