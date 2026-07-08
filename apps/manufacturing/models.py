import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CompanyScoped, NotesMixin, SequenceMixin


class WorkCenter(CompanyScoped, NotesMixin):
    """A manufacturing workstation or machine."""

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50)
    cost_per_hour = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text=_("Operating cost per hour for landed cost calculation"),
    )
    capacity = models.PositiveIntegerField(
        default=1, help_text=_("Number of simultaneous operations")
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "manufacturing_work_centers"
        unique_together = ("company", "code")
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class Routing(CompanyScoped, NotesMixin):
    """A sequence of operations to manufacture a product."""

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "manufacturing_routings"
        unique_together = ("company", "code")
        ordering = ["name"]

    def __str__(self):
        return self.name


class RoutingOperation(models.Model):
    """An individual step in a routing."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    routing = models.ForeignKey(
        Routing, on_delete=models.CASCADE, related_name="operations"
    )
    work_center = models.ForeignKey(WorkCenter, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    sequence = models.PositiveIntegerField(default=10)
    duration_minutes = models.PositiveIntegerField(default=0)
    instructions = models.TextField(blank=True)

    class Meta:
        db_table = "manufacturing_routing_operations"
        ordering = ["sequence"]

    def __str__(self):
        return f"{self.sequence}: {self.name} at {self.work_center.name}"


class BillOfMaterial(CompanyScoped, SequenceMixin, NotesMixin):
    """The recipe to assemble a product."""

    product = models.ForeignKey(
        "inventory.Product",
        on_delete=models.CASCADE,
        related_name="boms",
        help_text=_("The finished product"),
    )
    routing = models.ForeignKey(
        Routing, null=True, blank=True, on_delete=models.SET_NULL
    )
    quantity = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        default=1,
        help_text=_("Quantity of finished product this BOM produces"),
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "manufacturing_boms"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number("BOM", self.__class__)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"BOM: {self.product.name} ({self.quantity})"


class BillOfMaterialLine(models.Model):
    """A component required in a BOM."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bom = models.ForeignKey(
        BillOfMaterial, on_delete=models.CASCADE, related_name="lines"
    )
    component = models.ForeignKey(
        "inventory.Product",
        on_delete=models.PROTECT,
        help_text=_("Raw material or subassembly"),
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=4, default=1)
    scrap_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        db_table = "manufacturing_bom_lines"
        ordering = ["id"]

    def __str__(self):
        return f"{self.quantity} x {self.component.name}"


class ManufacturingOrder(CompanyScoped, SequenceMixin, NotesMixin):
    """A production order to build finished goods."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        CONFIRMED = "confirmed", _("Confirmed")
        IN_PROGRESS = "in_progress", _("In Progress")
        DONE = "done", _("Done")
        CANCELLED = "cancelled", _("Cancelled")

    product = models.ForeignKey(
        "inventory.Product",
        on_delete=models.PROTECT,
        related_name="manufacturing_orders",
    )
    bom = models.ForeignKey(BillOfMaterial, on_delete=models.PROTECT)
    quantity_to_produce = models.DecimalField(
        max_digits=15, decimal_places=4, default=1
    )
    quantity_produced = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    planned_start_date = models.DateField(null=True, blank=True)
    planned_end_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )

    # Traceability links
    warehouse = models.ForeignKey(
        "inventory.Warehouse",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text=_("Where finished goods will be stored and raw materials consumed"),
    )

    class Meta:
        db_table = "manufacturing_orders"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number("MO", self.__class__)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} | {self.product.name} ({self.quantity_to_produce})"

    def confirm(self):
        if self.status == self.Status.DRAFT:
            self.status = self.Status.CONFIRMED
            self.save(update_fields=["status"])
            # Generate Work Orders if a routing is present
            if self.bom.routing:
                for op in self.bom.routing.operations.all():
                    WorkOrder.objects.create(
                        company=self.company,
                        manufacturing_order=self,
                        operation=op,
                        work_center=op.work_center,
                        name=op.name,
                        expected_duration_minutes=op.duration_minutes
                        * self.quantity_to_produce,
                    )

    def mark_done(self):
        if self.status in [self.Status.CONFIRMED, self.Status.IN_PROGRESS]:
            self.status = self.Status.DONE
            self.quantity_produced = self.quantity_to_produce
            self.save(update_fields=["status", "quantity_produced"])
            self._process_inventory_transfer()

    def _process_inventory_transfer(self):
        """Automatically create inventory stock movements to consume raw materials and produce finished goods."""
        from decimal import Decimal

        from apps.inventory.models import StockMovement

        # Consume raw materials (Stock out)
        for line in self.bom.lines.all():
            qty_to_consume = Decimal(line.quantity) * (
                Decimal(self.quantity_produced) / Decimal(self.bom.quantity)
            )
            if line.scrap_percentage > 0:
                qty_to_consume += qty_to_consume * (
                    Decimal(line.scrap_percentage) / Decimal(100)
                )

            movement_out = StockMovement.objects.create(
                company=self.company,
                product=line.component,
                warehouse=self.warehouse,
                quantity=-qty_to_consume,
                movement_type=StockMovement.MovementType.PRODUCTION_OUT,
                movement_date=self.updated_at.date() if self.updated_at else None,
                reference_id=f"MO-{self.number}",
                notes=f"Consumed via BOM {self.bom.number}",
            )

        # Produce finished goods (Stock in)
        movement_in = StockMovement.objects.create(
            company=self.company,
            product=self.product,
            warehouse=self.warehouse,
            quantity=self.quantity_produced,
            movement_type=StockMovement.MovementType.PRODUCTION_IN,
            movement_date=self.updated_at.date() if self.updated_at else None,
            reference_id=f"MO-{self.number}",
            notes=f"Produced via BOM {self.bom.number}",
        )


class WorkOrder(CompanyScoped, SequenceMixin):
    """An execution step for a Manufacturing Order at a specific Work Center."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        READY = "ready", _("Ready")
        IN_PROGRESS = "in_progress", _("In Progress")
        DONE = "done", _("Done")
        CANCELLED = "cancelled", _("Cancelled")

    manufacturing_order = models.ForeignKey(
        ManufacturingOrder, on_delete=models.CASCADE, related_name="work_orders"
    )
    operation = models.ForeignKey(
        RoutingOperation, null=True, blank=True, on_delete=models.SET_NULL
    )
    work_center = models.ForeignKey(WorkCenter, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    expected_duration_minutes = models.PositiveIntegerField(default=0)
    actual_duration_minutes = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "manufacturing_work_orders"
        ordering = ["id"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number("WO", self.__class__)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} | {self.name} ({self.status})"


# ════════════════════════ SCRAP & DOWNTIME ════════════════════════════════════


class ScrapOrder(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        DONE = "done", _("Done")

    manufacturing_order = models.ForeignKey(
        ManufacturingOrder,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="scrap_orders",
    )
    work_center = models.ForeignKey(
        WorkCenter, null=True, blank=True, on_delete=models.SET_NULL
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    reason = models.CharField(max_length=255)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.DRAFT
    )

    class Meta:
        db_table = "manufacturing_scrap_orders"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number("SCRAP", self.__class__)
        super().save(*args, **kwargs)

    def mark_done(self):
        if self.status == self.Status.DRAFT:
            self.status = self.Status.DONE
            self.save(update_fields=["status"])

            # Create inventory adjustment for scrap
            from apps.inventory.models import StockMovement

            StockMovement.objects.create(
                company=self.company,
                product=self.product,
                warehouse=(
                    self.manufacturing_order.warehouse
                    if self.manufacturing_order
                    else None
                ),
                quantity=-self.quantity,
                movement_type=StockMovement.MovementType.ADJUSTMENT_OUT,
                reference_id=self.number,
                notes=f"Scrapped: {self.reason}",
            )


class DowntimeLog(CompanyScoped):
    work_center = models.ForeignKey(
        WorkCenter, on_delete=models.CASCADE, related_name="downtime_logs"
    )
    reason = models.CharField(max_length=255)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(
        default=0, help_text=_("Calculated automatically on save if end_time provided")
    )
    description = models.TextField(blank=True)

    class Meta:
        db_table = "manufacturing_downtime_logs"
        ordering = ["-start_time"]

    def save(self, *args, **kwargs):
        if self.start_time and self.end_time:
            diff = self.end_time - self.start_time
            self.duration_minutes = int(diff.total_seconds() / 60)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.work_center.name} downtime: {self.reason}"


# ════════════════════════ ADVANCED MANUFACTURING (QC, COSTING) ════════════════


class QualityCheck(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PASS = "pass", _("Pass")
        FAIL = "fail", _("Fail")

    manufacturing_order = models.ForeignKey(
        ManufacturingOrder, on_delete=models.CASCADE, related_name="quality_checks"
    )
    work_order = models.ForeignKey(
        "WorkOrder",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quality_checks",
    )
    inspector = models.ForeignKey(
        "authentication.User", null=True, blank=True, on_delete=models.SET_NULL
    )
    inspection_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING
    )
    parameters_checked = models.TextField(
        blank=True, help_text=_("Describe what was checked and the results")
    )

    class Meta:
        db_table = "manufacturing_quality_checks"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number("QC", self.__class__)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} | MO: {self.manufacturing_order.number} ({self.get_status_display()})"


class ProductionCosting(CompanyScoped):
    manufacturing_order = models.OneToOneField(
        ManufacturingOrder, on_delete=models.CASCADE, related_name="costing"
    )
    material_cost = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    labor_cost = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    overhead_cost = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    unit_cost = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        db_table = "manufacturing_production_costing"

    def calculate_costs(self):
        # Extremely simplified costing logic
        mo = self.manufacturing_order
        from decimal import Decimal

        # 1. Material Cost (sum of standard cost of BOM components)
        m_cost = Decimal(0)
        for line in mo.bom.lines.all():
            m_cost += line.quantity * Decimal(line.component.standard_price)
        self.material_cost = (
            m_cost * mo.quantity_produced
            if mo.quantity_produced
            else m_cost * mo.quantity_to_produce
        )

        # 2. Labor Cost (sum of actual duration * work center rate)
        l_cost = Decimal(0)
        for wo in mo.work_orders.all():
            hours = Decimal(wo.actual_duration_minutes) / Decimal(60)
            if hours == 0:
                hours = Decimal(wo.expected_duration_minutes) / Decimal(60)
            l_cost += hours * wo.work_center.cost_per_hour
        self.labor_cost = l_cost

        # 3. Overhead Cost (flat 10% of material + labor for demonstration)
        self.overhead_cost = (self.material_cost + self.labor_cost) * Decimal("0.10")

        self.total_cost = self.material_cost + self.labor_cost + self.overhead_cost

        if mo.quantity_produced and mo.quantity_produced > 0:
            self.unit_cost = self.total_cost / mo.quantity_produced
        else:
            self.unit_cost = self.total_cost / mo.quantity_to_produce

        self.save()

    def __str__(self):
        return f"Costing for MO: {self.manufacturing_order.number}"


# ════════════════════════ MRP & MAINTENANCE ════════════════════════════════════


class MaterialPlan(CompanyScoped, SequenceMixin):
    """An MRP run to calculate material requirements."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        COMPLETED = "completed", _("Completed")

    name = models.CharField(max_length=200)
    target_date = models.DateField(
        help_text=_("Calculate requirements up to this date")
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )

    class Meta:
        db_table = "manufacturing_material_plans"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number("MRP", self.__class__)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} | {self.name}"


class MaterialPlanItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(
        MaterialPlan, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.CASCADE)
    required_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    available_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    shortage = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    planned_order_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "manufacturing_material_plan_items"
        ordering = ["planned_order_date", "product__name"]

    def __str__(self):
        return f"{self.product.name} (Shortage: {self.shortage})"


class MaintenanceRequest(CompanyScoped, SequenceMixin):
    """Track machine breakdowns and preventive maintenance."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SCHEDULED = "scheduled", _("Scheduled")
        IN_PROGRESS = "in_progress", _("In Progress")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("High")
        CRITICAL = "critical", _("Critical")

    work_center = models.ForeignKey(
        WorkCenter, on_delete=models.CASCADE, related_name="maintenance_requests"
    )
    issue_description = models.TextField()
    priority = models.CharField(
        max_length=20, choices=Priority.choices, default=Priority.NORMAL
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    scheduled_date = models.DateField(null=True, blank=True)
    completed_date = models.DateField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    cost = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    technician = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="maintenance_tasks",
    )

    class Meta:
        db_table = "manufacturing_maintenance_requests"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number("MNT", self.__class__)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} | {self.work_center.name} ({self.get_status_display()})"
