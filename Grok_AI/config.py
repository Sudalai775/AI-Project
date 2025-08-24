import os
from datetime import timedelta

class Config:
	# Secret key for session management
	SECRET_KEY = os.getenv('SECRET_KEY', 'dev-key-change-in-production')
    
	# Session configuration
	SESSION_TYPE = 'filesystem'
	PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    
	# Google OAuth configuration
	GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
	GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
    
	# Weather API
	WEATHER_API_KEY = os.getenv('WEATHER_API_KEY', 'f2a0dd0e25fb5b4ce4c6b00cc4f6aff4')
    
	# Database
	SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///assistant.db')
	SQLALCHEMY_TRACK_MODIFICATIONS = False
    
	# Environment
	ENV = os.getenv('FLASK_ENV', 'development')
	DEBUG = ENV == 'development'
