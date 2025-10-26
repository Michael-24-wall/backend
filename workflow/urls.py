# workflow/utils.py

from django.core.mail import send_mail
from django.conf import settings
from documents.models import Document # Make sure this import path is correct
from django.urls import reverse # Useful for generating a link to the document

def send_approval_notification(document_id):
    """Sends a notification email to the document creator upon final approval."""
    try:
        document = Document.objects.get(pk=document_id)
        creator_user = document.created_by
        
        # NOTE: Adjust this URL generation to match your frontend routing
        document_url = settings.FRONTEND_BASE_URL + reverse('document-detail', args=[document.id]) 
        
        subject = f"✅ Request Approved: {document.title}"
        message = (
            f"Hello {creator_user.first_name or creator_user.username},\n\n"
            f"Your request titled '{document.title}' has been fully approved "
            f"by the entire organizational workflow and is now complete.\n\n"
            f"You can view the final signed document here: {document_url}\n\n"
            f"Thank you."
        )
        
        # Assuming email backend is configured in settings.py
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [creator_user.email],
            fail_silently=False,
        )
    except Document.DoesNotExist:
        print(f"Error: Document {document_id} not found for notification.")
    except Exception as e:
        # Log this error in production
        print(f"Error sending approval email for document {document_id}: {e}")