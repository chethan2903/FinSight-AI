from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("stock/<str:ticker>/", views.stock_detail, name="stock_detail"),
    path("portfolio/", views.portfolio_dashboard, name="portfolio_dashboard"),
    path("portfolio/add/", views.add_holding, name="add_holding"),
    path("portfolio/remove/<int:holding_id>/", views.remove_holding, name="remove_holding"),
    path("assistant/", views.assistant_chat, name="assistant_chat"),
    path("alerts/", views.alerts_config, name="alerts_config"),
    path("alerts/create/", views.create_alert, name="create_alert"),
    path("alerts/delete/<int:alert_id>/", views.delete_alert, name="delete_alert"),
    path("alerts/read-all/", views.mark_notifications_read, name="mark_notifications_read"),
]
