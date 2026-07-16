from django.urls import path

from . import api

urlpatterns = [
    path("activities/", api.ActivityListView.as_view(), name="activity-list"),
    path("activities/<slug:slug>/", api.ActivityDetailView.as_view(), name="activity-detail"),
    path(
        "activities/<slug:slug>/register/",
        api.RegisterView.as_view(),
        name="activity-register",
    ),
]
