import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add a secret key for JWT token generation
SECRET_KEY = os.environ.get('SECRET_KEY', 'your-super-secret-key-change-me-in-production')

# Database Configuration
DB_USERNAME = os.environ.get('PYTHONANYWHERE_USERNAME')
DB_PASSWORD = os.environ.get('MYSQL_PASSWORD')
DB_HOSTNAME = os.environ.get('MYSQL_HOSTNAME')
DB_NAME = os.environ.get('DATABASE_NAME')

# Database URL
DATABASE_URL = f'mysql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOSTNAME}/{DB_NAME}?charset=utf8mb4'

# Database Pool Settings
DATABASE_POOL_OPTIONS = {
    'pool_size': 10,
    'pool_recycle': 280,
    'pool_pre_ping': True,
    'pool_timeout': 30,
    'max_overflow': 5
}

# Google Drive Settings
FOLDER_ID = os.environ.get('FOLDER_ID')
GOOGLE_CREDENTIALS_PATH = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'credentials.json')
DRIVE_SCOPES = ['https://www.googleapis.com/auth/drive.metadata.readonly']

# CORS Settings
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')
CORS_ORIGINS = [
    'http://localhost:3000',  # Development
    'https://drive-c-frontend-hy5kwvqhk-tobias-lundhs-projects.vercel.app',  # Vercel deployment
    'https://drive-c-frontend.vercel.app', # In case the URL changes to production
    'https://drive-c-frontend-git-split-tobias-lundhs-projects.vercel.app',
    'https://drive-c-frontend-5q8e56t64-tobias-lundhs-projects.vercel.app',
    'https://drive-c-frontend-git-main-2-tobias-lundhs-projects.vercel.app',
    os.environ.get('FRONTEND_URL', ''),  # From environment variable
]

# Clean empty strings from CORS_ORIGINS
CORS_ORIGINS = [origin for origin in CORS_ORIGINS if origin]

# Extended CORS Configuration
CORS_CONFIG = {
    "origins": CORS_ORIGINS,
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"],
    "expose_headers": ["Content-Range", "X-Total-Count"],
    "supports_credentials": True,
    "max_age": 600  # Cache preflight requests for 10 minutes
}
