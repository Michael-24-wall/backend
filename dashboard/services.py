from django.utils import timezone
from django.db.models import Count, Sum, Avg, Q
from django.core.cache import cache
from datetime import timedelta
import logging

logger = logging.getLogger('dashboard')

class DashboardService:
    """
    Simple, robust dashboard service that handles all data processing
    """
    
    def __init__(self, user):
        self.user = user
        self.organization = self._get_user_organization()
    
    def _get_user_organization(self):
        """Get user organization safely"""
        try:
            if hasattr(self.user, 'organization_id') and self.user.organization_id:
                from core.models import Organization
                return Organization.objects.get(id=self.user.organization_id)
        except Exception as e:
            logger.warning(f"Organization lookup failed: {e}")
        return None
    
    def get_main_dashboard(self):
        """Get main dashboard data based on user role"""
        if not self.organization:
            return self._error_response("Organization not found")
        
        role = self._get_user_role()
        
        if role == 'owner':
            return self._get_executive_data()
        elif role == 'manager':
            return self._get_manager_data()
        elif role == 'hr':
            return self._get_hr_data()
        elif role == 'accountant':
            return self._get_finance_data()
        elif role == 'social_worker':
            return self._get_social_worker_data()
        elif role == 'admin':
            return self._get_admin_data()
        else:
            return self._get_staff_data()
    
    def get_role_dashboard(self, role):
        """Get specific role dashboard data"""
        if not self.organization:
            return self._error_response("Organization not found")
        
        role_handlers = {
            'executive': self._get_executive_data,
            'manager': self._get_manager_data,
            'hr': self._get_hr_data,
            'finance': self._get_finance_data,
            'social_worker': self._get_social_worker_data,
            'admin': self._get_admin_data,
            'staff': self._get_staff_data,
        }
        
        if role not in role_handlers:
            return self._error_response(f"Invalid role: {role}")
        
        return role_handlers[role]()
    
    def _get_user_role(self):
        """Get user role safely"""
        try:
            if self.user.is_superuser:
                return 'admin'
            
            from core.models import OrganizationMembership
            membership = OrganizationMembership.objects.filter(
                user=self.user,
                organization=self.organization
            ).first()
            
            if membership and hasattr(membership, 'role'):
                return getattr(membership, 'role', 'staff')
                
        except Exception as e:
            logger.warning(f"Role detection failed: {e}")
        
        return 'staff'
    
    def _get_executive_data(self):
        """Executive dashboard data"""
        user_stats = self._get_basic_user_stats()
        doc_stats = self._get_basic_document_stats()
        
        return {
            'dashboard_type': 'executive',
            'organization': self.organization.name,
            'metrics': {
                'total_users': user_stats['total'],
                'active_users': user_stats['active'],
                'total_documents': doc_stats['total'],
                'storage_used_gb': doc_stats['storage_gb'],
            },
            'timestamp': timezone.now().isoformat()
        }
    
    def _get_manager_data(self):
        """Manager dashboard data"""
        team_stats = self._get_team_stats()
        
        return {
            'dashboard_type': 'manager',
            'organization': self.organization.name,
            'team_metrics': {
                'team_size': team_stats['size'],
                'active_members': team_stats['active'],
                'team_documents': team_stats['documents'],
            },
            'timestamp': timezone.now().isoformat()
        }
    
    def _get_hr_data(self):
        """HR dashboard data"""
        workforce_stats = self._get_workforce_stats()
        
        return {
            'dashboard_type': 'hr',
            'organization': self.organization.name,
            'workforce': {
                'total_employees': workforce_stats['total'],
                'active_employees': workforce_stats['active'],
            },
            'timestamp': timezone.now().isoformat()
        }
    
    def _get_finance_data(self):
        """Finance dashboard data"""
        financial_stats = self._get_financial_stats()
        
        return {
            'dashboard_type': 'finance',
            'organization': self.organization.name,
            'financial_docs': {
                'total_count': financial_stats['count'],
                'storage_used_mb': financial_stats['storage_mb'],
            },
            'timestamp': timezone.now().isoformat()
        }
    
    def _get_social_worker_data(self):
        """Social worker dashboard data"""
        case_stats = self._get_case_stats()
        
        return {
            'dashboard_type': 'social_worker',
            'organization': self.organization.name,
            'caseload': {
                'total_cases': case_stats['total'],
                'active_cases': case_stats['active'],
            },
            'timestamp': timezone.now().isoformat()
        }
    
    def _get_admin_data(self):
        """Admin dashboard data"""
        system_stats = self._get_system_stats()
        
        return {
            'dashboard_type': 'admin',
            'organization': self.organization.name,
            'system_health': {
                'total_users': system_stats['users'],
                'total_documents': system_stats['documents'],
            },
            'timestamp': timezone.now().isoformat()
        }
    
    def _get_staff_data(self):
        """Staff dashboard data"""
        personal_stats = self._get_personal_stats()
        
        return {
            'dashboard_type': 'staff',
            'organization': self.organization.name,
            'personal_metrics': {
                'my_documents': personal_stats['documents'],
                'storage_used_mb': personal_stats['storage_mb'],
            },
            'timestamp': timezone.now().isoformat()
        }
    
    def _get_basic_user_stats(self):
        """Basic user statistics"""
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            stats = User.objects.filter(organization=self.organization).aggregate(
                total=Count('id'),
                active=Count('id', filter=Q(is_active=True)),
            )
            
            return {
                'total': stats['total'] or 0,
                'active': stats['active'] or 0,
            }
        except Exception as e:
            logger.warning(f"User stats failed: {e}")
            return {'total': 0, 'active': 0}
    
    def _get_basic_document_stats(self):
        """Basic document statistics"""
        try:
            from editor.models import SpreadsheetDocument
            
            stats = SpreadsheetDocument.objects.filter(organization=self.organization).aggregate(
                total=Count('id'),
                total_size=Sum('size'),
            )
            
            storage_gb = (stats['total_size'] or 0) / (1024 ** 3)
            
            return {
                'total': stats['total'] or 0,
                'storage_gb': round(storage_gb, 2),
            }
        except Exception as e:
            logger.warning(f"Document stats failed: {e}")
            return {'total': 0, 'storage_gb': 0}
    
    def _get_team_stats(self):
        """Team statistics"""
        try:
            from django.contrib.auth import get_user_model
            from editor.models import SpreadsheetDocument
            
            User = get_user_model()
            team_members = User.objects.filter(organization=self.organization)
            team_docs = SpreadsheetDocument.objects.filter(owner__in=team_members)
            
            docs_count = team_docs.count()
            
            return {
                'size': team_members.count(),
                'active': team_members.filter(is_active=True).count(),
                'documents': docs_count,
            }
        except Exception as e:
            logger.warning(f"Team stats failed: {e}")
            return {'size': 0, 'active': 0, 'documents': 0}
    
    def _get_workforce_stats(self):
        """Workforce statistics"""
        return self._get_basic_user_stats()
    
    def _get_financial_stats(self):
        """Financial document statistics"""
        try:
            from editor.models import SpreadsheetDocument
            
            financial_docs = SpreadsheetDocument.objects.filter(
                organization=self.organization,
                document_type__in=['financial', 'budget', 'invoice', 'expense']
            )
            
            count = financial_docs.count()
            total_size = financial_docs.aggregate(total_size=Sum('size'))['total_size'] or 0
            storage_mb = total_size / (1024 ** 2)
            
            return {
                'count': count,
                'storage_mb': round(storage_mb, 2),
            }
        except Exception as e:
            logger.warning(f"Financial stats failed: {e}")
            return {'count': 0, 'storage_mb': 0}
    
    def _get_case_stats(self):
        """Case statistics"""
        try:
            from editor.models import SpreadsheetDocument
            
            case_docs = SpreadsheetDocument.objects.filter(
                owner=self.user,
                document_type__icontains='case'
            )
            
            total = case_docs.count()
            active = case_docs.filter(is_archived=False).count()
            
            return {
                'total': total,
                'active': active,
            }
        except Exception as e:
            logger.warning(f"Case stats failed: {e}")
            return {'total': 0, 'active': 0}
    
    def _get_system_stats(self):
        """System statistics"""
        user_stats = self._get_basic_user_stats()
        doc_stats = self._get_basic_document_stats()
        
        return {
            'users': user_stats['total'],
            'documents': doc_stats['total'],
        }
    
    def _get_personal_stats(self):
        """Personal statistics"""
        try:
            from editor.models import SpreadsheetDocument
            
            user_docs = SpreadsheetDocument.objects.filter(owner=self.user)
            count = user_docs.count()
            total_size = user_docs.aggregate(total_size=Sum('size'))['total_size'] or 0
            storage_mb = total_size / (1024 ** 2)
            
            return {
                'documents': count,
                'storage_mb': round(storage_mb, 2),
            }
        except Exception as e:
            logger.warning(f"Personal stats failed: {e}")
            return {'documents': 0, 'storage_mb': 0}
    
    def get_activity_data(self, limit=20):
        """Get activity data"""
        try:
            from editor.models import AuditLog
            
            activities = AuditLog.objects.filter(user=self.user).select_related('document').order_by('-timestamp')[:limit]
            
            return [
                {
                    'action': activity.action,
                    'document': activity.document.title if activity.document else 'System',
                    'timestamp': activity.timestamp.isoformat(),
                }
                for activity in activities
            ]
        except Exception as e:
            logger.warning(f"Activity data failed: {e}")
            return []
    
    def get_quick_stats(self):
        """Get quick stats"""
        user_stats = self._get_basic_user_stats()
        doc_stats = self._get_basic_document_stats()
        
        return {
            'total_users': user_stats['total'],
            'active_users': user_stats['active'],
            'total_documents': doc_stats['total'],
            'storage_used_gb': doc_stats['storage_gb'],
        }
    
    def _error_response(self, message):
        """Error response"""
        return {
            'error': True,
            'message': message,
            'timestamp': timezone.now().isoformat()
        }