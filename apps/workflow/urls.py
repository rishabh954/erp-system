"""Enterprise Workflow URLs"""

from django.urls import path

from .views import (
    ApprovalDelegationCreateView,
    ApprovalDelegationDeleteView,
    ApprovalHistoryListView,
    DelegatedApprovalsListView,
    NotificationTemplateView,
    PendingApprovalsListView,
    StepCreateView,
    StepDeleteView,
    StepReorderView,
    WorkflowActionAPIView,
    WorkflowCreateView,
    WorkflowDashboardView,
    WorkflowDesignerSaveAPI,
    WorkflowDesignerView,
    WorkflowInstanceDetailView,
    WorkflowListView,
    WorkflowVisualFlowAPI,
)

app_name = "workflow"

urlpatterns = [
    # Dashboard
    path("", WorkflowDashboardView.as_view(), name="dashboard"),
    # Workflow Definitions
    path("definitions/", WorkflowListView.as_view(), name="list"),
    path("definitions/create/", WorkflowCreateView.as_view(), name="create"),
    path(
        "definitions/<uuid:pk>/designer/",
        WorkflowDesignerView.as_view(),
        name="designer",
    ),
    # Designer APIs
    path(
        "definitions/<uuid:pk>/save/",
        WorkflowDesignerSaveAPI.as_view(),
        name="designer_save",
    ),
    path(
        "definitions/<uuid:pk>/flow/",
        WorkflowVisualFlowAPI.as_view(),
        name="visual_flow",
    ),
    # Steps
    path(
        "definitions/<uuid:workflow_pk>/steps/create/",
        StepCreateView.as_view(),
        name="step_create",
    ),
    path("steps/<uuid:pk>/delete/", StepDeleteView.as_view(), name="step_delete"),
    path(
        "definitions/<uuid:workflow_pk>/steps/reorder/",
        StepReorderView.as_view(),
        name="step_reorder",
    ),
    # Pending Approvals
    path("pending/", PendingApprovalsListView.as_view(), name="pending_approvals"),
    # Action API (approve / reject / delegate / return)
    path(
        "api/action/<uuid:instance_id>/",
        WorkflowActionAPIView.as_view(),
        name="action_api",
    ),
    # History
    path("history/", ApprovalHistoryListView.as_view(), name="history"),
    path(
        "instances/<uuid:pk>/",
        WorkflowInstanceDetailView.as_view(),
        name="instance_detail",
    ),
    # Delegation
    path("delegations/", DelegatedApprovalsListView.as_view(), name="delegations"),
    path(
        "delegations/new/",
        ApprovalDelegationCreateView.as_view(),
        name="delegation_create",
    ),
    path(
        "delegations/<uuid:pk>/deactivate/",
        ApprovalDelegationDeleteView.as_view(),
        name="delegation_delete",
    ),
    # Notification Templates
    path(
        "definitions/<uuid:workflow_pk>/notifications/",
        NotificationTemplateView.as_view(),
        name="notification_templates",
    ),
]
