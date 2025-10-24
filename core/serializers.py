# core/serializers.py

from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db import transaction
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.utils import timezone

from .models import Organization, OrganizationMembership, Invitation

User = get_user_model()

# --- 1. Organization Registration Serializer (Nested) ---
class OrganizationRegistrationSerializer(serializers.ModelSerializer):
    """Used for nested organization creation during user registration."""
    class Meta:
        model = Organization
        fields = ['name']
        ref_name = "OrganizationRegistration"

# --- 2. Simple User Serializer (Re-used for related fields) ---
class SimpleUserSerializer(serializers.ModelSerializer):
    """Minimal serializer for display/read-only user info."""
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name']
        read_only_fields = fields
        ref_name = "SimpleUser"

# --- 3. Invitation Serializer (For POST /send_invite) ---
class InvitationSerializer(serializers.ModelSerializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(
        choices=OrganizationMembership.ROLE_CHOICES, 
        required=False, 
        default='contributor'
    )

    class Meta:
        model = Invitation
        fields = ['email', 'role']
        ref_name = "InvitationCreate"

    def validate_email(self, value):
        # Check if user is already registered
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email is already registered in the system.")
        
        # Check if a pending invitation for this email exists
        if Invitation.objects.filter(email=value, is_accepted=False).exists():
            raise serializers.ValidationError("An active invitation for this email already exists.")
            
        return value

# --- 4. User Registration Serializer ---
class UserRegistrationSerializer(serializers.ModelSerializer):
    organization = OrganizationRegistrationSerializer(required=False, allow_null=True)
    password = serializers.CharField(
        write_only=True, 
        required=True, 
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    password2 = serializers.CharField(
        style={'input_type': 'password'}, 
        write_only=True
    )
    invite_token = serializers.CharField(write_only=True, required=False, allow_blank=True) 

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'password', 'password2', 'organization', 'invite_token']
        extra_kwargs = {
            'first_name': {'required': True},
            'last_name': {'required': True}
        }
        ref_name = "UserRegistration"

    def validate(self, attrs):
        # Password check
        if attrs['password'] != attrs.pop('password2'):
            raise serializers.ValidationError({"password2": "Password fields didn't match."})
            
        # Email uniqueness
        if User.objects.filter(email=attrs['email']).exists():
            raise serializers.ValidationError({"email": "A user with this email already exists."})

        # Handle empty organization object
        has_token = attrs.get('invite_token', None)
        has_org_data = attrs.get('organization', None)
        
        # If organization is an empty dict, remove it to avoid validation errors
        if has_org_data == {}:
            attrs.pop('organization')
            has_org_data = None
        
        # Only validation: cannot have both token and organization data
        if has_token and has_org_data:
            raise serializers.ValidationError({
                "general": "Registration cannot include both an invite token and new organization data."
            })
            
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        token = validated_data.pop('invite_token', None)
        org_data = validated_data.pop('organization', None)
        password = validated_data.pop('password')
        
        # Default settings for standalone registration
        is_verified = False 
        is_active = True
        role = 'individual'  # New role for standalone users
        organization = None
        invitation = None
        
        # --- A. Invitation Registration Flow (Join Organization) ---
        if token:
            try:
                invitation = Invitation.objects.get(
                    token=token, 
                    is_accepted=False, 
                    email=validated_data['email']
                )
                if not invitation.can_accept():
                    raise serializers.ValidationError({
                        "token": "Invitation has expired or has already been used."
                    })
            except Invitation.DoesNotExist:
                raise serializers.ValidationError({
                    "token": "Invalid, expired, or used invitation token for this email."
                })

            organization = invitation.organization
            role = invitation.role
            is_verified = True  # Invited users are automatically verified

        # --- B. Organization Owner Registration Flow (Create Organization) ---
        elif org_data:
            organization = Organization.objects.create(**org_data)
            role = 'owner'
        
        # --- C. Standalone Registration Flow (No Organization) ---
        else:
            # User registers without organization - they can join one later via invites
            role = 'individual'
            is_verified = False  # Still need email verification

        # Create User
        user = User.objects.create_user(
            email=validated_data['email'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            password=password, 
            organization=organization,
            is_verified=is_verified,    
            is_active=is_active,        
        )
        
        # Create Membership only if user has an organization
        if organization:
            OrganizationMembership.objects.create(
                user=user,
                organization=organization,
                role=role
            )

        # Mark invitation as accepted
        if invitation:
            invitation.is_accepted = True
            invitation.save()
            
        return user

# --- 5. User Serializer (for responses) ---
class UserSerializer(serializers.ModelSerializer):
    organization_role = serializers.SerializerMethodField()
    date_joined = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S.%fZ', read_only=True)
    organization_name = serializers.SerializerMethodField()
    has_valid_organization = serializers.SerializerMethodField()  # ADDED
    
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'is_verified', 'is_active', 'date_joined', 'organization_role', 'organization_name', 'has_valid_organization']
        read_only_fields = ['id', 'is_verified', 'is_active', 'date_joined', 'organization_role', 'organization_name', 'has_valid_organization']
        ref_name = "UserDetail"
    
    def get_organization_role(self, obj):
        return obj.primary_role
    
    def get_organization_name(self, obj):
        return obj.organization.name if obj.organization else None
    
    def get_has_valid_organization(self, obj):  # ADDED
        return obj.has_valid_organization

# --- 6. Organization Serializer (for responses) ---
class OrganizationSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S.%fZ', read_only=True)
    
    class Meta:
        model = Organization
        fields = ['id', 'name', 'subdomain', 'is_active', 'created_at']
        ref_name = "OrganizationDetail"

# --- 7. Invitation Response Serializer ---
class InvitationResponseSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S.%fZ', read_only=True)
    expires_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S.%fZ', read_only=True)
    invited_by = SimpleUserSerializer(read_only=True)
    organization = OrganizationSerializer(read_only=True)
    
    class Meta:
        model = Invitation
        fields = ['id', 'email', 'role', 'token', 'organization', 'invited_by', 'is_accepted', 'created_at', 'expires_at', 'message']
        read_only_fields = fields
        ref_name = "InvitationResponse"

# --- 8. Join Organization Serializer ---
class JoinOrganizationSerializer(serializers.Serializer):
    """Serializer for joining an organization with an invite token"""
    invite_token = serializers.CharField(required=True)
    
    def validate_invite_token(self, value):
        try:
            invitation = Invitation.objects.get(
                token=value,
                is_accepted=False
            )
            
            if not invitation.can_accept():
                raise serializers.ValidationError("Invitation has expired or has already been used.")
                
            # Check if the invitation email matches the user's email
            user = self.context['request'].user
            if invitation.email.lower() != user.email.lower():
                raise serializers.ValidationError("This invitation is not for your email address.")
                
        except Invitation.DoesNotExist:
            raise serializers.ValidationError("Invalid or expired invitation token.")
            
        return value

    @transaction.atomic
    def join_organization(self, user):
        token = self.validated_data['invite_token']
        invitation = Invitation.objects.get(token=token, is_accepted=False)
        
        # Update user's organization
        user.organization = invitation.organization
        user.save()
        
        # Create membership
        OrganizationMembership.objects.create(
            user=user,
            organization=invitation.organization,
            role=invitation.role
        )
        
        # Mark invitation as accepted
        invitation.is_accepted = True
        invitation.save()
        
        return user

# --- 9. Custom JWT Login Serializer ---
class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    
    def validate(self, attrs):
        # Call parent validation first
        data = super().validate(attrs)
        
        # Now self.user is available
        user = self.user
        
        # DEBUG: Check organization status
        print(f"🔍 LOGIN DEBUG - User: {user.email}")
        print(f"🔍 LOGIN DEBUG - Organization ID: {user.organization_id}")
        print(f"🔍 LOGIN DEBUG - Organization: {user.organization}")
        print(f"🔍 LOGIN DEBUG - Primary Role: {user.primary_role}")
        print(f"🔍 LOGIN DEBUG - Has Valid Organization: {user.has_valid_organization}")
        
        # Check if user is verified
        if not user.is_verified:
            raise serializers.ValidationError({
                'detail': 'Please verify your email address before logging in.'
            })

        # Check if user is active
        if not user.is_active:
            raise serializers.ValidationError({
                'detail': 'This account has been deactivated.'
            })
        
        # Add user data to response - USING SAFE PROPERTIES
        data['user'] = {
            'id': user.id,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'is_verified': user.is_verified,
            'organization_role': user.primary_role,  # Now safe from models fix
            'has_organization': user.has_valid_organization  # Using the new safe property
        }
        
        return data

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        
        # Add custom claims to token - USING SAFE PROPERTIES
        token['email'] = user.email
        token['first_name'] = user.first_name
        token['last_name'] = user.last_name
        token['is_verified'] = user.is_verified
        token['organization_role'] = user.primary_role  # Now safe from models fix
        token['has_organization'] = user.has_valid_organization  # Using the new safe property
        return token