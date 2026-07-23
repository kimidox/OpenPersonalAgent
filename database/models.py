from datetime import datetime

from sqlalchemy import Column, String, Integer, TIMESTAMP, JSON, Text
from sqlalchemy.ext.declarative import declarative_base

from database.utils import get_local_time

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True)
    created_at = Column(TIMESTAMP, default=get_local_time)
    updated_at = Column(TIMESTAMP, default=get_local_time)
    
    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class Conversations(Base):
    __tablename__ = 'conversations'
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String, unique=True, index=True)
    user_id = Column(String, index=True)
    title = Column(String)
    active_skill_ids = Column(JSON, default=list)
    type = Column(String, default='agent_conversation')
    default_skills = Column(JSON, default=list)
    created_at = Column(TIMESTAMP, default=get_local_time)
    updated_at = Column(TIMESTAMP, default=get_local_time)
    
    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class Messages(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String, unique=True, index=True)
    conversation_id = Column(String, index=True)
    role = Column(String)
    content = Column(Text)
    ext = Column(JSON)
    created_at = Column(TIMESTAMP, default=get_local_time)
    updated_at = Column(TIMESTAMP, default=get_local_time)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class ScheduledTask(Base):
    __tablename__ = 'scheduled_tasks'
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String, unique=True, index=True)
    user_id = Column(String, index=True)
    title = Column(String)
    content = Column(Text)
    trigger_time = Column(TIMESTAMP)
    repeat_type = Column(String, default='none')
    notification_type = Column(String, default='system')
    status = Column(String, default='pending')
    execution_type = Column(String, default='notification')
    execution_chain = Column(Text, nullable=True)
    source_conversation_id = Column(String, nullable=True)
    skill_ids = Column(JSON, default=list)
    created_at = Column(TIMESTAMP, default=get_local_time)
    updated_at = Column(TIMESTAMP, default=get_local_time)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
