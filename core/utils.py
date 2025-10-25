# core/utils.py

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

class AccountActivationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        return (
            str(user.pk) + str(timestamp) + 
            str(user.is_active) + str(user.is_verified)
        )

class PasswordResetTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        return (
            str(user.pk) + str(timestamp) + 
            str(user.is_active) + str(user.password)
        )

# Create instances of the token generators
account_activation_token = AccountActivationTokenGenerator()
password_reset_token = PasswordResetTokenGenerator()

def decode_uid_and_token(uidb64, token):
    """
    Decode user ID from base64 and validate token.
    Returns user if valid, None otherwise.
    """
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        
        # Try to get user by primary key
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        try:
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return None
        
        # Check if token is valid for account activation
        if account_activation_token.check_token(user, token):
            return user
        
        # Also check if token is valid for password reset (for backward compatibility)
        if password_reset_token.check_token(user, token):
            return user
            
        return None
        
    except (TypeError, ValueError, OverflowError):
        return None

def decode_uid(uidb64):
    """
    Decode user ID from base64 string
    """
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        return uid
    except (TypeError, ValueError, OverflowError):
        return None