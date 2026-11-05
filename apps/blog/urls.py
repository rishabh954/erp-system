"""
Blog URL Configuration
Web UI routes — all under /blog/
"""

from django.urls import path

from .views import (
    ApprovalQueueView, ApprovePostView, BlogAnalyticsView,
    BlogCategoryCreateView, BlogCategoryListView, BlogDashboardView,
    BlogEnquiryListView, BlogEnquirySubmitView, BlogPostArchiveView,
    BlogPostCreateView, BlogPostDeleteView, BlogPostDetailView,
    BlogPostDuplicateView, BlogPostListView, BlogPostUpdateView,
    BlogTagCreateView, BlogTagListView, PublishCalendarView,
    PublishingHistoryView, PublishNowView, PublishToSocialView,
    RejectPostView, SchedulePostView, SocialAccountConnectView,
    SocialAccountDisconnectView, SocialAccountListView, SocialOAuthCallbackView,
    SocialPublishingQueueView, SubmitForApprovalView, UnpublishPostView,
    WebsiteHealthCheckView, WebsiteIntegrationView,
)

app_name = "blog"

urlpatterns = [
    # Dashboard
    path("", BlogDashboardView.as_view(), name="dashboard"),

    # Posts
    path("posts/", BlogPostListView.as_view(), name="posts"),
    path("posts/create/", BlogPostCreateView.as_view(), name="post_create"),
    path("posts/<uuid:pk>/", BlogPostDetailView.as_view(), name="post_detail"),
    path("posts/<uuid:pk>/edit/", BlogPostUpdateView.as_view(), name="post_edit"),
    path("posts/<uuid:pk>/delete/", BlogPostDeleteView.as_view(), name="post_delete"),
    path("posts/<uuid:pk>/duplicate/", BlogPostDuplicateView.as_view(), name="post_duplicate"),
    path("posts/<uuid:pk>/archive/", BlogPostArchiveView.as_view(), name="post_archive"),

    # Approval workflow
    path("posts/<uuid:pk>/submit/", SubmitForApprovalView.as_view(), name="post_submit"),
    path("posts/<uuid:pk>/approve/", ApprovePostView.as_view(), name="post_approve"),
    path("posts/<uuid:pk>/reject/", RejectPostView.as_view(), name="post_reject"),
    path("approval-queue/", ApprovalQueueView.as_view(), name="approval_queue"),

    # Publishing
    path("posts/<uuid:pk>/publish/", PublishNowView.as_view(), name="post_publish"),
    path("posts/<uuid:pk>/unpublish/", UnpublishPostView.as_view(), name="post_unpublish"),
    path("posts/<uuid:pk>/schedule/", SchedulePostView.as_view(), name="post_schedule"),
    path("calendar/", PublishCalendarView.as_view(), name="calendar"),
    path("history/", PublishingHistoryView.as_view(), name="publishing_history"),

    # Social media
    path("social/accounts/", SocialAccountListView.as_view(), name="social_accounts"),
    path("social/connect/<str:platform>/", SocialAccountConnectView.as_view(), name="social_connect"),
    path("social/callback/<str:platform>/", SocialOAuthCallbackView.as_view(), name="social_oauth_callback"),
    path("social/disconnect/<uuid:pk>/", SocialAccountDisconnectView.as_view(), name="social_disconnect"),
    path("posts/<uuid:pk>/social/publish/", PublishToSocialView.as_view(), name="post_social_publish"),
    path("social/queue/", SocialPublishingQueueView.as_view(), name="social_queue"),

    # Website integration
    path("website/integration/", WebsiteIntegrationView.as_view(), name="website_integration"),
    path("website/integration/<uuid:pk>/health/", WebsiteHealthCheckView.as_view(), name="website_health_check"),

    # Categories & Tags
    path("categories/", BlogCategoryListView.as_view(), name="categories"),
    path("categories/create/", BlogCategoryCreateView.as_view(), name="category_create"),
    path("tags/", BlogTagListView.as_view(), name="tags"),
    path("tags/create/", BlogTagCreateView.as_view(), name="tag_create"),

    # Analytics
    path("analytics/", BlogAnalyticsView.as_view(), name="analytics"),

    # Enquiries (internal list)
    path("enquiries/", BlogEnquiryListView.as_view(), name="enquiries"),

    # Public enquiry submission endpoint (no auth)
    path("enquiry/<uuid:post_pk>/submit/", BlogEnquirySubmitView.as_view(), name="enquiry_submit"),
]
