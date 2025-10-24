from django.urls import path
from .views import (
    dashboard_main,
    dashboard_executive,
    dashboard_manager,
    dashboard_hr,
    dashboard_finance,
    dashboard_social_worker,
    dashboard_admin,
    dashboard_staff,
    dashboard_activity,
    dashboard_quick_stats,
)

urlpatterns = [
    # Main dashboard
    path('', dashboard_main, name='dashboard-main'),
    
    # Individual role endpoints
    path('executive/', dashboard_executive, name='dashboard-executive'),
    path('manager/', dashboard_manager, name='dashboard-manager'),
    path('hr/', dashboard_hr, name='dashboard-hr'),
    path('finance/', dashboard_finance, name='dashboard-finance'),
    path('social-worker/', dashboard_social_worker, name='dashboard-social-worker'),
    path('admin/', dashboard_admin, name='dashboard-admin'),
    path('staff/', dashboard_staff, name='dashboard-staff'),
    
    path('activity/', dashboard_activity, name='dashboard-activity'),
    path('quick-stats/', dashboard_quick_stats, name='dashboard-quick-stats'),
]