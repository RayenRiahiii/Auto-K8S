from django.urls import path
from . import views

urlpatterns = [
    path("hosts/", views.hosts_list_create),
    path("hosts/<int:id>/", views.host_detail),
    path("credentials/", views.credentials_list),
    path("credentials/<int:id>/", views.credential_detail),
    path("templates/", views.templates_list),
    path("installations/", views.installations_list),
    path("installations/<int:id>/", views.installation_detail),
    path("installations/precheck/", views.precheck_installation_hosts),
    path("installations/launch/", views.launch_installation),
]
