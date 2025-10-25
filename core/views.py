# core/views.py

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth.password_validation import validate_password
from django.db.models import Count

from .utils import account_activation_token, decode_uid_and_token
from .serializers import (
    UserRegistrationSerializer, 
    CustomTokenObtainPairSerializer, 
    UserSerializer,
    InvitationSerializer,
    InvitationResponseSerializer,
    OrganizationSerializer,
    JoinOrganizationSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    ChangePasswordSerializer,
)
from .models import Organization, Invitation, OrganizationMembership 

User = get_user_model()


# ----------------------------------------------------------------------
# --- 1. Custom JWT View (Login) ---------------------------------------
# ----------------------------------------------------------------------
class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    
    @swagger_auto_schema(
        operation_description="Obtains JWT Access and Refresh tokens. Requires verified email.",
        responses={
            200: openapi.Response(
                description="Tokens and user data",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'refresh': openapi.Schema(type=openapi.TYPE_STRING),
                        'access': openapi.Schema(type=openapi.TYPE_STRING),
                        'user': openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'email': openapi.Schema(type=openapi.TYPE_STRING),
                                'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                                'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                                'is_verified': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                                'organization_role': openapi.Schema(type=openapi.TYPE_STRING),
                            }
                        )
                    }
                )
            ),
            401: 'Invalid Credentials / Email Not Verified.'
        }
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


# ----------------------------------------------------------------------
# --- 2. Auth ViewSet (Registration & Verification) --------------------
# ----------------------------------------------------------------------
class AuthViewSet(viewsets.GenericViewSet):
    """Handles User Registration and Email Verification."""
    permission_classes = [AllowAny]

    def get_serializer_class(self):
        """
        Return appropriate serializer class based on action
        """
        if self.action == 'register':
            return UserRegistrationSerializer
        elif self.action in ['profile', 'update_profile']:
            return UserSerializer
        elif self.action == 'join_organization':
            return JoinOrganizationSerializer
        elif self.action == 'forgot_password':
            return PasswordResetRequestSerializer
        elif self.action == 'password_reset_confirm':
            return PasswordResetConfirmSerializer
        elif self.action == 'change_password':
            return ChangePasswordSerializer
        # For other actions that don't need a serializer, return None
        return None

    # --- Helper Method to Send Email ---
    def _send_verification_email(self, user, request):
        try:
            domain = request.get_host()
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = account_activation_token.make_token(user)
            
            verification_url = f"{request.scheme}://{domain}/api/auth/verify_email/?uidb64={uid}&token={token}"
            
            mail_subject = 'Activate your Paperless SaaS Account'
            message = render_to_string('core/acc_active_email.html', {
                'user': user,
                'domain': domain,
                'verification_url': verification_url,
                'token': token,
                'protocol': request.scheme,
            })
            
            to_email = user.email
            email = EmailMessage(mail_subject, message, to=[to_email])
            email.content_subtype = "html"
            email.send()
            
            print(f"✅ Verification email sent to: {to_email}")
        except Exception as e:
            print(f"❌ Failed to send verification email: {str(e)}")

    # --- Helper Method to Send Password Reset Email ---
    def _send_password_reset_email(self, user, request):
        """Send password reset email to user"""
        try:
            domain = request.get_host()
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = account_activation_token.make_token(user)
            
            reset_url = f"{request.scheme}://{domain}/api/auth/password_reset_confirm/?uidb64={uid}&token={token}"
            
            mail_subject = 'Reset your Paperless SaaS Password'
            message = render_to_string('core/password_reset_email.html', {
                'user': user,
                'domain': domain,
                'reset_url': reset_url,
                'token': token,
                'protocol': request.scheme,
            })
            
            to_email = user.email
            email = EmailMessage(mail_subject, message, to=[to_email])
            email.content_subtype = "html"
            email.send()
            
            print(f"✅ Password reset email sent to: {to_email}")
        except Exception as e:
            print(f"❌ Failed to send password reset email: {str(e)}")

    # --- 2.1. Registration Endpoint ---
    @swagger_auto_schema(
        operation_description="Register a new user. Can be Organization Owner (with org data) or Invited User (with token) or Standalone User (no org).",
        request_body=UserRegistrationSerializer,
        responses={
            201: openapi.Response(
                description="Registration successful",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'message': openapi.Schema(type=openapi.TYPE_STRING),
                        'user': openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'email': openapi.Schema(type=openapi.TYPE_STRING),
                                'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                                'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                                'is_verified': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                                'is_active': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                                'date_joined': openapi.Schema(type=openapi.TYPE_STRING),
                                'organization_role': openapi.Schema(type=openapi.TYPE_STRING),
                            }
                        )
                    }
                )
            ),
            400: 'Bad Request'
        }
    )
    @action(detail=False, methods=['post'])
    def register(self, request):
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            
            if not user.is_verified:
                self._send_verification_email(user, request)
                message = 'Registration successful. Please check your email to verify your account.'
            else:
                message = 'Registration successful. You can now log in.'
            
            return Response({
                'message': message,
                'user': UserSerializer(user).data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # --- 2.2. Email Verification Endpoint ---
    @swagger_auto_schema(
        operation_description="Activates a user account using the UID and Token from the email link.",
        manual_parameters=[
            openapi.Parameter('uidb64', openapi.IN_QUERY, type=openapi.TYPE_STRING, description='Base64 encoded user ID.', required=True),
            openapi.Parameter('token', openapi.IN_QUERY, type=openapi.TYPE_STRING, description='Verification token.', required=True),
        ],
        responses={
            200: openapi.Response(
                description="Account activated successfully",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'message': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            ),
            400: openapi.Response(
                description="Invalid verification link",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'error': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            )
        }
    )
    @action(detail=False, methods=['get'])
    def verify_email(self, request):
        uidb64 = request.query_params.get('uidb64')
        token = request.query_params.get('token')
        
        if not uidb64 or not token:
            return Response({'error': 'Missing verification parameters.'}, status=status.HTTP_400_BAD_REQUEST)
        
        user = decode_uid_and_token(uidb64, token)

        if user is not None and not user.is_verified:
            user.is_verified = True
            user.is_active = True
            user.save()
            return Response(
                {'message': 'Account successfully activated and email verified. You can now log in.'}, 
                status=status.HTTP_200_OK
            )
        
        return Response(
            {'error': 'Verification link is invalid, expired, or the account is already verified.'}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    # --- 2.3. Resend Verification Email Endpoint ---
    @swagger_auto_schema(
        operation_description="Resend verification email for unverified accounts.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'email': openapi.Schema(type=openapi.TYPE_STRING, description='User email address'),
            },
            required=['email']
        ),
        responses={
            200: openapi.Response(
                description="Verification email sent",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'message': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            ),
            400: openapi.Response(
                description="Account already verified",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'error': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            ),
            404: openapi.Response(
                description="User not found",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'error': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            )
        }
    )
    @action(detail=False, methods=['post'])
    def resend_verification(self, request):
        email = request.data.get('email')
        
        if not email:
            return Response(
                {'error': 'Email address is required.'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user = User.objects.get(email=email)
            
            if user.is_verified:
                return Response(
                    {'error': 'Account is already verified.'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            self._send_verification_email(user, request)
            
            return Response(
                {'message': 'Verification email sent successfully.'}, 
                status=status.HTTP_200_OK
            )
            
        except User.DoesNotExist:
            return Response(
                {'error': 'User with this email address does not exist.'}, 
                status=status.HTTP_404_NOT_FOUND
            )

    # --- 2.4. User Profile Endpoint ---
    @swagger_auto_schema(
        operation_description="Get current user profile information",
        responses={
            200: openapi.Response(
                description="User profile data",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'email': openapi.Schema(type=openapi.TYPE_STRING),
                        'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                        'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                        'is_verified': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        'is_active': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        'date_joined': openapi.Schema(type=openapi.TYPE_STRING),
                        'organization_role': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            ),
            401: 'Authentication credentials were not provided.'
        }
    )
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def profile(self, request):
        """Get current user profile"""
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    # --- 2.5. Update Profile Endpoint ---
    @swagger_auto_schema(
        method='put',
        operation_description="Full update of user profile",
        request_body=UserSerializer,
        responses={
            200: openapi.Response(
                description="Updated user profile",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'email': openapi.Schema(type=openapi.TYPE_STRING),
                        'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                        'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                        'is_verified': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        'is_active': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        'date_joined': openapi.Schema(type=openapi.TYPE_STRING),
                        'organization_role': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            ),
            400: 'Bad Request'
        }
    )
    @swagger_auto_schema(
        method='patch',
        operation_description="Partial update of user profile",
        request_body=UserSerializer,
        responses={
            200: openapi.Response(
                description="Updated user profile",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'email': openapi.Schema(type=openapi.TYPE_STRING),
                        'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                        'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                        'is_verified': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        'is_active': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        'date_joined': openapi.Schema(type=openapi.TYPE_STRING),
                        'organization_role': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            ),
            400: 'Bad Request'
        }
    )
    @action(detail=False, methods=['put', 'patch'], permission_classes=[IsAuthenticated])
    def update_profile(self, request):
        """Update current user profile"""
        partial = request.method == 'PATCH'
        serializer = UserSerializer(
            request.user, 
            data=request.data, 
            partial=partial
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # --- 2.6. Change Password Endpoint (Updated with Serializer) ---
    @swagger_auto_schema(
        operation_description="Change user password",
        request_body=ChangePasswordSerializer,
        responses={
            200: openapi.Response(
                description="Password changed successfully",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'message': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            ),
            400: 'Bad Request'
        }
    )
    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def change_password(self, request):
        """Change user password using serializer"""
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(data=request.data, context={'request': request})
        
        if serializer.is_valid():
            user = request.user
            new_password = serializer.validated_data['new_password']
            
            user.set_password(new_password)
            user.save()
            
            return Response({
                'message': 'Password changed successfully.'
            }, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # --- 2.7. Forgot Password / Password Reset Request Endpoint ---
    @swagger_auto_schema(
        operation_description="Request password reset email",
        request_body=PasswordResetRequestSerializer,
        responses={
            200: openapi.Response(
                description="Password reset email sent if account exists",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'message': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            ),
            400: 'Bad Request'
        }
    )
    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def forgot_password(self, request):
        """Handle password reset request using serializer"""
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(data=request.data)
        
        if serializer.is_valid():
            email = serializer.validated_data['email']
            
            try:
                user = User.objects.get(email=email)
                # Send password reset email only if user exists and is active
                if user.is_active:
                    self._send_password_reset_email(user, request)
                    print(f"✅ Password reset email sent to: {email}")
                else:
                    print(f"⚠️ User {email} is inactive, skipping password reset email")
                
            except User.DoesNotExist:
                # For security, don't reveal whether email exists
                print(f"⚠️ Password reset requested for non-existent email: {email}")
                pass
            
            return Response({
                'message': 'If an account with this email exists, a password reset link has been sent.'
            }, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # --- 2.8. Password Reset Confirm Endpoint ---
    @swagger_auto_schema(
        operation_description="Confirm password reset with token",
        request_body=PasswordResetConfirmSerializer,
        responses={
            200: openapi.Response(
                description="Password reset successful",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'message': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            ),
            400: 'Invalid token or bad request'
        }
    )
    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def password_reset_confirm(self, request):
        """Confirm password reset with token using serializer"""
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(data=request.data)
        
        if serializer.is_valid():
            uidb64 = serializer.validated_data['uidb64']
            token = serializer.validated_data['token']
            new_password = serializer.validated_data['new_password']
            
            # Decode user ID and validate token using existing utility
            user = decode_uid_and_token(uidb64, token)

            if user is not None:
                user.set_password(new_password)
                user.save()
                
                return Response({
                    'message': 'Password has been reset successfully. You can now log in with your new password.'
                }, status=status.HTTP_200_OK)
            
            return Response({
                'error': 'Invalid or expired reset link.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # --- 2.9. Join Organization Endpoint ---
    @swagger_auto_schema(
        operation_description="Join an organization using an invite token",
        request_body=JoinOrganizationSerializer,
        responses={
            200: openapi.Response(
                description="Successfully joined organization",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'message': openapi.Schema(type=openapi.TYPE_STRING),
                        'user': openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'email': openapi.Schema(type=openapi.TYPE_STRING),
                                'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                                'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                                'is_verified': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                                'is_active': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                                'date_joined': openapi.Schema(type=openapi.TYPE_STRING),
                                'organization_role': openapi.Schema(type=openapi.TYPE_STRING),
                            }
                        )
                    }
                )
            ),
            400: 'Bad Request'
        }
    )
    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def join_organization(self, request):
        """Allow existing users to join an organization using an invite token"""
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(data=request.data, context={'request': request})
        
        if serializer.is_valid():
            user = serializer.join_organization(request.user)
            return Response({
                'message': f'Successfully joined {user.organization.name}',
                'user': UserSerializer(user).data
            }, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ----------------------------------------------------------------------
# --- 3. Organization Management ViewSet -------------------------------
# ----------------------------------------------------------------------
class OrganizationViewSet(viewsets.GenericViewSet):
    """Handles Organization and Invitation Management."""
    permission_classes = [IsAuthenticated]
    
    # Define roles a manager can invite people to - UPDATED WITH HR
    MANAGER_ALLOWED_ROLES = [
        'contributor', 
        'staff',
        'assistant_manager'
    ]
    
    # Define roles HR can invite people to - ADDED HR PERMISSIONS
    HR_ALLOWED_ROLES = [
        'contributor',
        'staff',
        'hr'  # HR can invite other HR staff
    ]

    def get_serializer_class(self):
        """
        Return appropriate serializer class based on action
        """
        if self.action == 'send_invitation':
            return InvitationSerializer
        elif self.action == 'my_organization':
            return OrganizationSerializer
        return None

    # --- Helper Method to Send Invitation Email ---
    def _send_invitation_email(self, invitation, request):
        """Send invitation email to the invited user"""
        try:
            domain = request.get_host()
            invite_url = f"{request.scheme}://{domain}/register?invite_token={invitation.token}"
            
            mail_subject = f'Invitation to join {invitation.organization.name} on Paperless SaaS'
            message = render_to_string('core/invitation_email.html', {
                'invitation': invitation,
                'invite_url': invite_url,
                'domain': domain,
                'protocol': request.scheme,
            })
            
            to_email = invitation.email
            email = EmailMessage(mail_subject, message, to=[to_email])
            email.content_subtype = "html"
            email.send()
            
            print(f"✅ Invitation email sent to: {to_email}")
            return True
        except Exception as e:
            print(f"❌ Failed to send invitation email: {str(e)}")
            return False

    # --- Helper function to check if user is owner, manager, or HR ---
    def _is_owner_manager_or_hr(self, user):
        """Check if user has owner, manager, or HR role in their organization"""
        # USE THE SAFE PROPERTY INSTEAD OF DIRECT CHECK
        if not user.has_valid_organization:
            return False
            
        membership = OrganizationMembership.objects.filter(
            user=user,
            organization=user.organization,
            is_active=True
        ).first()
        
        return membership and membership.role in ['owner', 'manager', 'ceo', 'administrator', 'hr']

    # --- 3.1. Send Invitation Endpoint - UPDATED WITH HR ---
    @swagger_auto_schema(
        operation_description="Send invitation to join organization (Owner: Any Role; Manager: Contributor/Staff/Assistant only; HR: Contributor/Staff/HR only).",
        request_body=InvitationSerializer,
        responses={
            201: openapi.Response(
                description="Invitation sent successfully",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'message': openapi.Schema(type=openapi.TYPE_STRING),
                        'invitation': openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'email': openapi.Schema(type=openapi.TYPE_STRING),
                                'role': openapi.Schema(type=openapi.TYPE_STRING),
                                'token': openapi.Schema(type=openapi.TYPE_STRING),
                                'is_accepted': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                                'created_at': openapi.Schema(type=openapi.TYPE_STRING),
                                'expires_at': openapi.Schema(type=openapi.TYPE_STRING),
                                'message': openapi.Schema(type=openapi.TYPE_STRING),
                            }
                        )
                    }
                )
            ),
            400: 'Bad Request',
            403: 'You do not have the required role to send invitations or invite to this role.'
        }
    )
    @action(detail=False, methods=['post'])
    def send_invitation(self, request):
        """Send invitation to join organization (Owners, Managers, and HR only)"""
        user = request.user
        
        # 1. Permission Check: Must be Owner, Manager, or HR
        if not self._is_owner_manager_or_hr(user):
            return Response(
                {'error': 'Only organization owners, managers, or HR can send invitations.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(data=request.data)
        if serializer.is_valid():
            invited_role = serializer.validated_data.get('role', 'contributor')
            
            # 2. Role Hierarchy Check based on user's role
            user_role = user.primary_role
            
            # Managers cannot invite to high-level roles
            if user_role in ['manager', 'assistant_manager']:
                if invited_role not in self.MANAGER_ALLOWED_ROLES:
                    return Response(
                        {'role': f"Managers can only invite users to the roles: {', '.join(self.MANAGER_ALLOWED_ROLES)}."},
                        status=status.HTTP_403_FORBIDDEN
                    )
            
            # HR can only invite to specific roles - ADDED HR CHECK
            if user_role == 'hr':
                if invited_role not in self.HR_ALLOWED_ROLES:
                    return Response(
                        {'role': f"HR can only invite users to the roles: {', '.join(self.HR_ALLOWED_ROLES)}."},
                        status=status.HTTP_403_FORBIDDEN
                    )

            # 3. Create invitation
            invitation = serializer.save(
                organization=user.organization,
                invited_by=user
            )
            
            # 4. Send invitation email
            email_sent = self._send_invitation_email(invitation, request)
            
            if email_sent:
                message = f'Invitation sent to {invitation.email}'
            else:
                message = f'Invitation created for {invitation.email} but email failed to send. Token: {invitation.token}'
            
            # Use the response serializer for the response
            response_serializer = InvitationResponseSerializer(invitation)
            return Response({
                'message': message,
                'invitation': response_serializer.data
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # --- 3.2. Get Organization Details ---
    @swagger_auto_schema(
        operation_description="Get current user's organization details",
        responses={
            200: openapi.Response(
                description="Organization details",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'name': openapi.Schema(type=openapi.TYPE_STRING),
                        'subdomain': openapi.Schema(type=openapi.TYPE_STRING),
                        'is_active': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        'created_at': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            ),
            404: 'Organization not found'
        }
    )
    @action(detail=False, methods=['get'])
    def my_organization(self, request):
        """Get current user's organization details"""
        # USE THE SAFE PROPERTY INSTEAD OF DIRECT CHECK
        if not request.user.has_valid_organization:
            return Response(
                {'error': 'User does not belong to any organization or organization is invalid.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        organization = request.user.organization
        serializer = OrganizationSerializer(organization)
        return Response(serializer.data)

    # --- 3.3. Get Pending Invitations - UPDATED WITH HR ---
    @swagger_auto_schema(
        operation_description="Get pending invitations for organization (Owners, Managers, and HR only)",
        responses={
            200: openapi.Response(
                description="List of pending invitations",
                schema=openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                            'email': openapi.Schema(type=openapi.TYPE_STRING),
                            'role': openapi.Schema(type=openapi.TYPE_STRING),
                            'token': openapi.Schema(type=openapi.TYPE_STRING),
                            'is_accepted': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                            'created_at': openapi.Schema(type=openapi.TYPE_STRING),
                            'expires_at': openapi.Schema(type=openapi.TYPE_STRING),
                            'message': openapi.Schema(type=openapi.TYPE_STRING),
                        }
                    )
                )
            ),
            403: 'Only organization owners, managers, or HR can view invitations'
        }
    )
    @action(detail=False, methods=['get'])
    def pending_invitations(self, request):
        """Get pending invitations for organization (Owners, Managers, and HR only)"""
        user = request.user

        # Permission Check: Must be Owner, Manager, or HR
        if not self._is_owner_manager_or_hr(user):
            return Response(
                {'error': 'Only organization owners, managers, or HR can view invitations.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # USE THE SAFE PROPERTY INSTEAD OF DIRECT CHECK
        if not user.has_valid_organization:
            return Response(
                {'error': 'User organization not found or invalid.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        invitations = Invitation.objects.filter(
            organization=user.organization,
            is_accepted=False
        )
        serializer = InvitationResponseSerializer(invitations, many=True)
        return Response(serializer.data)

    # --- 3.4. Get Organization Members - ADDED HR ACCESS ---
    @swagger_auto_schema(
        operation_description="Get organization members list (Owners, Managers, and HR only)",
        responses={
            200: openapi.Response(
                description="List of organization members",
                schema=openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                            'email': openapi.Schema(type=openapi.TYPE_STRING),
                            'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                            'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                            'is_verified': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                            'is_active': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                            'date_joined': openapi.Schema(type=openapi.TYPE_STRING),
                            'organization_role': openapi.Schema(type=openapi.TYPE_STRING),
                        }
                    )
                )
            ),
            403: 'Only organization owners, managers, or HR can view members'
        }
    )
    @action(detail=False, methods=['get'])
    def members(self, request):
        """Get organization members (Owners, Managers, and HR only)"""
        user = request.user

        # Permission Check: Must be Owner, Manager, or HR
        if not self._is_owner_manager_or_hr(user):
            return Response(
                {'error': 'Only organization owners, managers, or HR can view members.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # USE THE SAFE PROPERTY INSTEAD OF DIRECT CHECK
        if not user.has_valid_organization:
            return Response(
                {'error': 'User organization not found or invalid.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        members = User.objects.filter(organization=user.organization)
        serializer = UserSerializer(members, many=True)
        return Response(serializer.data)

    # --- 3.5. Get Organization Statistics - ADDED HR ACCESS ---
    @swagger_auto_schema(
        operation_description="Get organization statistics (Owners, Managers, and HR only)",
        responses={
            200: openapi.Response(
                description="Organization statistics",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'total_members': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'active_members': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'pending_invitations': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'role_distribution': openapi.Schema(type=openapi.TYPE_OBJECT),
                    }
                )
            ),
            403: 'Only organization owners, managers, or HR can view statistics'
        }
    )
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get organization statistics (Owners, Managers, and HR only)"""
        user = request.user

        # Permission Check: Must be Owner, Manager, or HR
        if not self._is_owner_manager_or_hr(user):
            return Response(
                {'error': 'Only organization owners, managers, or HR can view statistics.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # USE THE SAFE PROPERTY INSTEAD OF DIRECT CHECK
        if not user.has_valid_organization:
            return Response(
                {'error': 'User organization not found or invalid.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        organization = user.organization
        total_members = User.objects.filter(organization=organization).count()
        active_members = User.objects.filter(organization=organization, is_active=True).count()
        pending_invitations = Invitation.objects.filter(organization=organization, is_accepted=False).count()
        
        # Role distribution
        role_distribution = dict(
            User.objects.filter(organization=organization)
            .values('primary_role')
            .annotate(count=Count('id'))
            .values_list('primary_role', 'count')
        )
        
        return Response({
            'total_members': total_members,
            'active_members': active_members,
            'pending_invitations': pending_invitations,
            'role_distribution': role_distribution,
        })