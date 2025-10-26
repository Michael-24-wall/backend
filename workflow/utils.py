# workflow/utils.py

from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
# NOTE: Ensure the import path for your Document model is correct
from documents.models import Document 

def send_approval_notification(document_id):
    """
    Sends a final approval notification email to the original document creator.
    This function is called after the last step in the DocumentApprovalFlow is approved.
    """
    try:
        # 1. Retrieve the document and creator
        document = Document.objects.get(pk=document_id)
        creator_user = document.created_by
        
        # 2. Define the email content
        subject = f"✅ Request Approved: {document.title}"
        
        # You'll need to define a named URL pattern like 'document-detail' in your documents/urls.py
        # and ensure settings.FRONTEND_BASE_URL is configured.
        try:
            document_path = reverse('document-detail', args=[document.id])
            document_url = f"{settings.FRONTEND_BASE_URL}{document_path}"
        except Exception:
            # Fallback if URL reversal fails
            document_url = "Please log in to the portal to view the document."
        
        message = (
            f"Hello {creator_user.first_name or creator_user.username},\n\n"
            f"Your request titled '{document.title}' has been fully approved "
            f"by the entire organizational workflow and is now complete.\n\n"
            f"You can view the final signed document here: {document_url}\n\n"
            f"Thank you."
        )
        
        # 3. Send the email
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL, # Sender address from settings
            [creator_user.email],        # Recipient address
            fail_silently=False,         # Will raise an error if sending fails
        )
        print(f"Sent final approval email for document {document_id} to {creator_user.email}")
        
    except Document.DoesNotExist:
        # This should ideally not happen if called correctly from the view
        print(f"ERROR: Document {document_id} not found for notification.")
    except Exception as e:
        # Catch network or mail backend errors
        print(f"FATAL ERROR: Failed to send approval email for document {document_id}. Details: {e}")

# NOTE: No other utility functions are needed