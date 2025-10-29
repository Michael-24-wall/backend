from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.core.exceptions import ObjectDoesNotExist

from .models import (
    ApprovalWorkflow, WorkflowTemplateStep, 
    DocumentApprovalFlow, WorkflowLog,
    ApprovalChatRoom
)
from documents.models import Document 
from core.models import OrganizationMembership, Organization
from .serializers import (
    DocumentApprovalFlowDetailSerializer, 
    DocumentApprovalFlowListSerializer,
    WorkflowLogSerializer, 
    ApprovalActionSerializer,
    ApprovalWorkflowSerializer,
    WorkflowInitiationSerializer,
    ApprovalChatRoomSerializer
)

from .utils import send_approval_notification, send_rejection_notification

CustomUser = get_user_model()


class IsOrganizationMember(permissions.BasePermission):
    def has_permission(self, request, view):
        # Check JWT token claims first (your token has organization data)
        if hasattr(request, 'auth') and request.auth:
            try:
                has_organization = request.auth.get('has_organization', False)
                if has_organization:
                    return True
            except Exception:
                pass
        
        # Fallback to database check
        try:
            # Get user role - check JWT first, then database
            user_role = None
            
            # First, try to get role from JWT token
            if hasattr(request, 'auth') and request.auth:
                jwt_role = request.auth.get('organization_role', '').lower()
                if jwt_role:
                    user_role = jwt_role
            
            # If JWT doesn't have role, check database
            if not user_role and hasattr(request.user, 'organizationmembership'):
                user_role = request.user.organizationmembership.role.lower()
            
            # Owners always have access, others need active membership
            if user_role == 'owner':
                return True
                
            # For non-owners, check if membership is active
            if hasattr(request.user, 'organizationmembership'):
                return request.user.organizationmembership.is_active
                
        except (AttributeError, ObjectDoesNotExist):
            return False
        
        return False


class CanSubmitDocument(permissions.BasePermission):
    def has_permission(self, request, view):
        # Get user role - check JWT first, then database
        user_role = None
        
        # First, try to get role from JWT token
        if hasattr(request, 'auth') and request.auth:
            jwt_role = request.auth.get('organization_role', '').lower()
            if jwt_role:
                user_role = jwt_role
        
        # If JWT doesn't have role, check database
        if not user_role and hasattr(request.user, 'organizationmembership'):
            try:
                user_role = request.user.organizationmembership.role.lower()
            except (AttributeError, ObjectDoesNotExist):
                return False
        
        # Check permissions
        if user_role == 'owner':
            return True
            
        allowed_roles = ['staff', 'manager', 'admin', 'owner']
        return user_role in allowed_roles


def find_approver_for_role(organization, role_name):
    try:
        membership = OrganizationMembership.objects.filter(
            organization=organization,
            role=role_name,
            is_active=True
        ).select_related('user').first()
        return membership.user if membership else None
    except OrganizationMembership.DoesNotExist:
        return None


def get_user_organization(user):
    # Try to get organization from JWT token context
    if hasattr(user, 'auth') and user.auth:
        try:
            # Get organization from user's memberships
            # Since JWT doesn't have org ID, get the first active membership
            membership = OrganizationMembership.objects.filter(
                user=user,
                is_active=True
            ).select_related('organization').first()
            
            if membership:
                return membership.organization
        except Exception:
            pass
    
    # Fallback: get from organization membership
    if hasattr(user, 'organizationmembership'):
        try:
            membership = user.organizationmembership
            return membership.organization
        except (AttributeError, ObjectDoesNotExist):
            pass
    
    # Final fallback: get user's first organization
    try:
        membership = OrganizationMembership.objects.filter(
            user=user,
            is_active=True
        ).select_related('organization').first()
        
        if membership:
            return membership.organization
    except OrganizationMembership.DoesNotExist:
        pass
    
    raise PermissionDenied("User is not a member of any organization")


def get_user_role(user):
    """Get user role from JWT or database"""
    # First, try to get role from JWT token
    if hasattr(user, 'auth') and user.auth:
        jwt_role = user.auth.get('organization_role', '').lower()
        if jwt_role:
            return jwt_role
    
    # Fallback to database
    if hasattr(user, 'organizationmembership'):
        try:
            return user.organizationmembership.role.lower()
        except (AttributeError, ObjectDoesNotExist):
            pass
    
    # Final fallback: get from database directly
    try:
        membership = OrganizationMembership.objects.filter(
            user=user,
            is_active=True
        ).first()
        if membership:
            return membership.role.lower()
    except OrganizationMembership.DoesNotExist:
        pass
    
    return None


def is_user_owner(user):
    """Check if user is an owner"""
    user_role = get_user_role(user)
    return user_role == 'owner'


class DocumentSubmissionViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated, IsOrganizationMember, CanSubmitDocument]
    serializer_class = DocumentApprovalFlowDetailSerializer

    def get_queryset(self):
        org = get_user_organization(self.request.user)
        if is_user_owner(self.request.user):
            return Document.objects.filter(organization=org)
        return Document.objects.filter(organization=org, created_by=self.request.user)

    @action(detail=False, methods=['post'], url_path='submit')
    def submit_request(self, request):
        user = request.user
        org = get_user_organization(user)

        workflow_template_id = request.data.get('workflow_template_id')
        title = request.data.get('title')
        file_attachment = request.FILES.get('file_attachment')
        description = request.data.get('description', '')

        if not all([workflow_template_id, title, file_attachment]):
            return Response(
                {"detail": "Missing required fields (title, file_attachment, workflow_template_id)."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            workflow_template = ApprovalWorkflow.objects.get(
                organization=org, 
                id=workflow_template_id,
                is_active=True
            )
            first_step = workflow_template.template_steps.order_by('step_order').first()
            
            if not first_step:
                return Response(
                    {"detail": "Selected workflow template has no steps configured."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            initial_approver = find_approver_for_role(org, first_step.approver_role)
            if not initial_approver:
                return Response(
                    {"detail": f"No user found with required role: {first_step.approver_role}"},
                    status=status.HTTP_404_NOT_FOUND
                )

        except ApprovalWorkflow.DoesNotExist:
            return Response(
                {"detail": "Active workflow template not found."}, 
                status=status.HTTP_404_NOT_FOUND
            )

        with transaction.atomic():
            document = Document.objects.create(
                organization=org,
                title=title,
                created_by=user,
                status=Document.STATUS_PENDING_REVIEW,
                file_attachment=file_attachment,
                file_description=description or f"Initial submission for {title}",
            )
            
            flow = DocumentApprovalFlow.objects.create(
                document=document,
                workflow_template=workflow_template,
                current_template_step=first_step,
                current_approver=initial_approver,
                current_step_started_at=timezone.now()
            )
            
            WorkflowLog.objects.create(
                document=document,
                template_step=first_step,
                actor=user,
                action_type='route',
                comments=f"Document submitted and assigned to {initial_approver.get_full_name()}.",
            )

            # Create chat room for this approval
            self._create_approval_chat_room(flow, user, initial_approver)

        serializer = self.get_serializer(flow)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def _create_approval_chat_room(self, flow, user, initial_approver):
        """Create a chat room for the approval process"""
        try:
            from chat.models import ChatRoom, RoomMembership, Message
            
            chat_room = ChatRoom.objects.create(
                name=f"approval-doc-{flow.document.id}",
                title=f"Approval: {flow.document.title}",
                description=f"Discussion for {flow.document.title} approval process",
                is_private=True,
                created_by=user
            )
            
            # Add participants
            RoomMembership.objects.create(user=user, room=chat_room, role='admin')
            RoomMembership.objects.create(user=initial_approver, room=chat_room, role='admin')
            
            # Link to workflow
            ApprovalChatRoom.objects.create(approval_flow=flow, chat_room=chat_room)
            
            # Welcome message
            Message.objects.create(
                room=chat_room,
                user=user,
                content=f"Document submitted for approval. Current approver: {initial_approver.get_full_name()}",
                message_type='text'
            )
            
        except ImportError:
            # Chat app not available
            pass

    @action(detail=False, methods=['get'], url_path='my-submissions')
    def my_submissions(self, request):
        if is_user_owner(request.user):
            org = get_user_organization(request.user)
            submissions = Document.objects.filter(organization=org).select_related('approval_flow')
        else:
            submissions = self.get_queryset().select_related('approval_flow')
            
        serializer = DocumentApprovalFlowListSerializer(
            [sub.approval_flow for sub in submissions if hasattr(sub, 'approval_flow')], 
            many=True
        )
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='progress')
    def submission_progress(self, request, pk=None):
        flow = get_object_or_404(DocumentApprovalFlow, pk=pk)
        
        is_owner = is_user_owner(request.user)
        if not is_owner and (flow.document.created_by != request.user and 
            flow.current_approver != request.user and
            not self._can_view_team_flow(request.user, flow)):
            raise PermissionDenied("No permission to view this submission")
        
        progress_data = {
            'progress_percentage': flow.get_progress_percentage(),
            'current_step': flow.current_template_step.step_order if flow.current_template_step else None,
            'total_steps': flow.workflow_template.template_steps.count(),
            'status': flow.status,
            'is_overdue': flow.is_overdue()
        }
        return Response(progress_data)

    def _can_view_team_flow(self, user, flow):
        user_role = get_user_role(user)
        allowed_roles = ['manager', 'admin', 'owner']
        return user_role in allowed_roles if user_role else False


class WorkflowActionViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated, IsOrganizationMember]
    
    def get_queryset(self):
        org = get_user_organization(self.request.user)
        return DocumentApprovalFlow.objects.filter(document__organization=org)
    
    def get_serializer_class(self):
        if self.action == 'take_action':
            return ApprovalActionSerializer
        elif self.action == 'history':
            return WorkflowLogSerializer
        elif self.action in ['list', 'pending']:
            return DocumentApprovalFlowListSerializer
        return DocumentApprovalFlowDetailSerializer

    def list(self, request):
        if is_user_owner(request.user):
            pending_flows = self.get_queryset().filter(is_complete=False)
        else:
            pending_flows = self.get_queryset().filter(
                current_approver=request.user, 
                is_complete=False
            )
            
        pending_flows = pending_flows.select_related(
            'document', 
            'current_template_step',
            'current_approver'
        ).prefetch_related('workflow_logs')
        
        serializer = self.get_serializer(pending_flows, many=True)
        return Response({
            'count': pending_flows.count(),
            'results': serializer.data
        })

    @action(detail=False, methods=['get'], url_path='team-pending')
    def team_pending(self, request):
        """Show pending approvals for user's team (based on organization)"""
        org = get_user_organization(request.user)
        
        user_role = get_user_role(request.user)
        is_owner = user_role == 'owner'
        
        if not user_role:
            return Response(
                {"detail": "Could not determine user role"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check permissions
        allowed_roles = ['manager', 'admin', 'owner']
        if user_role not in allowed_roles:
            return Response(
                {
                    "detail": "Insufficient permissions to view team pending approvals",
                    "your_role": user_role,
                    "required_roles": allowed_roles
                }, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        team_flows = self.get_queryset().filter(
            is_complete=False,
            document__organization=org
        )
        
        if not is_owner:
            team_flows = team_flows.exclude(current_approver=request.user)
            
        team_flows = team_flows.select_related(
            'document', 'current_template_step', 'current_approver'
        )
        
        serializer = self.get_serializer(team_flows, many=True)
        return Response({
            'count': team_flows.count(),
            'results': serializer.data,
            'debug_info': {
                'user_role': user_role,
                'is_owner': is_owner
            }
        })

    @action(detail=True, methods=['post'], url_path='action')
    def take_action(self, request, pk=None):
        flow = get_object_or_404(DocumentApprovalFlow, pk=pk)
        
        is_owner = is_user_owner(request.user)
        if not is_owner and flow.current_approver != request.user:
            raise PermissionDenied("You are not authorized to take action on this document.")
        
        if flow.is_complete:
            raise ValidationError("This workflow is already complete.")
        
        if not flow.current_template_step:
            raise ValidationError("Workflow is in an invalid state (no current step).")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        action_type = data['action']
        comments = data.get('comments', '')

        with transaction.atomic():
            if action_type == 'reject':
                self._process_rejection(flow, request.user, comments)
            elif action_type == 'route':
                self._process_routing(flow, request.user, data['decision'], comments)
            elif action_type == 'delegate':
                self._process_delegation(flow, request.user, data['target_user_id'], comments)

        flow.refresh_from_db()
        serializer = DocumentApprovalFlowDetailSerializer(flow)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def _process_rejection(self, flow, user, comments):
        flow.is_complete = True
        flow.is_approved = False
        flow.status = 'rejected'
        flow.completed_at = timezone.now()
        flow.current_approver = None
        flow.current_template_step = None
        flow.save()
        
        flow.document.status = Document.STATUS_REJECTED
        flow.document.save()
        
        WorkflowLog.objects.create(
            document=flow.document, 
            actor=user, 
            action_type='reject', 
            template_step=flow.current_template_step, 
            comments=comments
        )
        
        send_rejection_notification(flow.document.id, comments, rejected_by=user)
        self._send_chat_notification(flow, 'rejected', user, comments)

    def _process_routing(self, flow, user, decision, comments):
        current_step_def = flow.current_template_step
        next_step_order = current_step_def.next_step_routes.get(decision)
        
        if next_step_order is None:
            raise ValidationError(f"Invalid decision '{decision}' for current workflow step.")
        
        if next_step_order == 0:
            flow.is_complete = True
            flow.is_approved = True
            flow.status = 'approved'
            flow.completed_at = timezone.now()
            flow.current_approver = None
            flow.current_template_step = None
            flow.document.status = Document.STATUS_SIGNED
            flow.document.save()
            
            send_approval_notification(flow.document.id)
            self._send_chat_notification(flow, 'approved', user, comments)
        else:
            next_step_def = get_object_or_404(
                WorkflowTemplateStep,
                workflow=flow.workflow_template,
                step_order=next_step_order
            )
            
            next_approver = find_approver_for_role(
                flow.document.organization, 
                next_step_def.approver_role
            )
            
            if not next_approver:
                raise ValidationError(f"No user found for the required role: {next_step_def.approver_role}")

            flow.current_template_step = next_step_def
            flow.current_approver = next_approver
            flow.current_step_started_at = timezone.now()
            flow.save()

            self._update_chat_room_members(flow, next_approver)
            self._send_chat_notification(flow, 'routed', user, f"Decision: {decision}")

        WorkflowLog.objects.create(
            document=flow.document, 
            actor=user, 
            action_type='route', 
            template_step=current_step_def,
            decision_key=decision,
            comments=f"Decision: {decision}. {comments}"
        )

    def _process_delegation(self, flow, user, target_user_id, comments):
        target_user = get_object_or_404(CustomUser, id=target_user_id)
        
        # Check if target user has organization membership
        try:
            if target_user.organizationmembership.organization != flow.document.organization:
                raise ValidationError("Cannot delegate to user outside organization")
        except (AttributeError, ObjectDoesNotExist):
            raise ValidationError("Target user is not a member of any organization")
        
        previous_approver = flow.current_approver
        flow.current_approver = target_user
        flow.save()
        
        WorkflowLog.objects.create(
            document=flow.document,
            actor=user,
            action_type='delegate',
            template_step=flow.current_template_step,
            comments=f"Delegated from {previous_approver.get_full_name()} to {target_user.get_full_name()}. {comments}"
        )
        
        self._send_chat_notification(flow, 'delegated', user, 
                                   f"Delegated to {target_user.get_full_name()}. {comments}")

    def _send_chat_notification(self, flow, action_type, actor, comments=""):
        """Send notification to workflow chat room"""
        try:
            approval_room = ApprovalChatRoom.objects.get(approval_flow=flow)
            from chat.models import Message
            
            action_messages = {
                'approved': '✅ Document approved',
                'rejected': '❌ Document rejected',
                'routed': '🔄 Document moved to next step',
                'delegated': '👤 Approval task delegated',
            }
            
            message_content = f"{action_messages.get(action_type, '📋 Action taken')} by {actor.get_full_name()}"
            if comments:
                message_content += f": {comments}"
            
            Message.objects.create(
                room=approval_room.chat_room,
                user=actor,
                content=message_content,
                message_type='system'
            )
            
        except ApprovalChatRoom.DoesNotExist:
            pass

    def _update_chat_room_members(self, flow, new_approver):
        """Add new approver to chat room"""
        try:
            approval_room = ApprovalChatRoom.objects.get(approval_flow=flow)
            from chat.models import RoomMembership, Message
            
            # Add new approver if not already member
            RoomMembership.objects.get_or_create(
                room=approval_room.chat_room,
                user=new_approver,
                defaults={'role': 'admin'}
            )
            
            Message.objects.create(
                room=approval_room.chat_room,
                user=flow.document.created_by,
                content=f"@{new_approver.get_full_name()} added to discussion for next approval step",
                message_type='system'
            )
            
        except ApprovalChatRoom.DoesNotExist:
            pass

    @action(detail=True, methods=['get'], url_path='history')
    def history(self, request, pk=None):
        """Retrieves the chronological history of all workflow actions for a document."""
        flow = get_object_or_404(DocumentApprovalFlow, pk=pk)
        
        is_owner = is_user_owner(request.user)
        if not is_owner:
            user_role = get_user_role(request.user)
            allowed_roles = ['manager', 'admin', 'owner']
            if (flow.current_approver != request.user and 
                flow.document.created_by != request.user and
                user_role not in allowed_roles):
                raise PermissionDenied("You don't have permission to view this document's history")
        
        logs = flow.document.workflow_logs.all().select_related(
            'actor', 'template_step'
        ).order_by('created_at')
        
        serializer = self.get_serializer(logs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='details')
    def flow_details(self, request, pk=None):
        """Get detailed information about a specific workflow flow"""
        flow = get_object_or_404(DocumentApprovalFlow, pk=pk)
        
        is_owner = is_user_owner(request.user)
        if not is_owner:
            user_role = get_user_role(request.user)
            allowed_roles = ['manager', 'admin', 'owner']
            if (flow.current_approver != request.user and 
                flow.document.created_by != request.user and
                user_role not in allowed_roles):
                raise PermissionDenied("You don't have permission to view this workflow")
        
        serializer = self.get_serializer(flow)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='chat-room')
    def chat_room(self, request, pk=None):
        flow = get_object_or_404(DocumentApprovalFlow, pk=pk)
        
        is_owner = is_user_owner(request.user)
        if not is_owner:
            user_role = get_user_role(request.user)
            allowed_roles = ['manager', 'admin', 'owner']
            if (flow.current_approver != request.user and 
                flow.document.created_by != request.user and
                user_role not in allowed_roles):
                raise PermissionDenied("You don't have permission to view this workflow")
        
        try:
            approval_room = ApprovalChatRoom.objects.get(approval_flow=flow)
            serializer = ApprovalChatRoomSerializer(approval_room)
            return Response(serializer.data)
        except ApprovalChatRoom.DoesNotExist:
            return Response({'detail': 'No chat room found for this workflow'}, 
                          status=status.HTTP_404_NOT_FOUND)


class WorkflowManagementViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsOrganizationMember]
    serializer_class = ApprovalWorkflowSerializer
    
    def get_queryset(self):
        org = get_user_organization(self.request.user)
        return ApprovalWorkflow.objects.filter(organization=org)
    
    def get_permissions(self):
        user_role = get_user_role(self.request.user)
        
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            allowed_roles = ['admin', 'owner']
            if user_role not in allowed_roles:
                raise PermissionDenied("Only admin and owner users can modify workflows")
        
        return super().get_permissions()


class WorkflowChatViewSet(viewsets.GenericViewSet):
    """Chat integration endpoints for workflow"""
    permission_classes = [permissions.IsAuthenticated, IsOrganizationMember]
    
    @action(detail=False, methods=['get'], url_path='workflow-rooms')
    def workflow_rooms(self, request):
        """Get all chat rooms related to user's workflow documents"""
        try:
            from chat.models import ChatRoom
            from chat.serializers import ChatRoomSerializer
            
            if is_user_owner(request.user):
                org = get_user_organization(request.user)
                approval_rooms = ChatRoom.objects.filter(
                    Q(approvalchatroom__approval_flow__document__organization=org) |
                    Q(name__startswith='approval-')
                ).distinct()
            else:
                approval_rooms = ChatRoom.objects.filter(
                    Q(approvalchatroom__approval_flow__current_approver=request.user) |
                    Q(approvalchatroom__approval_flow__document__created_by=request.user) |
                    Q(roommembership__user=request.user, name__startswith='approval-')
                ).distinct()
            
            serializer = ChatRoomSerializer(approval_rooms, many=True, context={'request': request})
            return Response(serializer.data)
            
        except ImportError:
            return Response({'detail': 'Chat app not available'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class WorkflowStatsAPI(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOrganizationMember]
    
    def get(self, request):
        org = get_user_organization(request.user)
        
        user_role = get_user_role(request.user)
        allowed_roles = ['manager', 'admin', 'owner']
        
        if user_role not in allowed_roles:
            raise PermissionDenied("Insufficient permissions to view organization statistics")
        
        from .utils import get_workflow_statistics
        stats = get_workflow_statistics(org.id)
        return Response(stats)


@api_view(['GET'])
def debug_auth(request):
    """Debug endpoint to check authentication and permissions"""
    user = request.user
    
    debug_info = {
        'user': user.email if user.is_authenticated else 'Anonymous',
        'is_authenticated': user.is_authenticated,
        'has_organization_membership': hasattr(user, 'organizationmembership'),
        'user_role': get_user_role(user),
        'is_owner': is_user_owner(user),
    }
    
    # Check JWT token data
    if hasattr(request, 'auth') and request.auth:
        debug_info['jwt_data'] = {
            'organization_role': request.auth.get('organization_role'),
            'has_organization': request.auth.get('has_organization'),
            'user_id': request.auth.get('user_id'),
        }
    
    if hasattr(user, 'organizationmembership'):
        membership = user.organizationmembership
        debug_info.update({
            'organization': membership.organization.name,
            'role': membership.role,
            'role_lower': membership.role.lower(),
            'is_active': membership.is_active,
        })
    
    # Test permission classes
    org_member_perm = IsOrganizationMember()
    can_submit_perm = CanSubmitDocument()
    
    debug_info['permissions'] = {
        'IsOrganizationMember': org_member_perm.has_permission(request, None),
        'CanSubmitDocument': can_submit_perm.has_permission(request, None),
    }
    
    return Response(debug_info)