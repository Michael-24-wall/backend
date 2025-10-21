# core/utils.py

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.contrib.auth import get_user_model

# ------------------------------------
# 1. Token Generator
# ------------------------------------
class AccountActivationTokenGenerator(PasswordResetTokenGenerator):
    """Generates tokens for account activation."""
    def _make_hash_value(self, user, timestamp):
        """
        Creates a hash value that includes:
        - User ID
        - Timestamp 
        - Verification status
        This ensures tokens become invalid after verification
        """
        return f"{user.pk}{timestamp}{user.is_verified}"

# Create the token generator instance
account_activation_token = AccountActivationTokenGenerator()

# ------------------------------------
# 2. Decoder
# ------------------------------------
def decode_uid_and_token(uidb64, token):
    """
    Decodes the base64 user ID and validates the token.
    Returns user object if valid, None otherwise.
    """
    User = get_user_model()
    
    if not uidb64 or not token:
        return None
        
    try:
        # Decode the user ID from base64
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
        
        # Check if token is valid for this user
        if account_activation_token.check_token(user, token):
            return user
            
    except (TypeError, ValueError, OverflowError):
        # Handle base64 decoding errors
        return None
    except User.DoesNotExist:
        # Handle case where user doesn't exist
        return None
    
    return None


# ------------------------------------
# 3. Custom Permission Check
# ------------------------------------
def is_owner_or_manager(user):
    """
    Checks if the user has a role that allows access management ('owner' or 'manager').
    
    This function was moved here from core/views.py to resolve a circular import.
    It relies on the @property def primary_role on the CustomUser model.
    """
    # Check if user is authenticated and has the primary_role property
    if not user.is_authenticated or not hasattr(user, 'primary_role'):
        return False
    
    # Check if the user's primary role is either 'owner' or 'manager'
    return user.primary_role in ['owner', 'manager']