"""
Enterprise Reporting Engine — Celery Tasks
Handles scheduled report execution and email delivery.
"""

from celery import shared_task
from django.core.mail import EmailMessage
from django.utils import timezone


@shared_task(bind=True, max_retries=3)
def run_scheduled_report(self, schedule_id: str):
    """Execute a scheduled report and email the results."""
    import io

    from .models import ReportExecution, ScheduledReport
    from .services import get_data

    try:
        schedule = ScheduledReport.objects.select_related("report__created_by").get(
            id=schedule_id
        )
    except ScheduledReport.DoesNotExist:
        return f"Schedule {schedule_id} not found."

    if not schedule.is_active:
        return f"Schedule {schedule_id} is inactive."

    report = schedule.report
    execution = ReportExecution.objects.create(
        report=report,
        schedule=schedule,
        status="running",
        export_format=schedule.export_format,
    )

    try:
        # Fetch data
        data = get_data(
            module=report.module,
            company_id=report.company_id,
            columns=report.columns,
            filters=report.filters,
            sort_by=report.sort_by,
            limit=5000,
        )

        fmt = schedule.export_format
        filename = (
            f"{report.name.replace(' ', '_')}_{timezone.now().strftime('%Y%m%d')}"
        )

        # Generate the file bytes
        if fmt == "csv":
            import csv as csv_mod

            output = io.StringIO()
            if data:
                writer = csv_mod.DictWriter(output, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
            file_content = output.getvalue().encode("utf-8")
            mime_type = "text/csv"
            full_filename = filename + ".csv"

        elif fmt == "xlsx":
            import openpyxl

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = report.name[:30]
            if data:
                headers = list(data[0].keys())
                ws.append([h.replace("_", " ").title() for h in headers])
                for row in data:
                    ws.append([row.get(h, "") for h in headers])
            buf = io.BytesIO()
            wb.save(buf)
            file_content = buf.getvalue()
            mime_type = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            full_filename = filename + ".xlsx"

        else:  # pdf
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import inch
            from reportlab.platypus import (
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )

            buf = io.BytesIO()
            doc = SimpleDocTemplate(buf, pagesize=landscape(A4))
            styles = getSampleStyleSheet()
            story = [Paragraph(report.name, styles["Title"]), Spacer(1, 0.2 * inch)]
            if data:
                headers = list(data[0].keys())
                table_data = [[h.replace("_", " ").title() for h in headers]]
                for row in data[:500]:
                    table_data.append([str(row.get(h, "")) for h in headers])
                col_width = (landscape(A4)[0] - inch) / max(len(headers), 1)
                t = Table(
                    table_data, colWidths=[col_width] * len(headers), repeatRows=1
                )
                t.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                            ("FONTSIZE", (0, 1), (-1, -1), 8),
                        ]
                    )
                )
                story.append(t)
            doc.build(story)
            file_content = buf.getvalue()
            mime_type = "application/pdf"
            full_filename = filename + ".pdf"

        # Send email
        subject = schedule.subject or f"Scheduled Report: {report.name}"
        body = (
            schedule.body
            or f"Please find the attached report: {report.name}\n\nGenerated: {timezone.now().strftime('%Y-%m-%d %H:%M')}"
        )

        email = EmailMessage(
            subject=subject,
            body=body,
            to=schedule.get_recipients_list(),
        )
        email.attach(full_filename, file_content, mime_type)
        email.send()

        # Update execution log
        execution.status = "success"
        execution.row_count = len(data)
        execution.completed_at = timezone.now()
        execution.save(update_fields=["status", "row_count", "completed_at"])

        # Update schedule timestamps
        schedule.last_run = timezone.now()
        schedule.save(update_fields=["last_run"])

        return f"Report '{report.name}' sent to {schedule.recipients}"

    except Exception as exc:
        execution.status = "failed"
        execution.error_message = str(exc)
        execution.completed_at = timezone.now()
        execution.save(update_fields=["status", "error_message", "completed_at"])
        raise self.retry(exc=exc, countdown=60)
