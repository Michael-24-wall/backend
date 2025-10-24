# core/models.py

from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.text import slugify
import uuid
from django.utils import timezone
from datetime import timedelta

# Custom User Manager
class CustomUserManager(BaseUserManager):
    """
    Custom user model manager where email is the unique identifier
    for authentication instead of username.
    """
    def create_user(self, email, password=None, **extra_fields):
        """
        Create and save a User with the given email and password.
        """
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """
        Create and save a SuperUser with the given email and password.
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_verified', True)  # Superusers are automatically verified

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)

# --- 1. Organization (Tenant) Model ---
class Organization(models.Model):
    name = models.CharField(max_length=150, unique=True)
    subdomain = models.SlugField(max_length=150, unique=True, editable=False) 
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Organization"
        verbose_name_plural = "Organizations"
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.subdomain:
            base_subdomain = slugify(self.name)
            self.subdomain = base_subdomain
            # Handle duplicate subdomains
            counter = 1
            while Organization.objects.filter(subdomain=self.subdomain).exists():
                self.subdomain = f"{base_subdomain}-{counter}"
                counter += 1
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.name
    
    @property
    def active_members_count(self):
        """Count of active members in the organization"""
        return self.organizationmembership_set.filter(is_active=True).count()
    
    @property
    def owner(self):
        """Get the owner of the organization"""
        owner_membership = self.organizationmembership_set.filter(role='owner', is_active=True).first()
        return owner_membership.user if owner_membership else None

# --- 2. CustomUser Model ---
class CustomUser(AbstractUser):
    username = None 
    email = models.EmailField(unique=True) 
    
    is_verified = models.BooleanField(default=False)
    # The organization the user primarily belongs to
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.SET_NULL, 
        related_name='primary_members', 
        null=True, blank=True,
        help_text="Primary organization for this user"
    )
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']
    
    objects = CustomUserManager()
    
    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ['email']
    
    def __str__(self):
        return self.email
    
    # HELPER METHODS - FIXED THESE PROPERTIES
    @property
    def primary_membership(self):
        """Get the membership for the user's primary organization"""
        if self.organization:
            try:
                return self.organizationmembership_set.filter(
                    organization=self.organization,
                    is_active=True
                ).first()
            except Exception:
                # If there's any issue accessing the membership, return None
                return None
        return None
    
    @property 
    def primary_role(self):
        """Get the role in primary organization - FIXED WITH BETTER ERROR HANDLING"""
        if not self.organization:
            return 'individual'
        
        membership = self.primary_membership
        if membership and hasattr(membership, 'role'):
            return membership.role
        
        # If organization exists but no membership, it's an inconsistent state
        # Return 'individual' to prevent errors
        return 'individual'
    
    @property
    def has_valid_organization(self):
        """Check if user has a valid organization with proper membership"""
        if not self.organization:
            return False
        
        # Check if organization actually exists in database
        try:
            Organization.objects.get(id=self.organization.id)
        except Organization.DoesNotExist:
            return False
        
        # Check if membership exists
        return self.primary_membership is not None
    
    @property
    def full_name(self):
        """Get user's full name"""
        return f"{self.first_name} {self.last_name}".strip()
    
    def get_all_organizations(self):
        """Get all organizations the user belongs to"""
        return Organization.objects.filter(
            organizationmembership__user=self,
            organizationmembership__is_active=True
        ).distinct()
    
    def has_organization_role(self, organization, role):
        """Check if user has specific role in organization"""
        return self.organizationmembership_set.filter(
            organization=organization,
            role=role,
            is_active=True
        ).exists()

# --- 3. OrganizationMembership (RBAC Link) ---
class OrganizationMembership(models.Model):
    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('ceo', 'CEO'),     
        ('manager', 'Manager'),
        ('assistant_manager', 'Assistant Manager'),
        ('accountant', 'Accountant'),
        ('hr', 'HR'),
        ('administrator', 'Administrator'),
        ('staff', 'Staff'),
        ('contributor', 'Contributor'),
        ('individual', 'Individual'),  # ADDED FOR STANDALONE USERS
    ]

    ROLE_HIERARCHY = {
        'owner': 100,
        'ceo': 90,
        'manager': 80,
        'administrator': 75,
        'assistant_manager': 70,
        'hr': 60,
        'accountant': 50,
        'staff': 40,
        'contributor': 30,
        'individual': 0,  # ADDED FOR STANDALONE USERS
    }

    user = models.ForeignKey(
        CustomUser, 
        on_delete=models.CASCADE,
        related_name='organizationmembership_set'
    )
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE,
        related_name='organizationmembership_set'
    )
    role = models.CharField(
        max_length=50, 
        choices=ROLE_CHOICES, 
        default='staff',
        help_text="User's role within the organization"
    ) 
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'organization') 
        verbose_name = "Organization Membership"
        verbose_name_plural = "Organization Memberships"
        ordering = ['-created_at']

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"{self.user.email} as {self.get_role_display()} in {self.organization.name} ({status})"

    def save(self, *args, **kwargs):
        # Ensure user's primary organization is set if this is their first membership
        if not self.user.organization and self.is_active:
            self.user.organization = self.organization
            self.user.save()
        
        # If this is an owner role, ensure only one owner per organization
        if self.role == 'owner' and self.is_active:
            OrganizationMembership.objects.filter(
                organization=self.organization, 
                role='owner',
                is_active=True
            ).exclude(pk=self.pk).update(role='administrator')
        
        super().save(*args, **kwargs)

    @property
    def role_weight(self):
        """Get numerical weight of the role for permission comparisons"""
        return self.ROLE_HIERARCHY.get(self.role, 0)
    
    def has_permission_over(self, other_role):
        """Check if this role has permission over another role"""
        return self.role_weight >= self.ROLE_HIERARCHY.get(other_role, 0)

# --- 4. Invitation Model ---
class Invitation(models.Model):
    email = models.EmailField(
        help_text="Email address of the person being invited"
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE,
        related_name='invitations'
    )
    role = models.CharField(
        max_length=50, 
        choices=OrganizationMembership.ROLE_CHOICES, 
        default='contributor',
        help_text="Role the user will have upon acceptance"
    )
    invited_by = models.ForeignKey(
        CustomUser, 
        on_delete=models.CASCADE, 
        related_name='sent_invitations',
        help_text="User who sent this invitation"
    )
    is_accepted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Optional expiration date for the invitation"
    )
    message = models.TextField(
        blank=True, 
        null=True,
        help_text="Optional personal message to include with the invitation"
    )

    class Meta:
        unique_together = ('email', 'organization', 'is_accepted')
        verbose_name = "Invitation"
        verbose_name_plural = "Invitations"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['token']),
            models.Index(fields=['email', 'is_accepted']),
        ]
    
    def __str__(self):
        status = "Accepted" if self.is_accepted else "Pending"
        return f"Invitation for {self.email} to {self.organization.name} ({status})"
    
    def save(self, *args, **kwargs):
        # Set default expiry (7 days from creation) if not provided
        if not self.expires_at and not self.pk:
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)
    
    @property
    def is_expired(self):
        """Check if the invitation has expired"""
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False
    
    def can_accept(self):
        """Check if the invitation can be accepted"""
        return not self.is_accepted and not self.is_expired
    
    @property
    def days_until_expiry(self):
        """Get number of days until expiry (negative if expired)"""
        if self.expires_at:
            delta = self.expires_at - timezone.now()
            return delta.days
        return None