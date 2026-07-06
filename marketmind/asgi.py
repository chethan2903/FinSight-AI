import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "marketmind.settings")

# Get standard ASGI application
django_asgi_app = get_asgi_application()

# Import routing inside the scope to ensure Django models are loaded
import market.routing

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(market.routing.websocket_urlpatterns)
        ),
    }
)
