from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.blog.api.views import (
    BlogCategoryViewSet,
    BlogEnquiryViewSet,
    BlogPostViewSet,
    BlogTagViewSet,
    PublishingLogViewSet,
    SocialMediaAccountViewSet,
    SocialMediaPublicationViewSet,
    WebsiteIntegrationViewSet,
)

app_name = "api_blog"

router = DefaultRouter()
router.register(r"posts", BlogPostViewSet, basename="post")
router.register(r"categories", BlogCategoryViewSet, basename="category")
router.register(r"tags", BlogTagViewSet, basename="tag")
router.register(r"website-integrations", WebsiteIntegrationViewSet, basename="website-integration")
router.register(r"social-accounts", SocialMediaAccountViewSet, basename="social-account")
router.register(r"social-publications", SocialMediaPublicationViewSet, basename="social-publication")
router.register(r"publishing-logs", PublishingLogViewSet, basename="publishing-log")
router.register(r"enquiries", BlogEnquiryViewSet, basename="enquiry")

urlpatterns = [path("", include(router.urls))]
