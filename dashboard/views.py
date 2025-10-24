from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
import logging

from .services import DashboardService

logger = logging.getLogger('dashboard')

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_main(request):
    """Main dashboard endpoint - completely independent"""
    try:
        service = DashboardService(request.user)
        data = service.get_main_dashboard()
        
        if data.get('error'):
            return JsonResponse({
                'status': 'error',
                'data': data
            }, status=400)
        
        return JsonResponse({
            'status': 'success',
            'data': data
        })
        
    except Exception as e:
        logger.error(f"Main dashboard error: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'Failed to load dashboard'
        }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_executive(request):
    """Executive dashboard - completely independent"""
    try:
        service = DashboardService(request.user)
        data = service.get_role_dashboard('executive')
        
        if data.get('error'):
            return JsonResponse({
                'status': 'error',
                'data': data
            }, status=400)
        
        return JsonResponse({
            'status': 'success',
            'data': data
        })
        
    except Exception as e:
        logger.error(f"Executive dashboard error: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'Failed to load executive dashboard'
        }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_manager(request):
    """Manager dashboard - completely independent"""
    try:
        service = DashboardService(request.user)
        data = service.get_role_dashboard('manager')
        
        if data.get('error'):
            return JsonResponse({
                'status': 'error',
                'data': data
            }, status=400)
        
        return JsonResponse({
            'status': 'success',
            'data': data
        })
        
    except Exception as e:
        logger.error(f"Manager dashboard error: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'Failed to load manager dashboard'
        }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_hr(request):
    """HR dashboard - completely independent"""
    try:
        service = DashboardService(request.user)
        data = service.get_role_dashboard('hr')
        
        if data.get('error'):
            return JsonResponse({
                'status': 'error',
                'data': data
            }, status=400)
        
        return JsonResponse({
            'status': 'success',
            'data': data
        })
        
    except Exception as e:
        logger.error(f"HR dashboard error: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'Failed to load HR dashboard'
        }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_finance(request):
    """Finance dashboard - completely independent"""
    try:
        service = DashboardService(request.user)
        data = service.get_role_dashboard('finance')
        
        if data.get('error'):
            return JsonResponse({
                'status': 'error',
                'data': data
            }, status=400)
        
        return JsonResponse({
            'status': 'success',
            'data': data
        })
        
    except Exception as e:
        logger.error(f"Finance dashboard error: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'Failed to load finance dashboard'
        }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_social_worker(request):
    """Social worker dashboard - completely independent"""
    try:
        service = DashboardService(request.user)
        data = service.get_role_dashboard('social_worker')
        
        if data.get('error'):
            return JsonResponse({
                'status': 'error',
                'data': data
            }, status=400)
        
        return JsonResponse({
            'status': 'success',
            'data': data
        })
        
    except Exception as e:
        logger.error(f"Social worker dashboard error: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'Failed to load social worker dashboard'
        }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_admin(request):
    """Admin dashboard - completely independent"""
    try:
        service = DashboardService(request.user)
        data = service.get_role_dashboard('admin')
        
        if data.get('error'):
            return JsonResponse({
                'status': 'error',
                'data': data
            }, status=400)
        
        return JsonResponse({
            'status': 'success',
            'data': data
        })
        
    except Exception as e:
        logger.error(f"Admin dashboard error: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'Failed to load admin dashboard'
        }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_staff(request):
    """Staff dashboard - completely independent"""
    try:
        service = DashboardService(request.user)
        data = service.get_role_dashboard('staff')
        
        if data.get('error'):
            return JsonResponse({
                'status': 'error',
                'data': data
            }, status=400)
        
        return JsonResponse({
            'status': 'success',
            'data': data
        })
        
    except Exception as e:
        logger.error(f"Staff dashboard error: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'Failed to load staff dashboard'
        }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_activity(request):
    """Activity feed - completely independent"""
    try:
        service = DashboardService(request.user)
        limit = min(int(request.GET.get('limit', 20)), 100)
        activities = service.get_activity_data(limit)
        
        return JsonResponse({
            'status': 'success',
            'data': activities,
            'count': len(activities)
        })
        
    except Exception as e:
        logger.error(f"Activity feed error: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'Failed to load activity feed'
        }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_quick_stats(request):
    """Quick stats - completely independent"""
    try:
        service = DashboardService(request.user)
        stats = service.get_quick_stats()
        
        return JsonResponse({
            'status': 'success',
            'data': stats
        })
        
    except Exception as e:
        logger.error(f"Quick stats error: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'Failed to load quick stats'
        }, status=500)