import json
import asyncio
from datetime import datetime
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
import redis
from django.contrib.auth import get_user_model

User = get_user_model()

class ChatConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        self.typing_tasks = {}

    async def connect(self):
        try:
            self.user = self.scope["user"]
            if isinstance(self.user, AnonymousUser):
                await self.close(code=4001)
                return

            self.room_name = self.scope['url_route']['kwargs']['room_name']
            self.room_group_name = f'chat_{self.room_name}'

            # Validate room access
            if not await self.validate_room_access():
                await self.close(code=4003)
                return

            # Join room group
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )

            await self.accept()

            # Update user online status
            await self.set_user_online(True)
            
            # Send room info and recent messages
            await self.send_room_info()
            await self.send_recent_messages()

            # Notify others about user joining
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'user_presence',
                    'user_id': self.user.id,
                    'username': self.user.username,
                    'action': 'joined',
                    'timestamp': datetime.now().isoformat(),
                    'online_count': await self.get_online_count(),
                }
            )

            print(f"🚀 {self.user.username} connected to {self.room_group_name}")

        except Exception as e:
            print(f"❌ Connection error: {e}")
            await self.close(code=4000)

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name') and self.room_group_name:
            # Leave room group
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

            # Update user online status
            await self.set_user_online(False)

            # Notify others about user leaving
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'user_presence',
                    'user_id': self.user.id,
                    'username': self.user.username,
                    'action': 'left',
                    'timestamp': datetime.now().isoformat(),
                    'online_count': await self.get_online_count(),
                }
            )

            # Clean up typing tasks
            if self.user.id in self.typing_tasks:
                self.typing_tasks[self.user.id].cancel()

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'message')

            # Rate limiting
            if not await self.check_rate_limit():
                await self.send_error('Rate limit exceeded. Please wait a moment.')
                return

            if message_type == 'message':
                await self.handle_message(data)
            elif message_type == 'typing_start':
                await self.handle_typing_start()
            elif message_type == 'typing_stop':
                await self.handle_typing_stop()
            elif message_type == 'message_read':
                await self.handle_message_read(data.get('message_id'))
            elif message_type == 'edit_message':
                await self.handle_edit_message(data.get('message_id'), data.get('content'))
            elif message_type == 'delete_message':
                await self.handle_delete_message(data.get('message_id'))
            elif message_type == 'react_message':
                await self.handle_message_reaction(data.get('message_id'), data.get('reaction'))

        except json.JSONDecodeError:
            await self.send_error('Invalid JSON format')
        except Exception as e:
            print(f"Error in receive: {e}")
            await self.send_error('Internal server error')

    async def handle_message(self, data):
        content = data.get('content', '').strip()
        message_type = data.get('message_type', 'text')
        reply_to_id = data.get('reply_to')
        file_data = data.get('file')

        if not content and not file_data:
            await self.send_error('Message content cannot be empty')
            return

        if len(content) > 5000:
            await self.send_error('Message too long (max 5000 characters)')
            return

        # Save message to database
        message_obj = await self.save_message(
            content=content,
            message_type=message_type,
            reply_to_id=reply_to_id,
            file_data=file_data
        )

        # Broadcast message to room
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message_id': message_obj.id,
                'content': content,
                'message_type': message_type,
                'user_id': self.user.id,
                'username': self.user.username,
                'timestamp': message_obj.timestamp.isoformat(),
                'reply_to': await self.get_reply_data(reply_to_id) if reply_to_id else None,
                'file_data': file_data,
            }
        )

    async def handle_typing_start(self):
        # Broadcast typing indicator
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_indicator',
                'user_id': self.user.id,
                'username': self.user.username,
                'is_typing': True,
            }
        )

        # Schedule typing stop after 3 seconds
        if self.user.id in self.typing_tasks:
            self.typing_tasks[self.user.id].cancel()
        
        self.typing_tasks[self.user.id] = asyncio.create_task(
            self.auto_stop_typing()
        )

    async def handle_typing_stop(self):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_indicator',
                'user_id': self.user.id,
                'username': self.user.username,
                'is_typing': False,
            }
        )

    async def handle_message_read(self, message_id):
        if message_id:
            await self.mark_message_as_read(message_id)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'message_read',
                    'message_id': message_id,
                    'user_id': self.user.id,
                    'username': self.user.username,
                    'timestamp': datetime.now().isoformat(),
                }
            )

    async def handle_edit_message(self, message_id, new_content):
        if await self.can_edit_message(message_id):
            message_obj = await self.update_message(message_id, new_content)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'message_edited',
                    'message_id': message_id,
                    'content': new_content,
                    'edited_at': message_obj.edited_at.isoformat(),
                }
            )

    async def handle_delete_message(self, message_id):
        if await self.can_delete_message(message_id):
            await self.delete_message(message_id)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'message_deleted',
                    'message_id': message_id,
                }
            )

    async def handle_message_reaction(self, message_id, reaction):
        if reaction:
            await self.add_message_reaction(message_id, reaction)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'message_reacted',
                    'message_id': message_id,
                    'user_id': self.user.id,
                    'username': self.user.username,
                    'reaction': reaction,
                    'timestamp': datetime.now().isoformat(),
                }
            )

    # Event handlers for group messages
    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message_id': event['message_id'],
            'content': event['content'],
            'message_type': event['message_type'],
            'user_id': event['user_id'],
            'username': event['username'],
            'timestamp': event['timestamp'],
            'reply_to': event.get('reply_to'),
            'file_data': event.get('file_data'),
        }))

    async def user_presence(self, event):
        await self.send(text_data=json.dumps({
            'type': 'user_presence',
            'user_id': event['user_id'],
            'username': event['username'],
            'action': event['action'],
            'timestamp': event['timestamp'],
            'online_count': event['online_count'],
        }))

    async def typing_indicator(self, event):
        await self.send(text_data=json.dumps({
            'type': 'typing_indicator',
            'user_id': event['user_id'],
            'username': event['username'],
            'is_typing': event['is_typing'],
        }))

    async def message_read(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message_read',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'username': event['username'],
            'timestamp': event['timestamp'],
        }))

    async def message_edited(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message_edited',
            'message_id': event['message_id'],
            'content': event['content'],
            'edited_at': event['edited_at'],
        }))

    async def message_deleted(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message_deleted',
            'message_id': event['message_id'],
        }))

    async def message_reacted(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message_reacted',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'username': event['username'],
            'reaction': event['reaction'],
            'timestamp': event['timestamp'],
        }))

    # Utility methods
    async def auto_stop_typing(self):
        await asyncio.sleep(3)
        await self.handle_typing_stop()

    async def send_room_info(self):
        room_info = await self.get_room_info()
        await self.send(text_data=json.dumps({
            'type': 'room_info',
            'room': room_info,
        }))

    async def send_recent_messages(self):
        messages = await self.get_recent_messages()
        await self.send(text_data=json.dumps({
            'type': 'recent_messages',
            'messages': messages,
        }))

    async def send_error(self, message):
        await self.send(text_data=json.dumps({
            'type': 'error',
            'error': message,
        }))

    # Database operations
    @database_sync_to_async
    def validate_room_access(self):
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

    @database_sync_to_async
    def save_message(self, content, message_type, reply_to_id, file_data):
        from .models import Message, ChatRoom
        room = ChatRoom.objects.get(name=self.room_name)
        
        message = Message(
            room=room,
            user=self.user,
            content=content,
            message_type=message_type,
        )
        
        if reply_to_id:
            try:
                message.reply_to = Message.objects.get(id=reply_to_id)
            except Message.DoesNotExist:
                pass
        
        if file_data:
            message.file_url = file_data.get('url')
            message.file_name = file_data.get('name')
            message.file_size = file_data.get('size')
        
        message.save()
        return message

    @database_sync_to_async
    def set_user_online(self, status):
        from .models import UserProfile
        profile, created = UserProfile.objects.get_or_create(user=self.user)
        profile.is_online = status
        profile.save()

    @database_sync_to_async
    def get_online_count(self):
        from .models import UserProfile
        return UserProfile.objects.filter(is_online=True).count()

    @database_sync_to_async
    def get_room_info(self):
        from .models import ChatRoom, RoomMembership
        room = ChatRoom.objects.get(name=self.room_name)
        members_count = RoomMembership.objects.filter(room=room, is_banned=False).count()
        
        return {
            'name': room.name,
            'title': room.title,
            'description': room.description,
            'members_count': members_count,
            'is_private': room.is_private,
        }

    @database_sync_to_async
    def get_recent_messages(self, limit=50):
        from .models import Message, ChatRoom
        from .serializers import MessageSerializer
        
        room = ChatRoom.objects.get(name=self.room_name)
        messages = Message.objects.filter(
            room=room, 
            is_deleted=False
        ).select_related('user', 'reply_to').order_by('-timestamp')[:limit]
        
        return MessageSerializer(messages, many=True).data

    @database_sync_to_async
    def get_reply_data(self, message_id):
        from .models import Message
        from .serializers import MessageSerializer
        
        try:
            message = Message.objects.get(id=message_id)
            return MessageSerializer(message).data
        except Message.DoesNotExist:
            return None

    @database_sync_to_async
    def mark_message_as_read(self, message_id):
        from .models import MessageReadReceipt, Message
        try:
            message = Message.objects.get(id=message_id)
            MessageReadReceipt.objects.get_or_create(message=message, user=self.user)
        except Message.DoesNotExist:
            pass

    @database_sync_to_async
    def can_edit_message(self, message_id):
        from .models import Message
        try:
            message = Message.objects.get(id=message_id)
            return message.user == self.user
        except Message.DoesNotExist:
            return False

    @database_sync_to_async
    def update_message(self, message_id, new_content):
        from .models import Message
        message = Message.objects.get(id=message_id)
        message.content = new_content
        message.is_edited = True
        message.edited_at = datetime.now()
        message.save()
        return message

    @database_sync_to_async
    def can_delete_message(self, message_id):
        from .models import Message, RoomMembership
        try:
            message = Message.objects.get(id=message_id)
            if message.user == self.user:
                return True
            
            # Check if user is admin/moderator of the room
            room_membership = RoomMembership.objects.get(room=message.room, user=self.user)
            return room_membership.role in ['admin', 'moderator']
        except (Message.DoesNotExist, RoomMembership.DoesNotExist):
            return False

    @database_sync_to_async
    def delete_message(self, message_id):
        from .models import Message
        message = Message.objects.get(id=message_id)
        message.is_deleted = True
        message.deleted_at = datetime.now()
        message.save()

    @database_sync_to_async
    def add_message_reaction(self, message_id, reaction):
        from .models import Message
        # Implementation for reactions would go here
        pass

    async def check_rate_limit(self):
        key = f"rate_limit:{self.user.id}:{self.room_name}"
        try:
            current = self.redis_client.incr(key)
            if current == 1:
                self.redis_client.expire(key, 60)  # 1 minute window
            return current <= 30  # 30 messages per minute
        except redis.ConnectionError:
            return True  # Skip rate limiting if Redis is down