"""
CRM Models - Leads, Customers, Pipeline
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.models import CompanyScoped, AddressMixin, ContactMixin, NotesMixin, SequenceMixin
from django.core.validators import MinValueValidator, MaxValueValidator

class Campaign(CompanyScoped, NotesMixin):
    class Status(models.TextChoices):
        PLANNING = 'planning', _('Planning')
        ACTIVE = 'active', _('Active')
        COMPLETED = 'completed', _('Completed')
        CANCELLED = 'cancelled', _('Cancelled')

    name = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNING)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    budget = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    expected_revenue = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        db_table = 'crm_campaigns'

    def __str__(self):
        return self.name

class Lead(CompanyScoped, ContactMixin, NotesMixin, SequenceMixin):

    class Status(models.TextChoices):
        NEW = 'new', _('New')
        CONTACTED = 'contacted', _('Contacted')
        QUALIFIED = 'qualified', _('Qualified')
        PROPOSAL = 'proposal', _('Proposal Sent')
        NEGOTIATION = 'negotiation', _('Negotiation')
        WON = 'won', _('Won')
        LOST = 'lost', _('Lost')

    class Source(models.TextChoices):
        WEB = 'web', _('Website')
        REFERRAL = 'referral', _('Referral')
        SOCIAL = 'social', _('Social Media')
        EMAIL = 'email', _('Email Campaign')
        COLD_CALL = 'cold_call', _('Cold Call')
        EVENT = 'event', _('Event')
        OTHER = 'other', _('Other')

    name = models.CharField(max_length=255)
    company_name = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    source = models.CharField(max_length=20, choices=Source.choices, blank=True)
    assigned_to = models.ForeignKey(
        'authentication.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='assigned_leads',
    )
    expected_revenue = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    probability = models.PositiveSmallIntegerField(default=10, validators=[MinValueValidator(0), MaxValueValidator(100)])
    expected_close_date = models.DateField(null=True, blank=True)
    lost_reason = models.TextField(blank=True)
    converted_to_customer = models.BooleanField(default=False)
    customer = models.ForeignKey('Customer', null=True, blank=True, on_delete=models.SET_NULL, related_name='leads')
    tags = models.JSONField(default=list)
    
    # Enterprise CRM additions
    is_opportunity = models.BooleanField(default=False, help_text='If True, this is considered a qualified deal/opportunity.')
    lead_score = models.IntegerField(default=0)
    campaign = models.ForeignKey(Campaign, null=True, blank=True, on_delete=models.SET_NULL, related_name='leads')

    class Meta:
        db_table = 'crm_leads'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.number} | {self.name}"

    def calculate_score(self):
        """Calculate lead score based on probability, revenue, source, and data completeness."""
        score = 0
        
        # 1. Probability (up to 50 pts)
        if self.probability:
            score += int(self.probability / 2)
            
        # 2. Expected Revenue (up to 20 pts)
        if self.expected_revenue:
            if self.expected_revenue >= 10000:
                score += 20
            elif self.expected_revenue >= 1000:
                score += 10
            elif self.expected_revenue > 0:
                score += 5
                
        # 3. Source (up to 15 pts)
        if self.source:
            if self.source == self.Source.REFERRAL:
                score += 15
            elif self.source in [self.Source.WEB, self.Source.EVENT]:
                score += 10
            elif self.source in [self.Source.EMAIL, self.Source.SOCIAL]:
                score += 5
                
        # 4. Data Completeness (up to 15 pts)
        if self.email:
            score += 5
        if self.phone:
            score += 5
        if self.campaign_id:
            score += 5
            
        # Cap at 100
        self.lead_score = min(score, 100)

    def save(self, *args, **kwargs):
        # Only auto-calculate if we're not explicitly updating specific fields that exclude lead_score
        update_fields = kwargs.get('update_fields')
        if not update_fields or 'lead_score' in update_fields or 'status' in update_fields:
            self.calculate_score()
            if update_fields and 'lead_score' not in update_fields:
                kwargs['update_fields'] = list(update_fields) + ['lead_score']
        super().save(*args, **kwargs)


class Customer(CompanyScoped, AddressMixin, ContactMixin, NotesMixin):
    class CustomerType(models.TextChoices):
        INDIVIDUAL = 'individual', _('Individual')
        BUSINESS = 'business', _('Business')

    name = models.CharField(max_length=255, db_index=True)
    customer_type = models.CharField(max_length=15, choices=CustomerType.choices, default=CustomerType.BUSINESS)
    customer_code = models.CharField(max_length=50, blank=True, db_index=True)
    tax_id = models.CharField(max_length=100, blank=True)
    credit_limit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    payment_terms = models.PositiveSmallIntegerField(default=30, help_text='Days')
    currency = models.ForeignKey('company.Currency', null=True, blank=True, on_delete=models.SET_NULL)
    sales_rep = models.ForeignKey(
        'authentication.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='customers',
    )
    shipping_address = models.TextField(blank=True)
    shipping_same_as_billing = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    portal_user = models.OneToOneField('authentication.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='customer_profile')

    class Meta:
        db_table = 'crm_customers'

    def __str__(self):
        return self.name

    @property
    def outstanding_balance(self):
        from apps.sales.models import Invoice
        from django.db.models import Sum
        return Invoice.objects.filter(
            customer=self, status__in=['sent', 'partial']
        ).aggregate(total=Sum('balance_due'))['total'] or 0


class LeadActivity(CompanyScoped):
    class ActivityType(models.TextChoices):
        CALL = 'call', _('Call')
        EMAIL = 'email', _('Email')
        MEETING = 'meeting', _('Meeting')
        NOTE = 'note', _('Note')
        TASK = 'task', _('Task')

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='activities')
    activity_type = models.CharField(max_length=15, choices=ActivityType.choices)
    subject = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    assigned_to = models.ForeignKey('authentication.User', null=True, on_delete=models.SET_NULL)
    outcome = models.TextField(blank=True)
    
    duration_minutes = models.PositiveIntegerField(null=True, blank=True, help_text='Duration in minutes for calls/meetings')
    email_message_id = models.CharField(max_length=255, blank=True)
    email_status = models.CharField(max_length=50, blank=True)

    class Meta:
        db_table = 'crm_lead_activities'
        ordering = ['-created_at']


class Contract(CompanyScoped, NotesMixin):
    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        ACTIVE = 'active', _('Active')
        EXPIRED = 'expired', _('Expired')
        TERMINATED = 'terminated', _('Terminated')

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='contracts')
    title = models.CharField(max_length=255)
    contract_number = models.CharField(max_length=100, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    value = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    document = models.FileField(upload_to='contracts/', null=True, blank=True)
    signed_by_customer = models.BooleanField(default=False)
    signed_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'crm_contracts'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.contract_number} | {self.title}"
