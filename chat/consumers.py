import json
import asyncio
from datetime import datetime
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
import redis
from django.contrib.auth import get_user_model
import logging

logger = logging.getLogger('websockets')

User = get_user_model()

class RobustChatConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.redis_client = redis.Redis(
                host='localhost', 
                port=6379, 
                db=0, 
                decode_responses=True,
                socket_connect_timeout=5,
                retry_on_timeout=True
            )
            self.redis_client.ping()  # Test connection
        except redis.ConnectionError:
            logger.warning("Redis connection failed, using in-memory storage")
            self.redis_client = None
        
        self.typing_tasks = {}
        self.room_name = None
        self.room_group_name = None
        self.user = None

    async def connect(self):
        try:
            self.user = self.scope["user"]
            
            # Authentication check
            if isinstance(self.user, AnonymousUser):
                logger.warning("Anonymous user attempted WebSocket connection")
                await self.close(code=4001)
                return

            self.room_name = self.scope['url_route']['kwargs']['room_name']
            self.room_group_name = f'chat_{self.room_name}'

            # Validate room access
            if not await self.validate_room_access():
                logger.warning(f"User {self.user.id} denied access to room {self.room_name}")
                await self.close(code=4003)
                return

            # Rate limiting for connections
            if not await self.check_connection_rate_limit():
                await self.close(code=4004)
                return

            # Join room group
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )

            await self.accept()

            # Update user presence
            await self.set_user_presence(True)
            
            # Send initial data
            await self.send_initial_data()

            # Notify room about user join
            await self.broadcast_user_presence('joined')

            logger.info(f"User {self.user.username} connected to {self.room_group_name}")

        except Exception as e:
            logger.error(f"Connection error for user {getattr(self.user, 'id', 'unknown')}: {e}")
            await self.close(code=4000)

    async def disconnect(self, close_code):
        try:
            if hasattr(self, 'room_group_name') and self.room_group_name:
                # Clean up typing tasks
                if self.user.id in self.typing_tasks:
                    self.typing_tasks[self.user.id].cancel()
                    del self.typing_tasks[self.user.id]

                # Update user presence
                await self.set_user_presence(False)

                # Notify room about user leave
                await self.broadcast_user_presence('left')

                # Leave room group
                await self.channel_layer.group_discard(
                    self.room_group_name,
                    self.channel_name
                )

            logger.info(f"User {self.user.username} disconnected from {self.room_group_name}")

        except Exception as e:
            logger.error(f"Disconnection error: {e}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'message')

            # Validate message type
            if message_type not in ['message', 'typing_start', 'typing_stop', 'message_read', 
                                  'edit_message', 'delete_message', 'react_message']:
                await self.send_error('Invalid message type')
                return

            # Rate limiting
            if not await self.check_message_rate_limit():
                await self.send_error('Rate limit exceeded. Please wait a moment.')
                return

            # Route to appropriate handler
            handler_map = {
                'message': self.handle_message,
                'typing_start': self.handle_typing_start,
                'typing_stop': self.handle_typing_stop,
                'message_read': self.handle_message_read,
                'edit_message': self.handle_edit_message,
                'delete_message': self.handle_delete_message,
                'react_message': self.handle_message_reaction,
            }

            if message_type in handler_map:
                await handler_map[message_type](data)

        except json.JSONDecodeError:
            await self.send_error('Invalid JSON format')
        except KeyError as e:
            await self.send_error(f'Missing required field: {e}')
        except Exception as e:
            logger.error(f"Error processing message from {self.user.username}: {e}")
            await self.send_error('Internal server error')

    async def handle_message(self, data):
        """Handle new message creation"""
        content = data.get('content', '').strip()
        message_type = data.get('message_type', 'text')
        reply_to_id = data.get('reply_to')
        file_data = data.get('file')

        # Validation
        validation_error = await self.validate_message(content, message_type, file_data)
        if validation_error:
            await self.send_error(validation_error)
            return

        # Check room permissions
        if not await self.can_send_message():
            await self.send_error('You do not have permission to send messages in this room')
            return

        # Save to database
        try:
            message_obj = await self.save_message(
                content=content,
                message_type=message_type,
                reply_to_id=reply_to_id,
                file_data=file_data
            )
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            await self.send_error('Failed to save message')
            return

        # Broadcast to room
        await self.broadcast_message(message_obj)

    async def handle_typing_start(self, data):
        """Handle typing indicator start"""
        await self.broadcast_typing_indicator(True)

        # Cancel existing typing task
        if self.user.id in self.typing_tasks:
            self.typing_tasks[self.user.id].cancel()
        
        # Schedule auto stop
        self.typing_tasks[self.user.id] = asyncio.create_task(
            self.auto_stop_typing()
        )

    async def handle_typing_stop(self, data):
        """Handle typing indicator stop"""
        await self.broadcast_typing_indicator(False)

    async def handle_message_read(self, data):
        """Handle message read receipt"""
        message_id = data.get('message_id')
        if not message_id:
            await self.send_error('message_id is required')
            return

        try:
            await self.mark_message_as_read(message_id)
            await self.broadcast_read_receipt(message_id)
        except Exception as e:
            logger.error(f"Error marking message as read: {e}")

    async def handle_edit_message(self, data):
        """Handle message editing"""
        message_id = data.get('message_id')
        new_content = data.get('content', '').strip()

        if not message_id:
            await self.send_error('message_id is required')
            return

        if not new_content:
            await self.send_error('Message content cannot be empty')
            return

        # Check permissions and edit
        try:
            if await self.can_edit_message(message_id):
                message_obj = await self.update_message(message_id, new_content)
                await self.broadcast_message_edit(message_obj)
            else:
                await self.send_error('You cannot edit this message')
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            await self.send_error('Failed to edit message')

    async def handle_delete_message(self, data):
        """Handle message deletion"""
        message_id = data.get('message_id')
        if not message_id:
            await self.send_error('message_id is required')
            return

        try:
            if await self.can_delete_message(message_id):
                await self.delete_message(message_id)
                await self.broadcast_message_deletion(message_id)
            else:
                await self.send_error('You cannot delete this message')
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            await self.send_error('Failed to delete message')

    async def handle_message_reaction(self, data):
        """Handle message reactions"""
        message_id = data.get('message_id')
        reaction = data.get('reaction')

        if not message_id or not reaction:
            await self.send_error('message_id and reaction are required')
            return

        # Validate reaction type
        valid_reactions = ['like', 'love', 'laugh', 'wow', 'sad', 'angry']
        if reaction not in valid_reactions:
            await self.send_error(f'Invalid reaction. Must be one of: {", ".join(valid_reactions)}')
            return

        try:
            await self.add_message_reaction(message_id, reaction)
            await self.broadcast_reaction(message_id, reaction)
        except Exception as e:
            logger.error(f"Error adding reaction: {e}")
            await self.send_error('Failed to add reaction')

    # Broadcast Methods
    async def broadcast_message(self, message_obj):
        """Broadcast new message to room"""
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message_id': str(message_obj.id),
                'content': message_obj.content,
                'message_type': message_obj.message_type,
                'user_id': str(self.user.id),
                'username': self.user.username,
                'display_name': self.user.get_full_name(),
                'timestamp': message_obj.timestamp.isoformat(),
                'reply_to': await self.get_reply_data(message_obj.reply_to_id),
                'file_data': await self.get_file_data(message_obj),
            }
        )

    async def broadcast_typing_indicator(self, is_typing):
        """Broadcast typing indicator"""
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_indicator',
                'user_id': str(self.user.id),
                'username': self.user.username,
                'display_name': self.user.get_full_name(),
                'is_typing': is_typing,
                'timestamp': datetime.now().isoformat(),
            }
        )

    async def broadcast_user_presence(self, action):
        """Broadcast user presence change"""
        online_count = await self.get_online_count()
        
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_presence',
                'user_id': str(self.user.id),
                'username': self.user.username,
                'display_name': self.user.get_full_name(),
                'action': action,
                'timestamp': datetime.now().isoformat(),
                'online_count': online_count,
            }
        )

    async def broadcast_read_receipt(self, message_id):
        """Broadcast read receipt"""
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'message_read',
                'message_id': message_id,
                'user_id': str(self.user.id),
                'username': self.user.username,
                'display_name': self.user.get_full_name(),
                'timestamp': datetime.now().isoformat(),
            }
        )

    async def broadcast_message_edit(self, message_obj):
        """Broadcast message edit"""
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'message_edited',
                'message_id': str(message_obj.id),
                'content': message_obj.content,
                'edited_at': message_obj.edited_at.isoformat(),
                'user_id': str(self.user.id),
            }
        )

    async def broadcast_message_deletion(self, message_id):
        """Broadcast message deletion"""
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'message_deleted',
                'message_id': message_id,
                'user_id': str(self.user.id),
                'username': self.user.username,
                'timestamp': datetime.now().isoformat(),
            }
        )

    async def broadcast_reaction(self, message_id, reaction):
        """Broadcast message reaction"""
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'message_reacted',
                'message_id': message_id,
                'user_id': str(self.user.id),
                'username': self.user.username,
                'display_name': self.user.get_full_name(),
                'reaction': reaction,
                'timestamp': datetime.now().isoformat(),
            }
        )

    # Event Handlers (send to individual clients)
    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message_id': event['message_id'],
            'content': event['content'],
            'message_type': event['message_type'],
            'user_id': event['user_id'],
            'username': event['username'],
            'display_name': event['display_name'],
            'timestamp': event['timestamp'],
            'reply_to': event.get('reply_to'),
            'file_data': event.get('file_data'),
        }))

    async def user_presence(self, event):
        await self.send(text_data=json.dumps({
            'type': 'user_presence',
            'user_id': event['user_id'],
            'username': event['username'],
            'display_name': event['display_name'],
            'action': event['action'],
            'timestamp': event['timestamp'],
            'online_count': event['online_count'],
        }))

    async def typing_indicator(self, event):
        await self.send(text_data=json.dumps({
            'type': 'typing_indicator',
            'user_id': event['user_id'],
            'username': event['username'],
            'display_name': event['display_name'],
            'is_typing': event['is_typing'],
            'timestamp': event['timestamp'],
        }))

    async def message_read(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message_read',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'username': event['username'],
            'display_name': event['display_name'],
            'timestamp': event['timestamp'],
        }))

    async def message_edited(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message_edited',
            'message_id': event['message_id'],
            'content': event['content'],
            'edited_at': event['edited_at'],
            'user_id': event['user_id'],
        }))

    async def message_deleted(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message_deleted',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'username': event['username'],
            'timestamp': event['timestamp'],
        }))

    async def message_reacted(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message_reacted',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'username': event['username'],
            'display_name': event['display_name'],
            'reaction': event['reaction'],
            'timestamp': event['timestamp'],
        }))

    # Utility Methods
    async def auto_stop_typing(self):
        """Automatically stop typing after 3 seconds"""
        await asyncio.sleep(3)
        await self.broadcast_typing_indicator(False)

    async def send_initial_data(self):
        """Send initial room data to client"""
        try:
            room_info = await self.get_room_info()
            recent_messages = await self.get_recent_messages()
            online_users = await self.get_online_users()

            await self.send(text_data=json.dumps({
                'type': 'initial_data',
                'room': room_info,
                'messages': recent_messages,
                'online_users': online_users,
                'user_id': str(self.user.id),
            }))
        except Exception as e:
            logger.error(f"Error sending initial data: {e}")

    async def send_error(self, message):
        """Send error message to client"""
        await self.send(text_data=json.dumps({
            'type': 'error',
            'error': message,
            'timestamp': datetime.now().isoformat(),
        }))

    async def validate_message(self, content, message_type, file_data):
        """Validate message data"""
        if not content and not file_data:
            return 'Message content cannot be empty'
        
        if content and len(content) > 5000:
            return 'Message too long (max 5000 characters)'
        
        if message_type not in ['text', 'image', 'file', 'system']:
            return 'Invalid message type'
        
        return None

    # Rate Limiting
    async def check_connection_rate_limit(self):
        """Rate limit connection attempts"""
        if not self.redis_client:
            return True
            
        key = f"conn_rate_limit:{self.user.id}"
        try:
            current = self.redis_client.incr(key)
            if current == 1:
                self.redis_client.expire(key, 60)  # 1 minute window
            return current <= 10  # 10 connections per minute
        except redis.RedisError:
            return True

    async def check_message_rate_limit(self):
        """Rate limit message sending"""
        if not self.redis_client:
            return True
            
        key = f"msg_rate_limit:{self.user.id}:{self.room_name}"
        try:
            current = self.redis_client.incr(key)
            if current == 1:
                self.redis_client.expire(key, 60)  # 1 minute window
            return current <= 30  # 30 messages per minute
        except redis.RedisError:
            return True

    # Database Operations (with proper error handling)
    @database_sync_to_async
    def validate_room_access(self):
        """Validate user has access to room"""
        from .models import ChatRoom, RoomMembership
        try:
            room = ChatRoom.objects.get(name=self.room_name, is_active=True)
            return RoomMembership.objects.filter(
                room=room, 
                user=self.user, 
                is_banned=False
            ).exists() or room.created_by == self.user
        except ChatRoom.DoesNotExist:
            return False
        except Exception as e:
            logger.error(f"Error validating room access: {e}")
            return False

    @database_sync_to_async
    def can_send_message(self):
        """Check if user can send messages in room"""
        from .models import RoomMembership
        try:
            membership = RoomMembership.objects.get(
                room__name=self.room_name, 
                user=self.user
            )
            return not membership.is_banned
        except RoomMembership.DoesNotExist:
            return False

    @database_sync_to_async
    def save_message(self, content, message_type, reply_to_id, file_data):
        """Save message to database"""
        from .models import Message, ChatRoom
        try:
            room = ChatRoom.objects.get(name=self.room_name)
            
            message = Message.objects.create(
                room=room,
                user=self.user,
                content=content,
                message_type=message_type,
            )
            
            if reply_to_id:
                try:
                    message.reply_to = Message.objects.get(id=reply_to_id, room=room)
                    message.save()
                except Message.DoesNotExist:
                    pass
            
            if file_data:
                message.file_url = file_data.get('url')
                message.file_name = file_data.get('name')
                message.file_size = file_data.get('size')
                message.save()
            
            # Update room last activity
            room.last_activity = datetime.now()
            room.save()
            
            return message
            
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            raise

    @database_sync_to_async
    def set_user_presence(self, is_online):
        """Update user online status"""
        from .models import UserProfile
        try:
            profile, created = UserProfile.objects.get_or_create(user=self.user)
            profile.online = is_online
            profile.last_seen = datetime.now()
            profile.save()

            # Update room presence in Redis for quick access
            if self.redis_client:
                key = f"room_presence:{self.room_name}"
                if is_online:
                    self.redis_client.sadd(key, str(self.user.id))
                else:
                    self.redis_client.srem(key, str(self.user.id))
                    
        except Exception as e:
            logger.error(f"Error setting user presence: {e}")

    @database_sync_to_async
    def get_online_count(self):
        """Get number of online users in room"""
        if self.redis_client:
            try:
                key = f"room_presence:{self.room_name}"
                return self.redis_client.scard(key)
            except redis.RedisError:
                pass
                
        # Fallback to database
        from .models import UserProfile
        return UserProfile.objects.filter(online=True).count()

    @database_sync_to_async
    def get_online_users(self):
        """Get list of online users"""
        from .models import UserProfile
        from .serializers import UserLiteSerializer
        
        online_profiles = UserProfile.objects.filter(online=True).select_related('user')
        return UserLiteSerializer([profile.user for profile in online_profiles], many=True).data

    @database_sync_to_async
    def get_room_info(self):
        """Get room information"""
        from .models import ChatRoom, RoomMembership
        from .serializers import ChatRoomSerializer
        
        room = ChatRoom.objects.get(name=self.room_name)
        return ChatRoomSerializer(room, context={'user': self.user}).data

    @database_sync_to_async
    def get_recent_messages(self, limit=50):
        """Get recent messages for room"""
        from .models import Message, ChatRoom
        from .serializers import MessageSerializer
        
        room = ChatRoom.objects.get(name=self.room_name)
        messages = Message.objects.filter(
            room=room, 
            is_deleted=False
        ).select_related('user', 'reply_to').prefetch_related('reactions').order_by('-timestamp')[:limit]
        
        return MessageSerializer(messages.reverse(), many=True).data  # Reverse to get chronological order

    @database_sync_to_async
    def get_reply_data(self, reply_to_id):
        """Get reply message data"""
        if not reply_to_id:
            return None
            
        from .models import Message
        from .serializers import MessageSerializer
        
        try:
            message = Message.objects.get(id=reply_to_id)
            return MessageSerializer(message).data
        except Message.DoesNotExist:
            return None

    @database_sync_to_async
    def get_file_data(self, message_obj):
        """Get file data for message"""
        if not message_obj.file_url:
            return None
            
        return {
            'url': message_obj.file_url,
            'name': message_obj.file_name,
            'size': message_obj.file_size,
            'type': message_obj.file_type,
        }

    # ... (other database operations with proper error handling)

# Additional consumer for typing indicators only
class TypingConsumer(AsyncWebsocketConsumer):
    """Lightweight consumer for typing indicators only"""
    async def connect(self):
        # Implementation for typing-only connections
        pass

# Consumer for notifications
class NotificationConsumer(AsyncWebsocketConsumer):
    """Consumer for user-specific notifications"""
    async def connect(self):
        # Implementation for user notification channel
        pass