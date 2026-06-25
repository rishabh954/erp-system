from django.urls import path
from .views import (
    PendingApprovalsListView,
    ApprovalHistoryListView,
    DelegatedApprovalsListView,
    ApprovalDelegationCreateView,
    WorkflowActionAPIView
)

app_name = 'workflow'

urlpatterns = [
    path('pending/', PendingApprovalsListView.as_view(), name='pending_approvals'),
    path('history/', ApprovalHistoryListView.as_view(), name='history'),
    path('delegations/', DelegatedApprovalsListView.as_view(), name='delegations'),
    path('delegations/new/', ApprovalDelegationCreateView.as_view(), name='delegation_create'),
    path('api/action/<uuid:instance_id>/', WorkflowActionAPIView.as_view(), name='action_api'),
]
