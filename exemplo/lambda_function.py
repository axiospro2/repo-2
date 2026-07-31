import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from app.main import handler as lambda_handler
