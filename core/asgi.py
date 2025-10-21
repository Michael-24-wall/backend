# core/asgi.py

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from chat import routing  # Import the chat app's WebSocket routing

# Get the default Django HTTP application
django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    # HTTP requests are handled by the standard Django ASGI app (includes DRF/Swagger)
    "http": django_asgi_app,

    # WebSocket connections are handled by Channels
    "websocket": AuthMiddlewareStack(
        URLRouter(
            routing.websocket_urlpatterns
        )
    ),
})